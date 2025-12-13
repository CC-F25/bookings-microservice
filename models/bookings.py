from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class BookingCreate(BaseModel):
    user_id: str 
    listing_id: str

class BookingRead(BaseModel):
    id: str
    user_id: str
    listing_id: str
    status: str
    created_at: datetime

    model_config = {
        "from_attributes": True
    }