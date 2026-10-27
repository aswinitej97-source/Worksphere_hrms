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
    Performance,
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
    manager: User = Depends(
        require_roles(Role.HR, Role.ADMIN)
    ),
):
    today = datetime.now(IST).date()
    selected_month = month or today.strftime("%Y-%m")

    # Employee statistics
    total_employees = db.scalar(
        select(func.count(Employee.id))
    ) or 0

    active_employees = db.scalar(
        select(func.count(Employee.id)).where(
            Employee.status == EmployeeStatus.ACTIVE
        )
    ) or 0

    # Today's attendance
    attendance_rows = db.execute(
        select(
            Attendance.status,
            func.count(Attendance.id),
        )
        .join(
            Employee,
            Employee.id == Attendance.employee_id,
        )
        .where(
            Attendance.date == today,
            Employee.status == EmployeeStatus.ACTIVE,
        )
        .group_by(Attendance.status)
    ).all()

    attendance = {
        status.value: 0
        for status in AttendanceStatus
    }

    for attendance_status, count in attendance_rows:
        attendance[attendance_status.value] = count

    recorded = sum(attendance.values())

    # Leave statistics
    leave_rows = db.execute(
        select(
            Leave.status,
            func.count(Leave.id),
        )
        .group_by(Leave.status)
    ).all()

    leave_statistics = {
        status.value: 0
        for status in LeaveStatus
    }

    for leave_status, count in leave_rows:
        leave_statistics[leave_status.value] = count

    # Payroll overview
    payroll_totals = db.execute(
        select(
            func.count(Payroll.id),
            func.sum(Payroll.basic_salary),
            func.sum(Payroll.deductions),
            func.sum(Payroll.bonus),
            func.sum(Payroll.net_salary),
        ).where(
            Payroll.month == selected_month
        )
    ).one()

    def money(value):
        return str(
            (value or Decimal("0.00")).quantize(
                Decimal("0.01")
            )
        )

    # Department-wise employee report
    departments = db.execute(
        select(
            Employee.department,
            func.count(Employee.id),
        )
        .group_by(Employee.department)
        .order_by(Employee.department)
    ).all()

    # Last 7 days attendance trend
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
        .group_by(
            Attendance.date,
            Attendance.status,
        )
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

    for day, attendance_status, count in trend_rows:
        trend[day][attendance_status.value] = count

    # Performance insights
    performance_stats = db.execute(
        select(
            func.count(Performance.id),
            func.avg(Performance.rating),
        )
    ).one()

    # Department-wise performance
    performance_by_department = db.execute(
        select(
            Employee.department,
            func.avg(Performance.rating),
            func.count(Performance.id),
        )
        .join(
            Employee,
            Employee.id == Performance.employee_id,
        )
        .group_by(Employee.department)
        .order_by(Employee.department)
    ).all()

    return {
        "total_employees": total_employees,

        "active_employees": active_employees,

        "inactive_employees": (
            total_employees - active_employees
        ),

        "attendance_today": {
            "date": today.isoformat(),
            **attendance,
            "not_marked": max(
                active_employees - recorded,
                0,
            ),
        },

        "leave_statistics": leave_statistics,

        "payroll_overview": {
            "month": selected_month,
            "generated_count": payroll_totals[0],
            "basic_salary": money(
                payroll_totals[1]
            ),
            "deductions": money(
                payroll_totals[2]
            ),
            "bonus": money(
                payroll_totals[3]
            ),
            "net_salary": money(
                payroll_totals[4]
            ),
        },

        "employees_by_department": [
            {
                "department": department,
                "count": count,
            }
            for department, count in departments
        ],

        "attendance_trend": list(
            trend.values()
        ),

        "performance_insights": {
            "total_reviews": performance_stats[0],

            "average_rating": round(
                float(
                    performance_stats[1] or 0
                ),
                2,
            ),

            "by_department": [
                {
                    "department": department,
                    "average_rating": round(
                        float(avg_rating or 0),
                        2,
                    ),
                    "review_count": review_count,
                }
                for (
                    department,
                    avg_rating,
                    review_count,
                ) in performance_by_department
            ],
        },
    }