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

from database_connection import Base, engine, get_db
from models.booking_sql import BookingDB

port = int(os.environ.get("FASTAPIPORT", 8000))

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
PREFS_URL = os.environ.get("PREFERENCES_SERVICE_URL")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Bookings Composite Service")

# Create Booking (Logical Foreign Keys with Validation)
@app.post("/bookings", response_model=BookingRead, status_code=201)
async def create_booking(booking: BookingCreate, db: Session = Depends(get_db)):
    async with httpx.AsyncClient() as client:
        # CHECK 1: Validate User
        try:
            user_rsp = await client.get(f"{USERS_URL}/users/{booking.user_id}")
            if user_rsp.status_code == 404:
                raise HTTPException(status_code=404, detail="User not found")
        except httpx.RequestError:
             raise HTTPException(status_code=503, detail="Users Service Unavailable")

        # CHECK 2: Validate Listing
        """
        listing_rsp = await client.get(f"{LISTINGS_URL}/listings/{booking.listing_id}")
        if listing_rsp.status_code == 404:
            raise HTTPException(status_code=404, detail="Listing not found")
        """
        print(f"WARNING: Mocking Listing Check for {booking.listing_id}")

        # CHECK 3: Validate Preferences
        """
        prefs_rsp = await client.get(f"{PREFS_URL}/preferences/{booking.user_id}")
        if prefs_rsp.status_code == 404:
             # Optional: Maybe we warn them, or maybe we block them?
             print("User has no preferences set.")
        """
        print(f"WARNING: Mocking Preferences Check for User {booking.user_id}")

    # Create Booking in Local DB
    new_booking = BookingDB(
        user_id=booking.user_id,
        listing_id=booking.listing_id
    )
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    
    return new_booking

# Composite Data Aggregation (Parallel Execution)
# This satisfies the "Use threads/async for parallel execution" requirement
@app.get("/bookings/{booking_id}/details")
async def get_booking_details(booking_id: str, db: Session = Depends(get_db)):
    
    # Get local booking data
    booking = db.query(BookingDB).filter(BookingDB.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Fetch data from ALL Atomic Services in Parallel
    async with httpx.AsyncClient() as client:
        # Define the tasks
        task_user = client.get(f"{USERS_URL}/users/{booking.user_id}")
        task_listing = client.get(f"{LISTINGS_URL}/listings/{booking.listing_id}")
        task_prefs = client.get(f"{PREFS_URL}/preferences/{booking.user_id}")

        # Execute all 3 at once (Parallel)
        # return_exceptions=True so one failure doesn't crash the whole request
        responses = await asyncio.gather(task_user, task_listing, task_prefs, return_exceptions=True)
        
        user_rsp, listing_rsp, prefs_rsp = responses

    # Construct the Composite Response
    return {
        "booking_info": booking,
        # Check if the calls succeeded before accessing .json()
        "user_info": user_rsp.json() if not isinstance(user_rsp, Exception) and user_rsp.status_code == 200 else "Unavailable",
        "listing_info": "Mock Listing Data" if isinstance(listing_rsp, Exception) else listing_rsp.json(),
        "preferences_info": "Mock Preferences Data" if isinstance(prefs_rsp, Exception) else prefs_rsp.json()
    }

# -----------------------------------------------------------------------------
# Entrypoint for `python main.py`
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)