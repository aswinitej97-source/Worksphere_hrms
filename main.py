import asyncio
import calendar
import logging
import math
import os
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from database import Base, SessionLocal, engine, get_db
from models import (
    Attendance,
    AttendanceStatus,
    Employee,
    EmployeeStatus,
    Leave,
    LeaveBalance,
    LeavePolicy,
    LeaveStatus,
    Notification,
    Payroll,
    Role,
    User,
)
from schemas import (
    AdminUserCreate,
    AdminUserUpdate,
    AttendanceMark,
    AttendanceResponse,
    EmployeeCreate,
    EmployeeResponse,
    EmployeeUpdate,
    LeaveBalanceResponse,
    LeaveCreate,
    LeaveDecision,
    LeavePolicyCreate,
    LeavePolicyResponse,
    LeavePolicyUpdate,
    LeaveResponse,
    MessageResponse,
    NotificationResponse,
    PayrollCreate,
    PayrollMonthlySummary,
    PayrollResponse,
    RoleUpdate,
    TokenResponse,
    UserRegister,
    UserResponse,
    UserStatusUpdate,
)


logger = logging.getLogger("worksphere")

INDIA = timezone(timedelta(hours=5, minutes=30))
ZERO = Decimal("0.00")
MAX_MONEY = Decimal("9999999999.99")

WORK_START = time.fromisoformat(
    os.getenv("WORK_START_TIME", "09:30")
)
LATE_GRACE_MINUTES = int(
    os.getenv("LATE_GRACE_MINUTES", "10")
)
WORKING_DAYS = {
    int(value.strip())
    for value in os.getenv(
        "WORKING_DAYS", "0,1,2,3,4"
    ).split(",")
}

if LATE_GRACE_MINUTES < 0:
    raise RuntimeError("LATE_GRACE_MINUTES cannot be negative")

if not WORKING_DAYS or not WORKING_DAYS.issubset(set(range(7))):
    raise RuntimeError("WORKING_DAYS must contain values from 0 to 6")

if WORK_START.tzinfo is not None:
    raise RuntimeError("WORK_START_TIME must be a local time like 09:30")


# Helpers

def today_india():
    return datetime.now(INDIA).date()


def is_manager(user):
    return user.role in (Role.HR, Role.ADMIN)


def save_changes(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "Record conflicts with existing data",
        ) from None


def lock_write(db):
    # This project uses SQLite.
    # Serialize multi-step changes such as leave approval.
    db.execute(text("BEGIN IMMEDIATE"))


def notify(db, user_id, title, message):
    db.add(
        Notification(
            user_id=user_id,
            title=title,
            message=message,
        )
    )


def own_employee(db, user):
    employee = db.scalar(
        select(Employee).where(Employee.user_id == user.id)
    )

    if employee is None:
        raise HTTPException(404, "Employee profile not found")

    return employee


def active_employee(db, user):
    employee = own_employee(db, user)

    if employee.status != EmployeeStatus.ACTIVE:
        raise HTTPException(403, "Employee is inactive")

    if employee.joining_date > today_india():
        raise HTTPException(403, "Your joining date is in the future")

    return employee


def get_employee_or_404(db, employee_id):
    employee = db.get(Employee, employee_id)

    if employee is None:
        raise HTTPException(404, "Employee not found")

    return employee


def leave_days(start_date, end_date):
    return (end_date - start_date).days + 1


def approved_days(db, employee_id, leave_type):
    records = db.scalars(
        select(Leave).where(
            Leave.employee_id == employee_id,
            Leave.leave_type == leave_type,
            Leave.status == LeaveStatus.APPROVED,
        )
    ).all()

    return sum(
        leave_days(item.start_date, item.end_date)
        for item in records
    )


def ensure_balance(db, employee_id, policy):
    balance = db.scalar(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.leave_type == policy.leave_type,
        )
    )

    if balance is None:
        used = approved_days(
            db,
            employee_id,
            policy.leave_type,
        )

        balance = LeaveBalance(
            employee_id=employee_id,
            leave_type=policy.leave_type,
            remaining_days=max(
                policy.total_days_allowed - used,
                0,
            ),
        )
        db.add(balance)
        db.flush()

    return balance


