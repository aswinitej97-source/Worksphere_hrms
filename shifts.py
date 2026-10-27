from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import Employee, EmployeeShift, Shift
from schemas import (
    EmployeeShiftCreate,
    EmployeeShiftResponse,
    ShiftCreate,
    ShiftResponse,
)


router = APIRouter(
    prefix="/shifts",
    tags=["Shifts"],
)


@router.post(
    "/",
    response_model=ShiftResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_shift(
    data: ShiftCreate,
    db: Session = Depends(get_db),
):
    existing_shift = (
        db.query(Shift)
        .filter(Shift.name == data.name)
        .first()
    )

    if existing_shift:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shift already exists",
        )

    shift = Shift(
        name=data.name,
        start_time=data.start_time,
        end_time=data.end_time,
    )

    db.add(shift)
    db.commit()
    db.refresh(shift)

    return shift


@router.get(
    "/",
    response_model=list[ShiftResponse],
)
def get_shifts(
    db: Session = Depends(get_db),
):
    return db.query(Shift).all()


@router.post(
    "/assign",
    response_model=EmployeeShiftResponse,
    status_code=status.HTTP_201_CREATED,
)
def assign_shift(
    data: EmployeeShiftCreate,
    db: Session = Depends(get_db),
):
    employee = (
        db.query(Employee)
        .filter(Employee.id == data.employee_id)
        .first()
    )

    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    shift = (
        db.query(Shift)
        .filter(Shift.id == data.shift_id)
        .first()
    )

    if not shift:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shift not found",
        )

    employee_shift = EmployeeShift(
        employee_id=data.employee_id,
        shift_id=data.shift_id,
    )

    db.add(employee_shift)
    db.commit()
    db.refresh(employee_shift)

    return employee_shift