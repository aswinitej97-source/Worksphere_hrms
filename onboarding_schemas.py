
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict

class OnboardingCreate(BaseModel):
    employee_id: int
    task_name: str
    due_date: Optional[date] = None

class OnboardingUpdate(BaseModel):
    status: Literal["PENDING", "COMPLETED"]

class OnboardingResponse(OnboardingCreate):
    id: int
    status: Literal["PENDING", "COMPLETED"]

    model_config = ConfigDict(from_attributes=True)
