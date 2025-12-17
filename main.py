from __future__ import annotations

import os
import socket
from datetime import datetime

from typing import Dict, List, Optional
from uuid import UUID

import httpx
import asyncio

from fastapi import FastAPI, HTTPException, Query, Path, Depends
import uvicorn
from models.health import Health
from models.bookings import BookingCreate, BookingRead

from sqlalchemy.orm import Session
from sqlalchemy import text

from database_connection import Base, engine, get_db
from models.bookings_sql import BookingDB

from fastapi import Header
from jose import jwt, JWTError

port = int(os.environ.get("FASTAPIPORT", 8080))


# -----------------------------------------------------------------------------
# JWT Authentication
# AUTH CONFIGURATION
JWT_SECRET = os.environ.get("JWT_SECRET", "my_super_secret_key")
JWT_ALGO = "HS256"

def require_auth(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.replace("Bearer ", "")
    try:
        # This verifies the signature using the SHARED secret
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(
    title="Bookings API",
    description="FastAPI app using Pydantic v2 models for Bookings Microservice",
    version="0.1.0",
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5000",                     # Firebase local emulator
        "https://cloud-computing-ui.web.app",        # deployed Firebase site
        "https://cloud-computing-ui.firebaseapp.com" # alt Firebase domain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Root
# -----------------------------------------------------------------------------
@app.get("/")
def root():
    return {"message": "Welcome to the Bookings API. See /docs for OpenAPI UI."}


# -----------------------------------------------------------------------------
# test-db endpoint
# -----------------------------------------------------------------------------

@app.get("/test-db")
def test_db_connection(db: Session = Depends(get_db)):
    try:
        # run a simple query to test the connection
        result = db.execute(text("SELECT 1")).fetchone()
        return {"status": "success", "result": result[0]}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
# -----------------------------------------------------------------------------
# Health endpoints
# -----------------------------------------------------------------------------

def make_health(echo: Optional[str], path_echo: Optional[str]=None) -> Health:
    return Health(
        status=200,
        status_message="OK",
        timestamp=datetime.utcnow().isoformat() + "Z",
        ip_address=socket.gethostbyname(socket.gethostname()),
        echo=echo,
        path_echo=path_echo
    )

@app.get("/health", response_model=Health)
def get_health_no_path(echo: str | None = Query(None, description="Optional echo string")):
    # Works because path_echo is optional in the model
    return make_health(echo=echo, path_echo=None)

@app.get("/health/{path_echo}", response_model=Health)
def get_health_with_path(
    path_echo: str = Path(..., description="Required echo in the URL path"),
    echo: str | None = Query(None, description="Optional echo string"),
):
    return make_health(echo=echo, path_echo=path_echo)


# -----------------------------------------------------------------------------
# Bookings endpoints
# -----------------------------------------------------------------------------

# Configuration: Load URLs for ALL Atomic Services
USERS_URL = os.environ.get("USERS_SERVICE_URL")
LISTINGS_URL = os.environ.get("LISTINGS_SERVICE_URL")

Base.metadata.create_all(bind=engine)

# Create Booking with Logical Foreign Keys with Validation
@app.post("/bookings", response_model=BookingRead, status_code=201)
async def create_booking(booking: BookingCreate, db: Session = Depends(get_db), token_payload: dict = Depends(require_auth)):

    user_id_from_token = token_payload.get("sub")
    if user_id_from_token != booking.user_id:
        raise HTTPException(status_code=403, detail="You cannot book for someone else")

    async with httpx.AsyncClient() as client:
        # CHECK 1: Validate User
        try:
            print(f"DEBUG: Verifying user {booking.user_id} at {USERS_URL}")
            user_rsp = await client.get(f"{USERS_URL}/users/{booking.user_id}")
            
            # If User doesn't exist (404), raise error
            if user_rsp.status_code == 404:
                raise HTTPException(status_code=404, detail="User not found")
            
            # If User ID is invalid (422) or Server Error (500), raise error
            if user_rsp.status_code != 200:
                print(f"DEBUG: User validation failed with status {user_rsp.status_code}: {user_rsp.text}")
                raise HTTPException(status_code=400, detail=f"User Validation Failed: {user_rsp.text}")

        except httpx.RequestError as e:
             print(f"CRITICAL: Could not connect to Users Service: {e}")
             raise HTTPException(status_code=503, detail="Users Service Unavailable")

        # CHECK 2: Validate Listing
        """
        listing_rsp = await client.get(f"{LISTINGS_URL}/listings/{booking.listing_id}")
        if listing_rsp.status_code == 404:
            raise HTTPException(status_code=404, detail="Listing not found")
        """
        print(f"WARNING: Mocking Listing Check for {booking.listing_id}")

    # Create Booking in Local DB
    new_booking = BookingDB(
        user_id=booking.user_id,
        listing_id=booking.listing_id,
        booking_date=booking.booking_date
    )
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    
    return new_booking

# Composite Data Aggregation with Parallel Execution
@app.get("/bookings/{booking_id}/details")
async def get_booking_details(booking_id: str, db: Session = Depends(get_db)):
    
    # Get local booking data
    booking = db.query(BookingDB).filter(BookingDB.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Fetch data from Atomic Services (Users + Listings)
    async with httpx.AsyncClient() as client:
        # Define the tasks
        task_user = client.get(f"{USERS_URL}/users/{booking.user_id}")
        task_listing = client.get(f"{LISTINGS_URL}/listings/{booking.listing_id}")

        # Execute both at once
        responses = await asyncio.gather(task_user, task_listing, return_exceptions=True)
        
        user_rsp, listing_rsp = responses

    # Construct the Composite Response
    return {
        "booking_info": booking,
        "user_info": user_rsp.json() if not isinstance(user_rsp, Exception) and user_rsp.status_code == 200 else "Unavailable",
        "listing_info": listing_rsp.json() if not isinstance(listing_rsp, Exception) and listing_rsp.status_code == 200 else "Unavailable"
    }
# Composite Data Aggregation with Parallel Execution

# Get ALL bookings for a specific user
@app.get("/bookings/user/{user_id}")
def get_user_bookings(user_id: str, db: Session = Depends(get_db)):
    # Query the local database for all rows with this user_id
    user_bookings = db.query(BookingDB).filter(BookingDB.user_id == user_id).all()
    
    # Return the list
    return user_bookings


# delete booking
@app.delete("/bookings/{booking_id}", status_code=204)
def delete_booking(booking_id: str, db: Session = Depends(get_db)):
    """
    Delete a booking from the composite service
    """
    booking = db.query(BookingDB).filter(BookingDB.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    db.delete(booking)
    db.commit()
    return None

# -----------------------------------------------------------------------------
# Entrypoint for `python main.py`
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)