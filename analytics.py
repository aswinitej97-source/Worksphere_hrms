from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from attendance import IST
from auth import require_roles
from database import get_db
from models import (
    Attendance,
    AttendanceStatus,
    Employee,
    EmployeeStatus,
    Leave,
    LeaveStatus,
    Payroll,
    Role,
    User,
)

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


@router.get("/summary")
def dashboard_summary(
    month: str | None = Query(
        default=None,
        pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$",
    ),
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    today = datetime.now(IST).date()
    selected_month = month or today.strftime("%Y-%m")

    total_employees = db.scalar(
        select(func.count(Employee.id))
    ) or 0

    active_employees = db.scalar(
        select(func.count(Employee.id)).where(
            Employee.status == EmployeeStatus.ACTIVE
        )
    ) or 0

    attendance_rows = db.execute(
        select(Attendance.status, func.count(Attendance.id))
        .join(Employee, Employee.id == Attendance.employee_id)
        .where(
            Attendance.date == today,
            Employee.status == EmployeeStatus.ACTIVE,
        )
        .group_by(Attendance.status)
    ).all()

    attendance = {
        status.value: 0 for status in AttendanceStatus
    }
    for status, count in attendance_rows:
        attendance[status.value] = count

    recorded = sum(attendance.values())

    leave_rows = db.execute(
        select(Leave.status, func.count(Leave.id))
        .group_by(Leave.status)
    ).all()

    leave_statistics = {
        status.value: 0 for status in LeaveStatus
    }
    for status, count in leave_rows:
        leave_statistics[status.value] = count

    payroll_totals = db.execute(
        select(
            func.count(Payroll.id),
            func.sum(Payroll.basic_salary),
            func.sum(Payroll.deductions),
            func.sum(Payroll.bonus),
            func.sum(Payroll.net_salary),
        ).where(Payroll.month == selected_month)
    ).one()

    def money(value):
        return str(
            (value or Decimal("0.00")).quantize(
                Decimal("0.01")
            )
        )

    departments = db.execute(
        select(Employee.department, func.count(Employee.id))
        .group_by(Employee.department)
        .order_by(Employee.department)
    ).all()

    start_date = today - timedelta(days=6)
    trend_rows = db.execute(
        select(
            Attendance.date,
            Attendance.status,
            func.count(Attendance.id),
        )
        .where(
            Attendance.date >= start_date,
            Attendance.date <= today,
        )
        .group_by(Attendance.date, Attendance.status)
    ).all()

    trend = {}
    for index in range(7):
        day = start_date + timedelta(days=index)
        trend[day] = {
            "date": day.isoformat(),
            "PRESENT": 0,
            "HALF_DAY": 0,
            "ABSENT": 0,
        }

    for day, status, count in trend_rows:
        trend[day][status.value] = count

    return {
        "total_employees": total_employees,
        "active_employees": active_employees,
        "inactive_employees": total_employees - active_employees,
        "attendance_today": {
            "date": today.isoformat(),
            **attendance,
            "not_marked": max(active_employees - recorded, 0),
        },
        "leave_statistics": leave_statistics,
        "payroll_overview": {
            "month": selected_month,
            "generated_count": payroll_totals[0],
            "basic_salary": money(payroll_totals[1]),
            "deductions": money(payroll_totals[2]),
            "bonus": money(payroll_totals[3]),
            "net_salary": money(payroll_totals[4]),
        },
        "employees_by_department": [
            {"department": department, "count": count}
            for department, count in departments
        ],
        "attendance_trend": list(trend.values()),
    }