def approved_leave_on(db, employee_id, day):
    return db.scalar(
        select(Leave.id).where(
            Leave.employee_id == employee_id,
            Leave.status == LeaveStatus.APPROVED,
            Leave.start_date <= day,
            Leave.end_date >= day,
        ).limit(1)
    ) is not None


def parse_month(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m")
        if parsed.strftime("%Y-%m") != value:
            raise ValueError
        return parsed
    except ValueError:
        raise HTTPException(
            422,
            "Month must use YYYY-MM format",
        ) from None


def payroll_summary(db, month, employee_id=None):
    parse_month(month)

    query = select(Payroll).where(Payroll.month == month)

    if employee_id is not None:
        query = query.where(
            Payroll.employee_id == employee_id
        )

    records = db.scalars(query).all()

    return {
        "month": month,
        "employee_count": len(records),
        "total_basic_salary": sum(
            (item.basic_salary for item in records), ZERO
        ),
        "total_allowances": sum(
            (item.allowances for item in records), ZERO
        ),
        "total_bonus": sum(
            (item.bonus for item in records), ZERO
        ),
        "total_deductions": sum(
            (item.deductions for item in records), ZERO
        ),
        "total_net_salary": sum(
            (item.net_salary for item in records), ZERO
        ),
    }


# Automatic absence
# Processes yesterday only. It does not invent historical records.
# The backend must be running for the scheduled task to execute.
# HR/Admin can use /attendance/reconcile for missed dates.

def reconcile_absences(day):
    if day >= today_india():
        raise ValueError("Absence reconciliation requires a past date")

    if day.weekday() not in WORKING_DAYS:
        return 0

    with SessionLocal() as db:
        lock_write(db)

        employees = db.scalars(
            select(Employee)
            .join(User, User.id == Employee.user_id)
            .where(
                Employee.status == EmployeeStatus.ACTIVE,
                User.is_active.is_(True),
                Employee.joining_date <= day,
            )
        ).all()

        existing_ids = set(
            db.scalars(
                select(Attendance.employee_id).where(
                    Attendance.date == day
                )
            ).all()
        )

        on_leave_ids = set(
            db.scalars(
                select(Leave.employee_id).where(
                    Leave.status == LeaveStatus.APPROVED,
                    Leave.start_date <= day,
                    Leave.end_date >= day,
                )
            ).all()
        )

        count = 0

        for employee in employees:
            if employee.id in existing_ids:
                continue

            if employee.id in on_leave_ids:
                continue

            db.add(
                Attendance(
                    employee_id=employee.id,
                    date=day,
                    status=AttendanceStatus.ABSENT,
                    is_late=False,
                    late_minutes=0,
                )
            )
            count += 1

        db.commit()
        return count


async def absence_worker():
    while True:
        try:
            day = today_india() - timedelta(days=1)
            await asyncio.to_thread(reconcile_absences, day)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Automatic absence processing failed")

        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    task = asyncio.create_task(absence_worker())

    try:
        yield
    finally:
        task.cancel()

        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="WorkSphere HRMS API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Home

@app.get("/")
def home():
    return {"message": "WorkSphere API is running"}


# Authentication

@app.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=201,
    tags=["Authentication"],
)
def register(
    data: UserRegister,
    db: Session = Depends(get_db),
):
    email = str(data.email).lower()

    existing = db.scalar(
        select(User).where(
            or_(
                User.username == data.username,
                User.email == email,
            )
        )
    )

    if existing:
        raise HTTPException(
            409, "Username or email already exists"
        )

    user = User(
        username=data.username,
        email=email,
        hashed_password=hash_password(data.password),
        role=Role.EMPLOYEE,
        is_active=True,
    )

    db.add(user)
    save_changes(db)
    db.refresh(user)
    return user


