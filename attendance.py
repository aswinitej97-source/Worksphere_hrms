from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user, require_roles
from database import get_db
from models import (
    Attendance,
    AttendanceStatus,
    Employee,
    EmployeeStatus,
    Notification,
    Role,
    User,
)
from schemas import AttendanceMark, AttendanceResponse

router = APIRouter(
    prefix="/attendance",
    tags=["Attendance"],
)

IST = timezone(timedelta(hours=5, minutes=30))


def active_employee(db, user):
    employee = db.scalar(
        select(Employee).where(Employee.user_id == user.id)
    )
    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee profile not created. Contact HR.",
        )
    if employee.status != EmployeeStatus.ACTIVE:
        raise HTTPException(
            status_code=403,
            detail="Employee profile is inactive",
        )
    return employee


@router.post(
    "/check-in",
    response_model=AttendanceResponse,
    status_code=201,
)
def check_in(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    employee = active_employee(db, user)
    now = datetime.now(IST)

    record = Attendance(
        employee_id=employee.id,
        date=now.date(),
        check_in=now.astimezone(timezone.utc),
        status=AttendanceStatus.PRESENT,
    )
    db.add(record)
    db.add(
        Notification(
            user_id=user.id,
            title="Attendance check-in",
            message=f"Checked in for {now.date()}.",
        )
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Attendance already recorded for today",
        )

    db.refresh(record)
    return record


@router.post("/check-out", response_model=AttendanceResponse)
def check_out(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    employee = active_employee(db, user)
    now = datetime.now(timezone.utc)
    today = now.astimezone(IST).date()

    record = db.scalar(
        select(Attendance).where(
            Attendance.employee_id == employee.id,
            Attendance.date == today,
        )
    )
    if record is None or record.check_in is None:
        raise HTTPException(
            status_code=400,
            detail="Check in first",
        )
    if record.check_out is not None:
        raise HTTPException(
            status_code=409,
            detail="Already checked out",
        )

    started = record.check_in
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)

    hours = max((now - started).total_seconds(), 0) / 3600
    attendance_status = (
        AttendanceStatus.PRESENT
        if hours >= 8
        else AttendanceStatus.HALF_DAY
    )

    result = db.execute(
        update(Attendance)
        .where(
            Attendance.id == record.id,
            Attendance.check_out.is_(None),
        )
        .values(
            check_out=now,
            status=attendance_status,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Already checked out",
        )

    db.add(
        Notification(
            user_id=user.id,
            title="Attendance check-out",
            message=f"Working hours: {hours:.2f}.",
        )
    )
    db.commit()
    db.refresh(record)
    return record


@router.get("", response_model=list[AttendanceResponse])
def attendance_history(
    employee_id: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Attendance)

    if user.role == Role.EMPLOYEE:
        employee = db.scalar(
            select(Employee).where(Employee.user_id == user.id)
        )
        if employee is None:
            return []
        if employee_id is not None and employee_id != employee.id:
            raise HTTPException(
                status_code=403,
                detail="You can only view your own attendance",
            )
        query = query.where(
            Attendance.employee_id == employee.id
        )
    elif employee_id is not None:
        query = query.where(
            Attendance.employee_id == employee_id
        )

    return db.scalars(
        query.order_by(
            Attendance.date.desc(), Attendance.id.desc()
        ).offset(offset).limit(limit)
    ).all()


@router.post(
    "/mark",
    response_model=AttendanceResponse,
    status_code=201,
)
def mark_absent(
    data: AttendanceMark,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    employee = db.get(Employee, data.employee_id)
    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    # Mark absences only after the attendance day has ended.
    if data.date >= datetime.now(IST).date():
        raise HTTPException(
            status_code=400,
            detail="Absence can only be marked for past dates",
        )
    if data.date < employee.joining_date:
        raise HTTPException(
            status_code=400,
            detail="Date cannot be before joining date",
        )

    record = Attendance(**data.model_dump())
    db.add(record)
    db.add(
        Notification(
            user_id=employee.user_id,
            title="Attendance alert",
            message=f"Marked absent for {data.date}. Contact HR for corrections.",
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Attendance already recorded for this date",
        )

    db.refresh(record)
    return record