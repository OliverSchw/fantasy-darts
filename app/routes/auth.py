from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from .. import database, models
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from datetime import datetime, timedelta
from pydantic import BaseModel

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


SECRET_KEY = "SUPER_GEHEIMER_SCHLÜSSEL"  #
ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

router = APIRouter(prefix="/auth", tags=["auth"])


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(password, hashed):
    return pwd_context.verify(password, hashed)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    user_id: int
    username: str
    is_admin: bool
    access_token: str
    token_type: str

    class Config:
        orm_mode = True


class RegisterRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class UserAdminOut(BaseModel):
    id: int
    username: str
    is_admin: bool

    class Config:
        orm_mode = True


class UserUpdateAdminStatus(BaseModel):
    is_admin: bool


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return int(user_id)

    except JWTError:
        raise credentials_exception


def get_current_admin(
    db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized (Admin required)")
    return user


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == req.username).first()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Payload und Token erstellen
    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": str(user.id), "is_admin": user.is_admin},
        expires_delta=access_token_expires,
    )

    return {
        "user_id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.get("/users", response_model=list[UserAdminOut])
def get_all_users(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    """Returns a list of all users. Admins only."""
    users = db.query(models.User).all()
    return users


@router.put("/users/{user_id}")
def update_user_admin_status(
    user_id: int,
    update_data: UserUpdateAdminStatus,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    """Changes a user's admin status. Admins only."""
    user = db.query(models.User).filter(models.User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_admin = update_data.is_admin
    db.commit()
    return {
        "message": f"User {user.username} admin status updated to {update_data.is_admin}"
    }


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    """Deletes a user by ID. Admins only."""

    if user_id == current_admin.id:
        raise HTTPException(
            status_code=403, detail="You cannot delete your own account while logged in"
        )

    teams_to_delete = db.query(models.Team).filter(models.Team.user_id == user_id).all()

    if teams_to_delete:
        for team in teams_to_delete:
            db.delete(team)

    user_query = db.query(models.User).filter(models.User.id == user_id)

    if not user_query.first():
        raise HTTPException(status_code=404, detail="User not found")
    user_query.delete(synchronize_session=False)

    db.commit()

    return


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(
    req: RegisterRequest,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):

    existing_user = (
        db.query(models.User).filter(models.User.username == req.username).first()
    )
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = pwd_context.hash(req.password)

    user = models.User(
        username=req.username,
        password_hash=hashed_password,
        is_admin=req.is_admin,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "message": f"User {user.username} created successfully with admin status: {user.is_admin}"
    }


@router.get("/{user_id}/active_team")
def get_active_team_id(user_id: int, db: Session = Depends(get_db)):

    user = db.get(models.User, user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    return {
        "user_id": user_id,
        "active_team_id": user.active_team_id,
    }
