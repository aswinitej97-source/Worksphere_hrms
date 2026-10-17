from getpass import getpass

from pydantic import ValidationError
from sqlalchemy import or_, select

from auth import hash_password
from database import Base, SessionLocal, engine
from models import Role, User
from schemas import UserRegister


def main():
    print("Create WorkSphere Admin")

    username = input("Username: ").strip()
    email = input("Email: ").strip().lower()
    password = getpass("Password (minimum 8 characters): ")
    confirm = getpass("Confirm password: ")

    if password != confirm:
        print("Passwords do not match.")
        return

    try:
        data = UserRegister(
            username=username,
            email=email,
            password=password,
        )
    except ValidationError:
        print(
            "Invalid details. Use a valid email, a username of "
            "3–50 letters/numbers/underscores, and a password "
            "of 8–128 characters."
        )
        return

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        existing = db.scalar(
            select(User).where(
                or_(
                    User.username == data.username,
                    User.email == str(data.email).lower(),
                )
            )
        )
        if existing:
            print(
                "Username or email already exists. "
                "Use different details."
            )
            return

        admin = User(
            username=data.username,
            email=str(data.email).lower(),
            hashed_password=hash_password(data.password),
            role=Role.ADMIN,
        )
        db.add(admin)
        db.commit()
        print("Admin account created successfully.")


if __name__ == "__main__":
    main()