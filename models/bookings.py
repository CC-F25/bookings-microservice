from pydantic import BaseModel

class BookingCreate(BaseModel):
    user_id: int
    listing_id: int
    preference_id: int


    