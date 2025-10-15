# create_users.py
from app import database, models
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_user(username: str, password: str):
    db = database.SessionLocal()
    hashed = hash_password(password)
    user = models.User(username=username, password_hash=hashed)
    db.add(user)
    db.commit()
    db.close()


if __name__ == "__main__":
    create_user("olli", "geheimespasswort")
    create_user("maria", "passwort123")
    print("Users created successfully!")
