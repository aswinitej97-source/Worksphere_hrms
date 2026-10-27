from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import Document, Employee
from schemas import DocumentCreate, DocumentResponse


router = APIRouter(
    prefix="/documents",
    tags=["Documents"],
)


@router.post(
    "/",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    data: DocumentCreate,
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

    document = Document(
        employee_id=data.employee_id,
        file_name=data.file_name,
        file_url=data.file_url,
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    return document


@router.get(
    "/",
    response_model=list[DocumentResponse],
)
def get_documents(
    db: Session = Depends(get_db),
):
    return db.query(Document).all()


@router.get(
    "/employee/{employee_id}",
    response_model=list[DocumentResponse],
)
def get_employee_documents(
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
        db.query(Document)
        .filter(Document.employee_id == employee_id)
        .all()
    )