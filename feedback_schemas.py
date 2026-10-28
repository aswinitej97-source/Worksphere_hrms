
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class FeedbackCreate(BaseModel):
    employee_id: int = Field(gt=0)
    message: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)


class FeedbackResponse(FeedbackCreate):
    id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
