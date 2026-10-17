import tkinter as tk
from tkinter import simpledialog

from sqlalchemy import select

from auth import hash_password
from database import SessionLocal
from models import User

root = tk.Tk()
root.withdraw()

try:
    password = simpledialog.askstring(
        "Reset password",
        "Enter a new password (8–128 characters):",
        show="*",
        parent=root,
    )
    confirm = simpledialog.askstring(
        "Confirm password",
        "Enter the same password again:",
        show="*",
        parent=root,
    )

    if password is None or confirm is None:
        print("Reset cancelled.")
    elif not 8 <= len(password) <= 128:
        print("Password must contain 8–128 characters.")
    elif password != confirm:
        print("Passwords do not match.")
    else:
        with SessionLocal() as db:
            user = db.scalar(
                select(User).where(
                    User.username == "tejaswini21"
                )
            )
            if user is None:
                print("User not found.")
            else:
                user.hashed_password = hash_password(password)
                db.commit()
                print("Password reset successfully.")
finally:
    root.destroy()
    
