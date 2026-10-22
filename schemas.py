from datetime import date, datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    model_validator,
)

from models import (
    AttendanceStatus,
    EmployeeStatus,
    LeaveStatus,
    LeaveType,
    Role,
)


# Common models

class ORMResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StrictInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class NonNullUpdate(StrictInput):
    @model_validator(mode="after")
    def validate_update(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")

        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")

        return self


# Authentication

class UserRegister(BaseModel):
    # Password whitespace is preserved.
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_]+$",
    )
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(ORMResponse):
    id: int
    username: str
    email: EmailStr
    role: Role
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Admin user management
# Only admin-protected endpoints should accept these schemas.

class AdminUserCreate(UserRegister):
    role: Role = Role.EMPLOYEE
    is_active: bool = True


class AdminUserUpdate(BaseModel):
    # Do not strip whitespace from passwords.
    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_]+$",
    )
    email: EmailStr | None = None
    password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
    )
    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")

        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")

        return self


class RoleUpdate(StrictInput):
    role: Role


class UserStatusUpdate(StrictInput):
    is_active: bool


class MessageResponse(BaseModel):
    message: str


# Employees

class EmployeeCreate(StrictInput):
    user_id: int = Field(gt=0)
    full_name: str = Field(min_length=1, max_length=150)
    designation: str = Field(min_length=1, max_length=100)
    department: str = Field(min_length=1, max_length=100)
    joining_date: date

    salary: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2,
        allow_inf_nan=False,
    )

    status: EmployeeStatus = EmployeeStatus.ACTIVE


class EmployeeUpdate(NonNullUpdate):
    full_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
    )
    designation: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    department: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    joining_date: date | None = None

    salary: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
        allow_inf_nan=False,
    )

    status: EmployeeStatus | None = None


class EmployeeResponse(ORMResponse):
    id: int
    user_id: int
    full_name: str
    designation: str
    department: str
    joining_date: date
    salary: Decimal
    status: EmployeeStatus


# Attendance

class AttendanceResponse(ORMResponse):
    id: int
    employee_id: int
    check_in: datetime | None
    check_out: datetime | None
    date: date
    status: AttendanceStatus
    working_hours: float

    # These fields require the updated Attendance model.
    is_late: bool
    late_minutes: int
    overtime_hours: float


class AttendanceMark(StrictInput):
    employee_id: int = Field(gt=0)
    date: date
    status: AttendanceStatus = AttendanceStatus.ABSENT

    @model_validator(mode="after")
    def validate_manual_status(self):
        if self.status != AttendanceStatus.ABSENT:
            raise ValueError(
                "Manual marking supports ABSENT only; "
                "use check-in/check-out for working attendance"
            )
        return self


# Leave requests

class LeaveCreate(StrictInput):
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError(
                "end_date must be on or after start_date"
            )
        return self


class LeaveDecision(StrictInput):
    status: LeaveStatus

    @model_validator(mode="after")
    def validate_decision(self):
        if self.status not in (
            LeaveStatus.APPROVED,
            LeaveStatus.REJECTED,
        ):
            raise ValueError("Choose APPROVED or REJECTED")
        return self


class LeaveResponse(ORMResponse):
    id: int
    employee_id: int
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str
    status: LeaveStatus


# Leave policies
# Full-day leave is used in this version.

class LeavePolicyCreate(StrictInput):
    leave_type: LeaveType
    total_days_allowed: int = Field(
        ge=0,
        le=366,
        strict=True,
    )


class LeavePolicyUpdate(StrictInput):
    total_days_allowed: int = Field(
        ge=0,
        le=366,
        strict=True,
    )


class LeavePolicyResponse(ORMResponse):
    id: int
    leave_type: LeaveType
    total_days_allowed: int


# Leave balances
# Approval logic must deduct balances atomically in the backend.

class LeaveBalanceResponse(ORMResponse):
    id: int
    employee_id: int
    leave_type: LeaveType
    remaining_days: int


# Payroll

class PayrollCreate(StrictInput):
    employee_id: int = Field(gt=0)

    month: str = Field(
        pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"
    )

    allowances: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=12,
        decimal_places=2,
        allow_inf_nan=False,
    )

    deductions: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=12,
        decimal_places=2,
        allow_inf_nan=False,
    )

    bonus: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=12,
        decimal_places=2,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def validate_month(self):
        year, month = map(int, self.month.split("-"))
        date(year, month, 1)
        return self


class PayrollResponse(ORMResponse):
    id: int
    employee_id: int
    basic_salary: Decimal
    allowances: Decimal
    deductions: Decimal
    bonus: Decimal
    net_salary: Decimal
    month: str
    created_at: datetime


class PayrollMonthlySummary(BaseModel):
    month: str
    employee_count: int
    total_basic_salary: Decimal
    total_allowances: Decimal
    total_bonus: Decimal
    total_deductions: Decimal
    total_net_salary: Decimal


# Notifications

class NotificationResponse(ORMResponse):
    id: int
    user_id: int
    title: str
    message: str
    is_read: bool
    created_at: datetime