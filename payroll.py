from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user, require_roles
from database import get_db
from models import (
    Employee,
    EmployeeStatus,
    Notification,
    Payroll,
    Role,
    User,
)
from schemas import PayrollCreate, PayrollResponse

router = APIRouter(prefix="/payroll", tags=["Payroll"])


@router.post(
    "",
    response_model=PayrollResponse,
    status_code=201,
)
def generate_payroll(
    data: PayrollCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    employee = db.get(Employee, data.employee_id)
    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    if employee.status != EmployeeStatus.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail="Employee profile is inactive",
        )

    year, month = map(int, data.month.split("-"))
    if year < 1:
        raise HTTPException(
            status_code=400,
            detail="Invalid payroll year",
        )

    if (year, month) < (
        employee.joining_date.year,
        employee.joining_date.month,
    ):
        raise HTTPException(
            status_code=400,
            detail="Payroll month cannot be before joining month",
        )

    existing = db.scalar(
        select(Payroll).where(
            Payroll.employee_id == employee.id,
            Payroll.month == data.month,
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Payroll already generated for this month",
        )

    net_salary = (
        employee.salary + data.bonus - data.deductions
    ).quantize(Decimal("0.01"))

    if net_salary < 0:
        raise HTTPException(
            status_code=400,
            detail="Deductions exceed salary plus bonus",
        )

    if net_salary > Decimal("9999999999.99"):
        raise HTTPException(
            status_code=400,
            detail="Net salary exceeds the supported amount",
        )

    payroll = Payroll(
        employee_id=employee.id,
        basic_salary=employee.salary,
        deductions=data.deductions,
        bonus=data.bonus,
        net_salary=net_salary,
        month=data.month,
    )
    db.add(payroll)
    db.add(
        Notification(
            user_id=employee.user_id,
            title="Payroll generated",
            message=(
                f"Your payroll for {data.month} is available. "
                f"Net salary: INR {net_salary:.2f}."
            ),
        )
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Payroll already generated for this month",
        )

    db.refresh(payroll)
    return payroll


@router.get("", response_model=list[PayrollResponse])
def payroll_history(
    employee_id: int | None = Query(default=None, gt=0),
    month: str | None = Query(
        default=None,
        pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Payroll)

    if user.role == Role.EMPLOYEE:
        employee = db.scalar(
            select(Employee).where(Employee.user_id == user.id)
        )
        if employee is None:
            return []

        if employee_id is not None and employee_id != employee.id:
            raise HTTPException(
                status_code=403,
                detail="You can only view your own payroll",
            )

        query = query.where(
            Payroll.employee_id == employee.id
        )

    elif employee_id is not None:
        query = query.where(
            Payroll.employee_id == employee_id
        )

    if month is not None:
        query = query.where(Payroll.month == month)

    return db.scalars(
        query.order_by(Payroll.month.desc(), Payroll.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()


@router.get("/{payroll_id}", response_model=PayrollResponse)
def payroll_details(
    payroll_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payroll = db.get(Payroll, payroll_id)
    if payroll is None:
        raise HTTPException(
            status_code=404,
            detail="Payroll not found",
        )

    employee = db.get(Employee, payroll.employee_id)
    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    if (
        user.role == Role.EMPLOYEE
        and employee.user_id != user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="You can only view your own payroll",
        )

    return payrolls