@app.post(
    "/auth/login",
    response_model=TokenResponse,
    tags=["Authentication"],
)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(
            User.username == form.username
        )
    )

    if user is None or not verify_password(
        form.password, user.hashed_password
    ):
        raise HTTPException(
            401,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            403,
            "Your account is deactivated. Contact your admin.",
        )

    return TokenResponse(
        access_token=create_access_token(
            user.id, user.role
        )
    )


@app.get(
    "/auth/me",
    response_model=UserResponse,
    tags=["Authentication"],
)
def get_profile(
    user: User = Depends(get_current_user),
):
    return user


# Dashboards / Employee self-service

@app.get("/dashboard/employee", tags=["Dashboards"])
def employee_dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    employee = own_employee(db, user)

    attendance_today = db.scalar(
        select(Attendance).where(
            Attendance.employee_id == employee.id,
            Attendance.date == today_india(),
        )
    )

    balances = db.scalars(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee.id
        )
    ).all()

    pending = db.scalar(
        select(func.count(Leave.id)).where(
            Leave.employee_id == employee.id,
            Leave.status == LeaveStatus.PENDING,
        )
    )

    latest_payroll = db.scalar(
        select(Payroll)
        .where(Payroll.employee_id == employee.id)
        .order_by(Payroll.month.desc())
        .limit(1)
    )

    return {
        "message": f"Welcome, {user.username}",
        "role": user.role,
        "employee": EmployeeResponse.model_validate(employee),
        "attendance_today": (
            AttendanceResponse.model_validate(attendance_today)
            if attendance_today else None
        ),
        "pending_leaves": pending,
        "leave_balances": [
            LeaveBalanceResponse.model_validate(item)
            for item in balances
        ],
        "latest_payroll": (
            PayrollResponse.model_validate(latest_payroll)
            if latest_payroll else None
        ),
    }


@app.get("/dashboard/hr", tags=["Dashboards"])
def hr_dashboard(
    user: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    return {
        "message": "Welcome to the HR dashboard",
        "username": user.username,
    }


@app.get("/dashboard/admin", tags=["Dashboards"])
def admin_dashboard(
    user: User = Depends(require_roles(Role.ADMIN)),
):
    return {
        "message": "Welcome to the Admin dashboard",
        "username": user.username,
    }


# Admin user management

@app.get(
    "/admin/users",
    response_model=list[UserResponse],
    tags=["Admin"],
)
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.ADMIN)),
):
    return db.scalars(
        select(User).order_by(User.id)
    ).all()


@app.post(
    "/admin/users",
    response_model=UserResponse,
    status_code=201,
    tags=["Admin"],
)
def create_user(
    data: AdminUserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.ADMIN)),
):
    user = User(
        username=data.username,
        email=str(data.email).lower(),
        hashed_password=hash_password(data.password),
        role=data.role,
        is_active=data.is_active,
    )

    db.add(user)
    save_changes(db)
    db.refresh(user)
    return user


@app.patch(
    "/admin/users/{user_id}",
    response_model=UserResponse,
    tags=["Admin"],
)
def update_user(
    user_id: int,
    data: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.ADMIN)),
):
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(404, "User not found")

    changes = data.model_dump(exclude_unset=True)

    if user.id == admin.id:
        if (
            "role" in changes
            and changes["role"] != Role.ADMIN
        ):
            raise HTTPException(
                400, "You cannot remove your own admin role"
            )

        if changes.get("is_active") is False:
            raise HTTPException(
                400, "You cannot deactivate yourself"
            )

    for field, value in changes.items():
        if field == "password":
            user.hashed_password = hash_password(value)
        elif field == "email":
            user.email = str(value).lower()
        else:
            setattr(user, field, value)

    save_changes(db)
    db.refresh(user)
    return user


@app.patch(
    "/admin/users/{user_id}/role",
    response_model=UserResponse,
    tags=["Admin"],
)
def update_role(
    user_id: int,
    data: RoleUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.ADMIN)),
):
    return update_user(
        user_id,
        AdminUserUpdate(role=data.role),
        db,
        admin,
    )


@app.patch(
    "/admin/users/{user_id}/status",
    response_model=UserResponse,
    tags=["Admin"],
)
def update_user_status(
    user_id: int,
    data: UserStatusUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.ADMIN)),
):
    return update_user(
        user_id,
        AdminUserUpdate(is_active=data.is_active),
        db,
        admin,
    )


@app.delete(
    "/admin/users/{user_id}",
    response_model=MessageResponse,
    tags=["Admin"],
)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.ADMIN)),
):
    lock_write(db)

    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(404, "User not found")

    if user.id == admin.id:
        raise HTTPException(400, "You cannot delete yourself")

    employee = db.scalar(
        select(Employee.id).where(
            Employee.user_id == user_id
        )
    )

    if employee is not None:
        raise HTTPException(
            409,
            "This user has an employee record. "
            "Deactivate the user to preserve HR history.",
        )

    db.query(Notification).filter(
        Notification.user_id == user_id
    ).delete(synchronize_session=False)

    db.delete(user)
    save_changes(db)

    return {"message": "User deleted"}


# Employees

@app.post(
    "/employees",
    response_model=EmployeeResponse,
    status_code=201,
    tags=["Employees"],
)
def create_employee(
    data: EmployeeCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    lock_write(db)

    if db.get(User, data.user_id) is None:
        raise HTTPException(404, "Registered user not found")

    employee = Employee(**data.model_dump())
    db.add(employee)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "Employee already exists for this user"
        ) from None

    for policy in db.scalars(select(LeavePolicy)).all():
        ensure_balance(db, employee.id, policy)

    save_changes(db)
    db.refresh(employee)
    return employee


