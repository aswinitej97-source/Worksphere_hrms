import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


# Helpers

def utc_now():
    return datetime.now(timezone.utc)


def enum_column(enum_type):
    return Enum(
        enum_type,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
    )


def as_utc(value: datetime) -> datetime:
    # SQLite may return stored UTC timestamps without timezone info.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


# Enums

class Role(str, enum.Enum):
    EMPLOYEE = "EMPLOYEE"
    HR = "HR"
    ADMIN = "ADMIN"


class EmployeeStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AttendanceStatus(str, enum.Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    HALF_DAY = "HALF_DAY"


class LeaveType(str, enum.Enum):
    SICK = "SICK"
    CASUAL = "CASUAL"
    PAID = "PAID"


class LeaveStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# Users

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    role: Mapped[Role] = mapped_column(
        enum_column(Role),
        default=Role.EMPLOYEE,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="1",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


# Employees

class Employee(Base):
    __tablename__ = "employees"

    __table_args__ = (
        CheckConstraint(
            "salary >= 0",
            name="ck_employee_salary_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True,
        nullable=False,
    )

    full_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    designation: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    department: Mapped[str] = mapped_column(
        String(100),
        index=True,
        nullable=False,
    )

    joining_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    salary: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    status: Mapped[EmployeeStatus] = mapped_column(
        enum_column(EmployeeStatus),
        default=EmployeeStatus.ACTIVE,
        nullable=False,
    )


# Attendance

class Attendance(Base):
    __tablename__ = "attendance"

    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "date",
            name="uq_attendance_employee_date",
        ),
        CheckConstraint(
            "late_minutes >= 0",
            name="ck_attendance_late_minutes_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"),
        index=True,
        nullable=False,
    )

    check_in: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    check_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    status: Mapped[AttendanceStatus] = mapped_column(
        enum_column(AttendanceStatus),
        nullable=False,
    )

    is_late: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )

    late_minutes: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    @property
    def working_hours(self) -> float:
        if self.check_in is None or self.check_out is None:
            return 0.0

        started = as_utc(self.check_in)
        finished = as_utc(self.check_out)

        seconds = max(
            (finished - started).total_seconds(),
            0,
        )

        return round(seconds / 3600, 2)

    @property
    def overtime_hours(self) -> float:
        # Overtime is time worked beyond eight hours.
        if self.check_in is None or self.check_out is None:
            return 0.0

        started = as_utc(self.check_in)
        finished = as_utc(self.check_out)

        seconds = max(
            (finished - started).total_seconds() - 8 * 3600,
            0,
        )

        return round(seconds / 3600, 2)


# Leave requests

class Leave(Base):
    __tablename__ = "leaves"

    __table_args__ = (
        CheckConstraint(
            "end_date >= start_date",
            name="ck_leave_date_order",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"),
        index=True,
        nullable=False,
    )

    leave_type: Mapped[LeaveType] = mapped_column(
        enum_column(LeaveType),
        nullable=False,
    )

    start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[LeaveStatus] = mapped_column(
        enum_column(LeaveStatus),
        default=LeaveStatus.PENDING,
        nullable=False,
    )


# Leave policies

class LeavePolicy(Base):
    __tablename__ = "leave_policies"

    __table_args__ = (
        CheckConstraint(
            "total_days_allowed >= 0 AND total_days_allowed <= 366",
            name="ck_leave_policy_days_range",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    leave_type: Mapped[LeaveType] = mapped_column(
        enum_column(LeaveType),
        unique=True,
        nullable=False,
    )

    total_days_allowed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )


# Leave balances
# One balance per employee and leave type.
# No automatic annual reset is defined in this model.

class LeaveBalance(Base):
    __tablename__ = "leave_balances"

    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "leave_type",
            name="uq_leave_balance_employee_type",
        ),
        CheckConstraint(
            "remaining_days >= 0",
            name="ck_leave_balance_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"),
        index=True,
        nullable=False,
    )

    leave_type: Mapped[LeaveType] = mapped_column(
        enum_column(LeaveType),
        nullable=False,
    )

    remaining_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )


# Payroll

class Payroll(Base):
    __tablename__ = "payroll"

    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "month",
            name="uq_payroll_employee_month",
        ),
        CheckConstraint(
            "basic_salary >= 0 "
            "AND allowances >= 0 "
            "AND deductions >= 0 "
            "AND bonus >= 0 "
            "AND net_salary >= 0",
            name="ck_payroll_amounts_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id"),
        index=True,
        nullable=False,
    )

    basic_salary: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    allowances: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        server_default="0",
        nullable=False,
    )

    deductions: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    bonus: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    net_salary: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    month: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


# Notifications

class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )