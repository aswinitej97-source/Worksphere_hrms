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


class ORMResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserRegister(BaseModel):
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
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RoleUpdate(BaseModel):
    role: Role


class EmployeeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: int = Field(gt=0)
    full_name: str = Field(min_length=1, max_length=150)
    designation: str = Field(min_length=1, max_length=100)
    department: str = Field(min_length=1, max_length=100)
    joining_date: date
    salary: Decimal = Field(
        ge=0, max_digits=12, decimal_places=2
    )
    status: EmployeeStatus = EmployeeStatus.ACTIVE


class EmployeeUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str | None = Field(
        default=None, min_length=1, max_length=150
    )
    designation: str | None = Field(
        default=None, min_length=1, max_length=100
    )
    department: str | None = Field(
        default=None, min_length=1, max_length=100
    )
    joining_date: date | None = None
    salary: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    status: EmployeeStatus | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self):
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class EmployeeResponse(ORMResponse):
    id: int
    user_id: int
    full_name: str
    designation: str
    department: str
    joining_date: date
    salary: Decimal
    status: EmployeeStatus


class AttendanceResponse(ORMResponse):
    id: int
    employee_id: int
    check_in: datetime | None
    check_out: datetime | None
    date: date
    status: AttendanceStatus
    working_hours: float


class AttendanceMark(BaseModel):
    employee_id: int = Field(gt=0)
    date: date
    status: AttendanceStatus

    @model_validator(mode="after")
    def validate_manual_status(self):
        if self.status != AttendanceStatus.ABSENT:
            raise ValueError(
                "Manual marking supports ABSENT only; "
                "use check-in/check-out for working attendance"
            )
        return self


class LeaveCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

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


class LeaveDecision(BaseModel):
    status: LeaveStatus

    @model_validator(mode="after")
    def validate_decision(self):
        if self.status == LeaveStatus.PENDING:
            raise ValueError(
                "Choose APPROVED or REJECTED"
            )
        return self


class LeaveResponse(ORMResponse):
    id: int
    employee_id: int
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str
    status: LeaveStatus


class PayrollCreate(BaseModel):
    employee_id: int = Field(gt=0)
    month: str = Field(
        pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"
    )
    deductions: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=12,
        decimal_places=2,
    )
    bonus: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=12,
        decimal_places=2,
    )


class PayrollResponse(ORMResponse):
    id: int
    employee_id: int
    basic_salary: Decimal
    deductions: Decimal
    bonus: Decimal
    net_salary: Decimal
    month: str
    created_at: datetime


class NotificationResponse(ORMResponse):
    id: int
    user_id: int
    title: str
    message: str
    is_read: bool
    created_at: datetime