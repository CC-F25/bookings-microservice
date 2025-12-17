from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class BookingCreate(BaseModel):
    user_id: str 
    listing_id: str
    booking_date: datetime

class BookingRead(BaseModel):
    id: str
    user_id: str
    listing_id: str
    status: str
    booking_date: datetime
    created_at: datetime

    model_config = {
        "from_attributes": True
    }