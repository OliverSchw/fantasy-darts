# create_users.py
from app import database, models
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_user(username: str, password: str, is_admin=False):
    db = database.SessionLocal()
    try:
        # Check if the user already exists
        existing = (
            db.query(models.User).filter(models.User.username == username).first()
        )
        if existing:
            print(f"User '{username}' already exists, skipping")
            return

        hashed = hash_password(password)
        user = models.User(username=username, password_hash=hashed, is_admin=is_admin)
        db.add(user)
        db.commit()
        print(f"User '{username}' created successfully")
    finally:
        db.close()


# if __name__ == "__main__":
#     # create_user("olli", "geheimespasswort")
#     # create_user("maria", "passwort123")
#     # print("Users created successfully!")
