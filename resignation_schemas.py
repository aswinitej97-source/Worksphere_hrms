
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class ResignationCreate(BaseModel):
    employee_id: int
    reason: str
    notice_period: int = Field(gt=0)


class ResignationUpdate(BaseModel):
    status: Literal["PENDING", "APPROVED", "REJECTED"]


class ResignationResponse(ResignationCreate):
    id: int
    status: str
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
