from sqlalchemy import Column, String, DateTime, Integer
from database_connection import Base
import uuid
from datetime import datetime

class BookingDB(Base):
    __tablename__ = "bookings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # These are the "Logical Foreign Keys"
    user_id = Column(String(36), nullable=False)
    listing_id = Column(String(36), nullable=False)
    
    status = Column(String(20), default="confirmed")
    created_at = Column(DateTime, default=datetime.utcnow)