
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from database import get_db
from models import User, Role, Employee
from resignation import Resignation
from auth import get_current_user, require_roles

router = APIRouter(
    prefix="/resignations",
    tags=["Resignations"]
)


class ResignationCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    notice_period: int = Field(ge=0)


@router.post("/")
def submit_resignation(
    data: ResignationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employee = db.query(Employee).filter(
        Employee.user_id == current_user.id
    ).first()

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee profile not found"
        )

    resignation = Resignation(
        employee_id=employee.id,
        reason=data.reason,
        notice_period=data.notice_period,
        status="PENDING"
    )

    db.add(resignation)
    db.commit()
    db.refresh(resignation)

    return resignation


@router.get("/")
def list_resignations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role in (Role.HR, Role.ADMIN):
        return db.query(Resignation).all()

    employee = db.query(Employee).filter(
        Employee.user_id == current_user.id
    ).first()

    if employee is None:
        return []

    return db.query(Resignation).filter(
        Resignation.employee_id == employee.id
    ).all()


@router.put("/{resignation_id}/status")
def update_resignation_status(
    resignation_id: int,
    new_status: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(Role.HR, Role.ADMIN)
    ),
):
    new_status = new_status.upper()

    if new_status not in ("APPROVED", "REJECTED"):
        raise HTTPException(
            status_code=400,
            detail="Status must be APPROVED or REJECTED"
        )

    resignation = db.get(Resignation, resignation_id)

    if resignation is None:
        raise HTTPException(
            status_code=404,
            detail="Resignation not found"
        )

    resignation.status = new_status
    db.commit()
    db.refresh(resignation)

    return resignation
