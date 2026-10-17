from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user, require_roles
from database import get_db
from models import Employee, EmployeeStatus, Role, User
from schemas import (
    EmployeeCreate,
    EmployeeResponse,
    EmployeeUpdate,
)

router = APIRouter(prefix="/employees", tags=["Employees"])


@router.get("/me", response_model=EmployeeResponse)
def my_employee_profile(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    employee = db.scalar(
        select(Employee).where(Employee.user_id == user.id)
    )
    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee profile not created. Contact HR.",
        )
    return employee


@router.post(
    "",
    response_model=EmployeeResponse,
    status_code=201,
)
def add_employee(
    data: EmployeeCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    if db.get(User, data.user_id) is None:
        raise HTTPException(
            status_code=404, detail="User not found"
        )

    existing = db.scalar(
        select(Employee).where(
            Employee.user_id == data.user_id
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Employee profile already exists for this user",
        )

    employee = Employee(**data.model_dump())
    db.add(employee)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Unable to create employee; check user details",
        )

    db.refresh(employee)
    return employee


@router.get("", response_model=list[EmployeeResponse])
def list_employees(
    search: str | None = Query(default=None, max_length=150),
    department: str | None = Query(
        default=None, max_length=100
    ),
    status: EmployeeStatus | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    query = select(Employee)

    if search and search.strip():
        term = search.strip()
        query = query.where(
            or_(
                Employee.full_name.contains(
                    term, autoescape=True
                ),
                Employee.designation.contains(
                    term, autoescape=True
                ),
                Employee.department.contains(
                    term, autoescape=True
                ),
            )
        )

    if department:
        query = query.where(
            Employee.department == department.strip()
        )

    if status:
        query = query.where(Employee.status == status)

    query = (
        query.order_by(Employee.id)
        .offset(offset)
        .limit(limit)
    )
    return db.scalars(query).all()


@router.get("/{employee_id}", response_model=EmployeeResponse)
def get_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(
            status_code=404, detail="Employee not found"
        )

    if (
        user.role == Role.EMPLOYEE
        and employee.user_id != user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="You can only view your own profile",
        )

    return employee


@router.patch(
    "/{employee_id}",
    response_model=EmployeeResponse,
)
def update_employee(
    employee_id: int,
    data: EmployeeUpdate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(Role.HR, Role.ADMIN)),
):
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(
            status_code=404, detail="Employee not found"
        )

    for field, value in data.model_dump(
        exclude_unset=True
    ).items():
        setattr(employee, field, value)

    db.commit()
    db.refresh(employee)
    return employee