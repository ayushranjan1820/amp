from pydantic import BaseModel, Field
from datetime import datetime

class UserProfile(BaseModel):
    name: str
    email: str
    password: str
    created_at: datetime
    updated_at: datetime