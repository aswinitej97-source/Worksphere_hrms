from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from attendance import IST, active_employee
from auth import get_current_user, require_roles
from database import get_db
from models import (
    Employee,
    Leave,
    LeaveStatus,
    Notification,
    Role,
    User,
)
from schemas import LeaveCreate, LeaveDecision, LeaveResponse

router = APIRouter(prefix="/leaves", tags=["Leaves"])


@router.post(
    "",
    response_model=LeaveResponse,
    status_code=201,
)
def apply_leave(
    data: LeaveCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    employee = active_employee(db, user)

    if data.start_date < datetime.now(IST).date():
        raise HTTPException(
            status_code=400,
            detail="Leave cannot start in the past",
        )

    if data.start_date < employee.joining_date:
        raise HTTPException(
            status_code=400,
            detail="Leave cannot start before joining date",
        )

    overlapping = db.scalar(
        select(Leave).where(
            Leave.employee_id == employee.id,
            Leave.status.in_(
                [LeaveStatus.PENDING, LeaveStatus.APPROVED]
            ),
            Leave.start_date <= data.end_date,
            Leave.end_date >= data.start_date,
        )
    )
    if overlapping:
        raise HTTPException(
            status_code=409,
            detail="An overlapping leave request already exists",
        )

    leave = Leave(
        employee_id=employee.id,
        **data.model_dump(),
        status=LeaveStatus.PENDING,
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


@router.get("", response_model=list[LeaveResponse])
def leave_history(
    employee_id: int | None = Query(default=None, gt=0),
    status: LeaveStatus | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Leave)

    if user.role == Role.EMPLOYEE:
        employee = db.scalar(
            select(Employee).where(Employee.user_id == user.id)
        )
        if employee is None:
            return []

        if employee_id is not None and employee_id != employee.id:
            raise HTTPException(
                status_code=403,
                detail="You can only view your own leaves",
            )

        query = query.where(Leave.employee_id == employee.id)

    elif employee_id is not None:
        query = query.where(Leave.employee_id == employee_id)

    if status is not None:
        query = query.where(Leave.status == status)

    return db.scalars(
        query.order_by(Leave.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()


@router.patch(
    "/{leave_id}/status",
    response_model=LeaveResponse,
)
def decide_leave(
    leave_id: int,
    data: LeaveDecision,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    leave = db.get(Leave, leave_id)
    if leave is None:
        raise HTTPException(
            status_code=404,
            detail="Leave request not found",
        )

    employee = db.get(Employee, leave.employee_id)
    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    if employee.user_id == manager.id:
        raise HTTPException(
            status_code=403,
            detail="Another HR/Admin must review your leave",
        )

    result = db.execute(
        update(Leave)
        .where(
            Leave.id == leave_id,
            Leave.status == LeaveStatus.PENDING,
        )
        .values(status=data.status)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This leave request has already been reviewed",
        )

    db.add(
        Notification(
            user_id=employee.user_id,
            title=f"Leave {data.status.value.lower()}",
            message=(
                f"Your leave from {leave.start_date} "
                f"to {leave.end_date} has been "
                f"{data.status.value.lower()}."
            ),
        )
    )
    db.commit()
    db.refresh(leave)
    return leave