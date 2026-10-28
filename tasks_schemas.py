
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    assigned_to: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    due_date: Optional[date] = None


class TaskUpdate(BaseModel):
    status: Literal["PENDING", "COMPLETED"]


class TaskResponse(TaskCreate):
    id: int
    status: Literal["PENDING", "COMPLETED"]

    model_config = ConfigDict(from_attributes=True)