@app.get(
    "/employees",
    response_model=list[EmployeeResponse],
    tags=["Employees"],
)
def list_employees(
    search: str | None = None,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    query = select(Employee)

    if search and search.strip():
        term = f"%{search.strip()}%"

        query = query.where(
            or_(
                Employee.full_name.ilike(term),
                Employee.designation.ilike(term),
                Employee.department.ilike(term),
            )
        )

    return db.scalars(query.order_by(Employee.id)).all()


@app.get(
    "/employees/me",
    response_model=EmployeeResponse,
    tags=["Employees"],
)
def my_employee_profile(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return own_employee(db, user)


@app.get(
    "/employees/{employee_id}",
    response_model=EmployeeResponse,
    tags=["Employees"],
)
def get_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    employee = get_employee_or_404(db, employee_id)

    if not is_manager(user) and employee.user_id != user.id:
        raise HTTPException(403, "You do not have permission")

    return employee


@app.patch(
    "/employees/{employee_id}",
    response_model=EmployeeResponse,
    tags=["Employees"],
)
def update_employee(
    employee_id: int,
    data: EmployeeUpdate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    employee = get_employee_or_404(db, employee_id)

    for field, value in data.model_dump(
        exclude_unset=True
    ).items():
        setattr(employee, field, value)

    save_changes(db)
    db.refresh(employee)
    return employee


# Attendance

@app.post(
    "/attendance/check-in",
    response_model=AttendanceResponse,
    status_code=201,
    tags=["Attendance"],
)
def check_in(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lock_write(db)
    employee = active_employee(db, user)
    now = datetime.now(INDIA)
    today = now.date()

    if today.weekday() not in WORKING_DAYS:
        raise HTTPException(400, "Today is not a configured working day")

    if approved_leave_on(db, employee.id, today):
        raise HTTPException(409, "You have approved leave today")

    open_record = db.scalar(
        select(Attendance.id).where(
            Attendance.employee_id == employee.id,
            Attendance.check_in.is_not(None),
            Attendance.check_out.is_(None),
        )
    )

    if open_record is not None:
        raise HTTPException(
            409, "Check out your open attendance first"
        )

    existing = db.scalar(
        select(Attendance.id).where(
            Attendance.employee_id == employee.id,
            Attendance.date == today,
        )
    )

    if existing is not None:
        raise HTTPException(
            409, "Attendance already recorded for today"
        )

    deadline = datetime.combine(
        today, WORK_START, tzinfo=INDIA
    ) + timedelta(minutes=LATE_GRACE_MINUTES)

    late_seconds = max(
        (now - deadline).total_seconds(), 0
    )

    record = Attendance(
        employee_id=employee.id,
        date=today,
        check_in=now.astimezone(timezone.utc),
        status=AttendanceStatus.HALF_DAY,
        is_late=late_seconds > 0,
        late_minutes=math.ceil(late_seconds / 60),
    )

    db.add(record)
    save_changes(db)
    db.refresh(record)
    return record


@app.post(
    "/attendance/check-out",
    response_model=AttendanceResponse,
    tags=["Attendance"],
)
def check_out(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lock_write(db)
    employee = active_employee(db, user)

    record = db.scalar(
        select(Attendance)
        .where(
            Attendance.employee_id == employee.id,
            Attendance.check_in.is_not(None),
            Attendance.check_out.is_(None),
        )
        .order_by(Attendance.date.desc())
    )

    if record is None:
        raise HTTPException(400, "No open check-in found")

    now = datetime.now(timezone.utc)
    started = record.check_in

    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)

    seconds = (now - started).total_seconds()

    record.check_out = now
    record.status = (
        AttendanceStatus.PRESENT
        if seconds >= 8 * 3600
        else AttendanceStatus.HALF_DAY
    )

    save_changes(db)
    db.refresh(record)
    return record


@app.get(
    "/attendance",
    response_model=list[AttendanceResponse],
    tags=["Attendance"],
)
def list_attendance(
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Attendance)

    if not is_manager(user):
        employee = own_employee(db, user)

        if employee_id is not None and employee_id != employee.id:
            raise HTTPException(403, "You do not have permission")

        employee_id = employee.id

    if employee_id is not None:
        query = query.where(
            Attendance.employee_id == employee_id
        )

    return db.scalars(
        query.order_by(
            Attendance.date.desc(),
            Attendance.id.desc(),
        )
    ).all()


@app.post(
    "/attendance/mark",
    response_model=AttendanceResponse,
    status_code=201,
    tags=["Attendance"],
)
def mark_absent(
    data: AttendanceMark,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    lock_write(db)
    employee = get_employee_or_404(db, data.employee_id)

    if data.date >= today_india():
        raise HTTPException(400, "Choose a past date")

    if data.date < employee.joining_date:
        raise HTTPException(400, "Date is before joining date")

    if data.date.weekday() not in WORKING_DAYS:
        raise HTTPException(400, "Not a configured working day")

    if approved_leave_on(db, employee.id, data.date):
        raise HTTPException(409, "Employee has approved leave")

    existing = db.scalar(
        select(Attendance.id).where(
            Attendance.employee_id == employee.id,
            Attendance.date == data.date,
        )
    )

    if existing is not None:
        raise HTTPException(409, "Attendance already exists")

    record = Attendance(
        employee_id=employee.id,
        date=data.date,
        status=AttendanceStatus.ABSENT,
        is_late=False,
        late_minutes=0,
    )

    db.add(record)
    save_changes(db)
    db.refresh(record)
    return record


@app.post("/attendance/reconcile", tags=["Attendance"])
def reconcile_attendance(
    day: date,
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    if day >= today_india():
        raise HTTPException(400, "Choose a past date")

    count = reconcile_absences(day)

    return {
        "date": day,
        "absences_created": count,
    }


# Leave policies

@app.get(
    "/leave-policies",
    response_model=list[LeavePolicyResponse],
    tags=["Leave Policies"],
)
def list_leave_policies(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.scalars(
        select(LeavePolicy).order_by(LeavePolicy.id)
    ).all()


@app.post(
    "/leave-policies",
    response_model=LeavePolicyResponse,
    status_code=201,
    tags=["Leave Policies"],
)
def create_leave_policy(
    data: LeavePolicyCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    lock_write(db)

    existing = db.scalar(
        select(LeavePolicy.id).where(
            LeavePolicy.leave_type == data.leave_type
        )
    )

    if existing is not None:
        raise HTTPException(409, "Policy already exists")

    policy = LeavePolicy(**data.model_dump())
    db.add(policy)
    db.flush()

    for employee_id in db.scalars(select(Employee.id)).all():
        ensure_balance(db, employee_id, policy)

    save_changes(db)
    db.refresh(policy)
    return policy


@app.patch(
    "/leave-policies/{policy_id}",
    response_model=LeavePolicyResponse,
    tags=["Leave Policies"],
)
def update_leave_policy(
    policy_id: int,
    data: LeavePolicyUpdate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    lock_write(db)
    policy = db.get(LeavePolicy, policy_id)

    if policy is None:
        raise HTTPException(404, "Leave policy not found")

    employees = db.scalars(select(Employee.id)).all()

    for employee_id in employees:
        used = approved_days(
            db, employee_id, policy.leave_type
        )

        if used > data.total_days_allowed:
            raise HTTPException(
                409,
                "New allowance is below leave already used "
                f"by employee {employee_id}",
            )

        balance = ensure_balance(db, employee_id, policy)
        balance.remaining_days = data.total_days_allowed - used

    policy.total_days_allowed = data.total_days_allowed

    save_changes(db)
    db.refresh(policy)
    return policy


@app.get(
    "/leave-balances",
    response_model=list[LeaveBalanceResponse],
    tags=["Leave Policies"],
)
def list_leave_balances(
    employee_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(LeaveBalance)

    if not is_manager(user):
        employee = own_employee(db, user)

        if employee_id is not None and employee_id != employee.id:
            raise HTTPException(403, "You do not have permission")

        employee_id = employee.id

    if employee_id is not None:
        query = query.where(
            LeaveBalance.employee_id == employee_id
        )

    return db.scalars(
        query.order_by(
            LeaveBalance.employee_id,
            LeaveBalance.id,
        )
    ).all()


# Leave requests

@app.post(
    "/leaves",
    response_model=LeaveResponse,
    status_code=201,
    tags=["Leaves"],
)
def apply_leave(
    data: LeaveCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    lock_write(db)
    employee = active_employee(db, user)

    if data.start_date < today_india():
        raise HTTPException(
            400, "New leave requests cannot start in the past"
        )

    policy = db.scalar(
        select(LeavePolicy).where(
            LeavePolicy.leave_type == data.leave_type
        )
    )

    if policy is None:
        raise HTTPException(
            400, "HR must configure this leave policy first"
        )

    overlapping = db.scalar(
        select(Leave.id).where(
            Leave.employee_id == employee.id,
            Leave.status.in_(
                [LeaveStatus.PENDING, LeaveStatus.APPROVED]
            ),
            Leave.start_date <= data.end_date,
            Leave.end_date >= data.start_date,
        )
    )

    if overlapping is not None:
        raise HTTPException(
            409, "An existing leave overlaps these dates"
        )

    balance = ensure_balance(db, employee.id, policy)

    pending = db.scalars(
        select(Leave).where(
            Leave.employee_id == employee.id,
            Leave.leave_type == data.leave_type,
            Leave.status == LeaveStatus.PENDING,
        )
    ).all()

    reserved = sum(
        leave_days(item.start_date, item.end_date)
        for item in pending
    )

    requested = leave_days(data.start_date, data.end_date)

    if requested > balance.remaining_days - reserved:
        raise HTTPException(
            400,
            "Insufficient leave balance after pending requests",
        )

    record = Leave(
        employee_id=employee.id,
        **data.model_dump(),
    )

    db.add(record)
    save_changes(db)
    db.refresh(record)
    return record


@app.get(
    "/leaves",
    response_model=list[LeaveResponse],
    tags=["Leaves"],
)
def list_leaves(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Leave)

    if not is_manager(user):
        employee = own_employee(db, user)
        query = query.where(Leave.employee_id == employee.id)

    return db.scalars(
        query.order_by(Leave.id.desc())
    ).all()


@app.patch(
    "/leaves/{leave_id}/status",
    response_model=LeaveResponse,
    tags=["Leaves"],
)
def decide_leave(
    leave_id: int,
    data: LeaveDecision,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    lock_write(db)
    record = db.get(Leave, leave_id)

    if record is None:
        raise HTTPException(404, "Leave not found")

    if record.status != LeaveStatus.PENDING:
        raise HTTPException(409, "Leave has already been processed")

    employee = get_employee_or_404(db, record.employee_id)

    if employee.user_id == manager.id:
        raise HTTPException(403, "You cannot decide your own leave")

    if data.status == LeaveStatus.APPROVED:
        worked = db.scalar(
            select(Attendance.id).where(
                Attendance.employee_id == employee.id,
                Attendance.date >= record.start_date,
                Attendance.date <= record.end_date,
                Attendance.check_in.is_not(None),
            ).limit(1)
        )

        if worked is not None:
            raise HTTPException(
                409, "Working attendance overlaps this leave"
            )

        policy = db.scalar(
            select(LeavePolicy).where(
                LeavePolicy.leave_type == record.leave_type
            )
        )

        if policy is None:
            raise HTTPException(400, "Leave policy is not configured")

        balance = ensure_balance(db, employee.id, policy)
        requested = leave_days(record.start_date, record.end_date)

        changed = (
            db.query(LeaveBalance)
            .filter(
                LeaveBalance.id == balance.id,
                LeaveBalance.remaining_days >= requested,
            )
            .update(
                {
                    LeaveBalance.remaining_days:
                    LeaveBalance.remaining_days - requested
                },
                synchronize_session=False,
            )
        )

        if changed != 1:
            db.rollback()
            raise HTTPException(400, "Insufficient leave balance")

        # Remove unworked absence records covered by approved leave.
        db.query(Attendance).filter(
            Attendance.employee_id == employee.id,
            Attendance.date >= record.start_date,
            Attendance.date <= record.end_date,
            Attendance.status == AttendanceStatus.ABSENT,
            Attendance.check_in.is_(None),
        ).delete(synchronize_session=False)

    record.status = data.status

    notify(
        db,
        employee.user_id,
        "Leave update",
        f"Your leave request #{leave_id} was {data.status.value}.",
    )

    save_changes(db)
    db.refresh(record)
    return record


# Payroll

@app.post(
    "/payroll",
    response_model=PayrollResponse,
    status_code=201,
    tags=["Payroll"],
)
def create_payroll(
    data: PayrollCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    employee = get_employee_or_404(db, data.employee_id)

    month_start = parse_month(data.month).date()
    month_end = month_start.replace(
        day=calendar.monthrange(
            month_start.year, month_start.month
        )[1]
    )

    if employee.joining_date > month_end:
        raise HTTPException(
            400, "Employee had not joined during this month"
        )

    net_salary = (
        employee.salary
        + data.allowances
        + data.bonus
        - data.deductions
    )

    if net_salary < 0:
        raise HTTPException(
            400, "Deductions exceed total earnings"
        )

    if net_salary > MAX_MONEY:
        raise HTTPException(400, "Net salary exceeds supported amount")

    record = Payroll(
        employee_id=employee.id,
        month=data.month,
        basic_salary=employee.salary,
        allowances=data.allowances,
        deductions=data.deductions,
        bonus=data.bonus,
        net_salary=net_salary,
    )

    db.add(record)

    notify(
        db,
        employee.user_id,
        "Payroll generated",
        f"Your payroll for {data.month} is available.",
    )

    save_changes(db)
    db.refresh(record)
    return record


@app.get(
    "/payroll",
    response_model=list[PayrollResponse],
    tags=["Payroll"],
)
def list_payroll(
    month: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Payroll)

    if month is not None:
        parse_month(month)
        query = query.where(Payroll.month == month)

    if not is_manager(user):
        employee = own_employee(db, user)
        query = query.where(Payroll.employee_id == employee.id)

    return db.scalars(
        query.order_by(Payroll.month.desc(), Payroll.id.desc())
    ).all()


@app.get(
    "/payroll/summary",
    response_model=PayrollMonthlySummary,
    tags=["Payroll"],
)
def monthly_payroll_summary(
    month: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    employee_id = None

    if not is_manager(user):
        employee_id = own_employee(db, user).id

    return payroll_summary(db, month, employee_id)


@app.get(
    "/payroll/{payroll_id}",
    response_model=PayrollResponse,
    tags=["Payroll"],
)
def get_payroll(
    payroll_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    record = db.get(Payroll, payroll_id)

    if record is None:
        raise HTTPException(404, "Payroll not found")

    if not is_manager(user):
        employee = own_employee(db, user)

        if record.employee_id != employee.id:
            raise HTTPException(403, "You do not have permission")

    return record


# Notifications

@app.get(
    "/notifications",
    response_model=list[NotificationResponse],
    tags=["Notifications"],
)
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.id.desc())
    ).all()


@app.get("/notifications/unread-count", tags=["Notifications"])
def unread_notification_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
    )

    return {"unread_count": count}


@app.patch("/notifications/read-all", tags=["Notifications"])
def read_all_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
        .update(
            {Notification.is_read: True},
            synchronize_session=False,
        )
    )

    save_changes(db)
    return {"updated_count": count}


@app.patch(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponse,
    tags=["Notifications"],
)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    record = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )

    if record is None:
        raise HTTPException(404, "Notification not found")

    record.is_read = True
    save_changes(db)
    db.refresh(record)
    return record


# System-wide analytics: Admin only

@app.get("/analytics/summary", tags=["Analytics"])
def analytics_summary(
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.ADMIN)),
):
    today = today_india()
    start = today - timedelta(days=6)

    employees = db.scalars(select(Employee)).all()

    attendance = db.scalars(
        select(Attendance).where(
            Attendance.date >= start,
            Attendance.date <= today,
        )
    ).all()

    leaves = db.scalars(select(Leave)).all()

    active_ids = {
        employee.id
        for employee in employees
        if employee.status == EmployeeStatus.ACTIVE
    }

    departments = {}

    for employee in employees:
        departments[employee.department] = (
            departments.get(employee.department, 0) + 1
        )

    leave_statistics = {
        "PENDING": 0,
        "APPROVED": 0,
        "REJECTED": 0,
    }

    for record in leaves:
        leave_statistics[record.status.value] += 1

    def day_counts(day):
        counts = {
            "PRESENT": 0,
            "HALF_DAY": 0,
            "ABSENT": 0,
        }
        marked = set()
        late_count = 0

        for record in attendance:
            if record.date == day and record.employee_id in active_ids:
                counts[record.status.value] += 1
                marked.add(record.employee_id)

                if record.is_late:
                    late_count += 1

        counts["not_marked"] = len(active_ids - marked)
        counts["late"] = late_count
        return counts

    month = today.strftime("%Y-%m")
    summary = payroll_summary(db, month)

    return {
        "total_users": db.scalar(
            select(func.count(User.id))
        ),
        "total_employees": len(employees),
        "active_employees": len(active_ids),
        "attendance_today": day_counts(today),
        "leave_statistics": leave_statistics,
        "employees_by_department": [
            {"department": name, "count": count}
            for name, count in sorted(departments.items())
        ],
        "attendance_trend": [
            {
                "date": (
                    start + timedelta(days=index)
                ).isoformat(),
                **day_counts(start + timedelta(days=index)),
            }
            for index in range(7)
        ],
        "payroll_overview": {
            "month": month,
            "basic_salary": str(summary["total_basic_salary"]),
            "allowances": str(summary["total_allowances"]),
            "deductions": str(summary["total_deductions"]),
            "bonus": str(summary["total_bonus"]),
            "net_salary": str(summary["total_net_salary"]),
        },
    }