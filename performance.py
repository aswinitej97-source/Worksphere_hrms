from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import Employee, Performance
from schemas import PerformanceCreate, PerformanceResponse


router = APIRouter(
    prefix="/performance",
    tags=["Performance"],
)


@router.post(
    "/",
    response_model=PerformanceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_performance_review(
    data: PerformanceCreate,
    db: Session = Depends(get_db),
):
    employee = (
        db.query(Employee)
        .filter(Employee.id == data.employee_id)
        .first()
    )

    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    performance = Performance(
        employee_id=data.employee_id,
        review_period=data.review_period,
        rating=data.rating,
        feedback=data.feedback,
    )

    db.add(performance)
    db.commit()
    db.refresh(performance)

    return performance


@router.get(
    "/",
    response_model=list[PerformanceResponse],
)
def get_performance_reviews(
    db: Session = Depends(get_db),
):
    return db.query(Performance).all()


@router.get(
    "/employee/{employee_id}",
    response_model=list[PerformanceResponse],
)
def get_employee_performance(
    employee_id: int,
    db: Session = Depends(get_db),
):
    employee = (
        db.query(Employee)
        .filter(Employee.id == employee_id)
        .first()
    )

    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    return (
        db.query(Performance)
        .filter(Performance.employee_id == employee_id)
        .all()
    )