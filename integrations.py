from fastapi import HTTPException
import os
from fastapi import APIRouter, Depends
from auth import require_roles
from models import Role

router = APIRouter(
    prefix="/integrations",
    tags=["Third-Party Integrations"],
    dependencies=[
        Depends(require_roles(Role.HR, Role.ADMIN))
    ]
)
from pydantic import BaseModel, EmailStr

class EmailNotification(BaseModel):
    recipient: EmailStr
    subject: str
    message: str
@router.post("/send-email")
def send_email(data: EmailNotification):
    from dotenv import load_dotenv

    load_dotenv()

    email_test_mode = (
        os.getenv("EMAIL_TEST_MODE", "false").lower() == "true"
    )

    if email_test_mode:
        return {
            "message": "Email simulated successfully",
            "mode": "TEST",
            "recipient": str(data.recipient),
            "email_sent": False
        }

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not all([smtp_host, smtp_user, smtp_password]):
        raise HTTPException(
            status_code=503,
            detail="Email service not configured"
        )

    email = EmailMessage()
    email["From"] = smtp_user
    email["To"] = data.recipient
    email["Subject"] = data.subject
    email.set_content(data.message)

    try:
        with smtplib.SMTP(
            smtp_host, smtp_port, timeout=10
        ) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(email)

    except (smtplib.SMTPException, OSError):
        raise HTTPException(
            status_code=502,
            detail="Email delivery failed"
        ) from None

    return {
        "message": "Email sent successfully",
        "mode": "LIVE",
        "email_sent": True
    }
