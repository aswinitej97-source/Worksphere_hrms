from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from database import Base, engine, get_db
from models import (
    Attendance,
    AttendanceStatus,
    Employee,
    EmployeeStatus,
    Leave,
    LeaveStatus,
    Notification,
    Payroll,
    Role,
    User,
)
from schemas import (
    AttendanceMark,
    AttendanceResponse,
    EmployeeCreate,
    EmployeeResponse,
    EmployeeUpdate,
    LeaveCreate,
    LeaveDecision,
    LeaveResponse,
    NotificationResponse,
    PayrollCreate,
    PayrollResponse,
    RoleUpdate,
    TokenResponse,
    UserRegister,
    UserResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="WorkSphere HRMS API",
    version="1.0.0",
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

INDIA = timezone(timedelta(hours=5, minutes=30))


# Helpers

def today_india():
    return datetime.now(INDIA).date()


def is_manager(user):
    return user.role in (Role.HR, Role.ADMIN)


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
    return employee


def save_changes(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Record conflicts with existing data")


def notify(db, user_id, title, message):
    db.add(
        Notification(
            user_id=user_id,
            title=title,
            message=message,
        )
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
def register(data: UserRegister, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    existing = db.scalar(
        select(User).where(
            or_(User.username == data.username, User.email == email)
        )
    )
    if existing:
        raise HTTPException(409, "Username or email already exists")

    user = User(
        username=data.username,
        email=email,
        hashed_password=hash_password(data.password),
        role=Role.EMPLOYEE,
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
        select(User).where(User.username == form.username)
    )
    if user is None or not verify_password(
        form.password, user.hashed_password
    ):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(user.id))


@app.get(
    "/auth/me",
    response_model=UserResponse,
    tags=["Authentication"],
)
def get_profile(user: User = Depends(get_current_user)):
    return user


# Dashboards

@app.get("/dashboard/employee", tags=["Dashboards"])
def employee_dashboard(user: User = Depends(get_current_user)):
    return {
        "message": f"Welcome, {user.username}",
        "role": user.role,
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


# Admin

@app.get(
    "/admin/users",
    response_model=list[UserResponse],
    tags=["Admin"],
)
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.ADMIN)),
):
    return db.scalars(select(User).order_by(User.id)).all()


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
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(400, "You cannot change your own role")

    user.role = data.role
    save_changes(db)
    db.refresh(user)
    return user


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
    if db.get(User, data.user_id) is None:
        raise HTTPException(404, "Registered user not found")

    existing = db.scalar(
        select(Employee).where(Employee.user_id == data.user_id)
    )
    if existing:
        raise HTTPException(409, "Employee already exists for this user")

    employee = Employee(**data.model_dump())
    db.add(employee)
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
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(404, "Employee not found")
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
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(404, "Employee not found")

    for field, value in data.model_dump(exclude_unset=True).items():
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
    employee = active_employee(db, user)
    open_record = db.scalar(
        select(Attendance).where(
            Attendance.employee_id == employee.id,
            Attendance.check_in.is_not(None),
            Attendance.check_out.is_(None),
        )
    )
    if open_record:
        raise HTTPException(409, "Check out your open attendance first")

    today = today_india()
    existing = db.scalar(
        select(Attendance).where(
            Attendance.employee_id == employee.id,
            Attendance.date == today,
        )
    )
    if existing:
        raise HTTPException(409, "Attendance already recorded for today")

    record = Attendance(
        employee_id=employee.id,
        date=today,
        check_in=datetime.now(timezone.utc),
        status=AttendanceStatus.HALF_DAY,
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
    employee = active_employee(db, user)
    record = db.scalar(
        select(Attendance).where(
            Attendance.employee_id == employee.id,
            Attendance.check_in.is_not(None),
            Attendance.check_out.is_(None),
        ).order_by(Attendance.date.desc())
    )
    if record is None:
        raise HTTPException(400, "No open check-in found")

    now = datetime.now(timezone.utc)
    started = record.check_in
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)

    seconds = (now - started).total_seconds()
    final_status = (
        AttendanceStatus.PRESENT
        if seconds >= 8 * 3600
        else AttendanceStatus.HALF_DAY
    )

    changed = (
        db.query(Attendance)
        .filter(
            Attendance.id == record.id,
            Attendance.check_out.is_(None),
        )
        .update(
            {
                Attendance.check_out: now,
                Attendance.status: final_status,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "Already checked out")

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
        query = query.where(Attendance.employee_id == employee.id)
    elif employee_id is not None:
        query = query.where(Attendance.employee_id == employee_id)

    return db.scalars(
        query.order_by(Attendance.date.desc(), Attendance.id.desc())
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
    if data.date >= today_india():
        raise HTTPException(400, "Choose a past date to mark absence")
    if db.get(Employee, data.employee_id) is None:
        raise HTTPException(404, "Employee not found")

    existing = db.scalar(
        select(Attendance).where(
            Attendance.employee_id == data.employee_id,
            Attendance.date == data.date,
        )
    )
    if existing:
        raise HTTPException(409, "Attendance already exists for this date")

    record = Attendance(
        employee_id=data.employee_id,
        date=data.date,
        status=AttendanceStatus.ABSENT,
    )
    db.add(record)
    save_changes(db)
    db.refresh(record)
    return record


# Leaves

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
    employee = active_employee(db, user)
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
        raise HTTPException(409, "An existing leave overlaps these dates")

    record = Leave(employee_id=employee.id, **data.model_dump())
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
    return db.scalars(query.order_by(Leave.id.desc())).all()


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
    record = db.get(Leave, leave_id)
    if record is None:
        raise HTTPException(404, "Leave not found")

    employee = db.get(Employee, record.employee_id)
    if employee is None:
        raise HTTPException(404, "Employee not found")
    if employee.user_id == manager.id:
        raise HTTPException(403, "You cannot decide your own leave")

    changed = (
        db.query(Leave)
        .filter(
            Leave.id == leave_id,
            Leave.status == LeaveStatus.PENDING,
        )
        .update(
            {Leave.status: data.status},
            synchronize_session=False,
        )
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "Leave has already been processed")

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
    employee = db.get(Employee, data.employee_id)
    if employee is None:
        raise HTTPException(404, "Employee not found")

    existing = db.scalar(
        select(Payroll).where(
            Payroll.employee_id == employee.id,
            Payroll.month == data.month,
        )
    )
    if existing:
        raise HTTPException(409, "Payroll already exists for this month")

    net_salary = employee.salary + data.bonus - data.deductions
    if net_salary < 0:
        raise HTTPException(400, "Deductions exceed salary plus bonus")

    record = Payroll(
        employee_id=employee.id,
        month=data.month,
        basic_salary=employee.salary,
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Payroll)
    if not is_manager(user):
        employee = own_employee(db, user)
        query = query.where(Payroll.employee_id == employee.id)
    return db.scalars(
        query.order_by(Payroll.month.desc(), Payroll.id.desc())
    ).all()


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
    ids = db.scalars(
        select(Notification.id).where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
    ).all()
    return {"unread_count": len(ids)}


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


# Analytics

@app.get("/analytics/summary", tags=["Analytics"])
def analytics_summary(
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
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
    payroll = db.scalars(
        select(Payroll).where(
            Payroll.month == today.strftime("%Y-%m")
        )
    ).all()

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
    for leave in leaves:
        leave_statistics[leave.status.value] += 1

    def day_counts(day):
        counts = {"PRESENT": 0, "HALF_DAY": 0, "ABSENT": 0}
        marked = set()

        for record in attendance:
            if record.date == day and record.employee_id in active_ids:
                counts[record.status.value] += 1
                marked.add(record.employee_id)

        counts["not_marked"] = len(active_ids - marked)
        return counts

    zero = Decimal("0.00")

    return {
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
                "date": (start + timedelta(days=index)).isoformat(),
                **day_counts(start + timedelta(days=index)),
            }
            for index in range(7)
        ],
        "payroll_overview": {
            "month": today.strftime("%Y-%m"),
            "basic_salary": str(
                sum((item.basic_salary for item in payroll), zero)
            ),
            "deductions": str(
                sum((item.deductions for item in payroll), zero)
            ),
            "bonus": str(
                sum((item.bonus for item in payroll), zero)
            ),
            "net_salary": str(
                sum((item.net_salary for item in payroll), zero)
            ),
        },
    }