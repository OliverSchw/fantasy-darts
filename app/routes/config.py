from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from .. import database, models
from ..schemas import TeamCreate
from pydantic import BaseModel
from .auth import get_current_admin


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


router = APIRouter(prefix="/config", tags=["config"])


class LockStatusPayload(BaseModel):
    teams_locked: bool


@router.get("/lock-status", status_code=status.HTTP_200_OK)
def get_lock_status(db: Session = Depends(get_db)):
    """Returns the global lock status for teams."""

    config_entry = (
        db.query(models.Config).filter(models.Config.key == "teams_locked").first()
    )

    if config_entry:

        teams_locked = config_entry.value
    else:
        teams_locked = False

    return {"teams_locked": teams_locked}


@router.post("/lock-status", status_code=status.HTTP_200_OK)
def set_lock_status(
    payload: LockStatusPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
):
    """Sets the global lock status for teams. Admins only."""

    config_entry = (
        db.query(models.Config).filter(models.Config.key == "teams_locked").first()
    )

    if config_entry:
        config_entry.value = payload.teams_locked
    else:
        new_entry = models.Config(key="teams_locked", value=payload.teams_locked)
        db.add(new_entry)

    db.commit()
    db.refresh(config_entry or new_entry)

    return {"message": "Team lock status updated successfully."}
