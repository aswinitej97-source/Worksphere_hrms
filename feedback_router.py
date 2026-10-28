
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from feedback import Feedback
from feedback_schemas import FeedbackCreate, FeedbackResponse

router = APIRouter(
    prefix="/feedback",
    tags=["Employee Feedback"]
)


@router.post("/", response_model=FeedbackResponse)
def submit_feedback(
    data: FeedbackCreate,
    db: Session = Depends(get_db)
):
    feedback = Feedback(**data.model_dump())
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


@router.get("/", response_model=list[FeedbackResponse])
def get_feedback(db: Session = Depends(get_db)):
    return db.query(Feedback).all()


@router.get("/{feedback_id}", response_model=FeedbackResponse)
def get_feedback_by_id(
    feedback_id: int,
    db: Session = Depends(get_db)
):
    feedback = db.get(Feedback, feedback_id)

    if not feedback:
        raise HTTPException(
            status_code=404,
            detail="Feedback not found"
        )

    return feedback
