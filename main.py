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
from sqlalchemy import text, and_

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
# Helper Functions (Synchronous for Threading)
# -----------------------------------------------------------------------------

def fetch_json(url: str):
    """
    Synchronous helper to be run in a separate thread
    Used to demonstrate multi-threading parallelism
    """
    try:
        # Use synchronous httpx.get (blocking I/O)
        r = httpx.get(url, timeout=5.0)
        if r.status_code != 200:
            return "Unavailable"
        return r.json()
    except Exception:
        return "Unavailable"
    
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
# Bookings configuration
# -----------------------------------------------------------------------------

# Configuration: Load URLs for ALL Atomic Services
USERS_URL = os.environ.get("USERS_SERVICE_URL")
LISTINGS_URL = os.environ.get("LISTINGS_SERVICE_URL")

Base.metadata.create_all(bind=engine)

# -----------------------------------------------------------------------------
# Bookings endpoints
# -----------------------------------------------------------------------------

# Create Booking with Logical Foreign Keys with Validation
@app.post("/bookings", response_model=BookingRead, status_code=201)
async def create_booking(booking: BookingCreate, db: Session = Depends(get_db), token_payload: dict = Depends(require_auth)):

    user_id_from_token = token_payload.get("sub")
    if user_id_from_token != booking.user_id:
        raise HTTPException(status_code=403, detail="You cannot book for someone else")

    # Availability Check (Prevent Double Booking)
    # Check if this listing is already booked for this specific date
    existing_booking = db.query(BookingDB).filter(
        and_(
            BookingDB.listing_id == booking.listing_id,
            BookingDB.booking_date == booking.booking_date
        )
    ).first()

    if existing_booking:
        # If the user trying to book is the same person who already booked it
        if existing_booking.user_id == booking.user_id:
            raise HTTPException(status_code=409, detail="You have already booked this listing for this date.")
        # If someone else booked it
        raise HTTPException(status_code=409, detail="This listing is unavailable for the selected date.")

    async with httpx.AsyncClient() as client:
        # CHECK 1: Validate User
        try:
            user_rsp = await client.get(f"{USERS_URL}/users/{booking.user_id}")
            if user_rsp.status_code == 404:
                raise HTTPException(status_code=404, detail="User not found")
            if user_rsp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"User Validation Failed: {user_rsp.text}")
        except httpx.RequestError:
             raise HTTPException(status_code=503, detail="Users Service Unavailable")

        # CHECK 2: Validate Listing
        try:
            listing_rsp = await client.get(f"{LISTINGS_URL}/listings/{booking.listing_id}")
            if listing_rsp.status_code == 404:
                raise HTTPException(status_code=404, detail="Listing not found")
        except httpx.RequestError:
            print(f"CRITICAL: Could not connect to Listings Service")
            raise HTTPException(status_code=503, detail="Listings Service Unavailable")

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

# Composite Data Aggregation with Parallel Execution using THREADS
@app.get("/bookings/{booking_id}/details")
async def get_booking_details(booking_id: str, db: Session = Depends(get_db)):
    
    # Get local booking data
    booking = db.query(BookingDB).filter(BookingDB.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Use asyncio.to_thread to run the synchronous 'fetch_json' in separate THREADS
    # This explicitly satisfies the requirement for "Parallel execution using threads"
    user_task = asyncio.to_thread(fetch_json, f"{USERS_URL}/users/{booking.user_id}")
    listing_task = asyncio.to_thread(fetch_json, f"{LISTINGS_URL}/listings/{booking.listing_id}")

    # Run both threads concurrently and wait for results
    user_info, listing_info = await asyncio.gather(user_task, listing_task)

    # Construct the Composite Response
    return {
        "booking_info": booking,
        "user_info": user_info,  
        "listing_info": listing_info 
    }

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

# Delete all bookings for a specific user (Cascading Delete Support)
@app.delete("/bookings/user/{user_id}", status_code=204)
def delete_all_user_bookings(user_id: str, db: Session = Depends(get_db)):
    """
    Deletes all bookings associated with a specific user ID.
    This should be called when a User is deleted to ensure data consistency.
    """
    bookings = db.query(BookingDB).filter(BookingDB.user_id == user_id).all()
    for booking in bookings:
        db.delete(booking)
    
    db.commit()
    return None

# ---------------------------------------------------------------------------
# ATOMIC SERVICE DELEGATION (Encapsulate & Expose)
# ---------------------------------------------------------------------------

@app.get("/users/{user_id}")
async def get_user_proxy(user_id: str):
    """
    Proxy endpoint to expose Users Service API via the Composite Service.
    """
    async with httpx.AsyncClient() as client:
        try:
            # Delegate to the Atomic Users Service
            resp = await client.get(f"{USERS_URL}/users/{user_id}")
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="User not found")
            return resp.json()
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Users Service Unavailable")

@app.get("/listings/{listing_id}")
async def get_listing_proxy(listing_id: str):
    """
    Proxy endpoint to expose Listings Service API via the Composite Service.
    Delegates to the existing Listings Proxy/Service.
    """
    async with httpx.AsyncClient() as client:
        try:
            # Delegate to the Atomic Listings Service
            resp = await client.get(f"{LISTINGS_URL}/listings/{listing_id}")
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Listing not found")
            return resp.json()
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Listings Service Unavailable")

# -----------------------------------------------------------------------------
# Entrypoint for `python main.py`
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)