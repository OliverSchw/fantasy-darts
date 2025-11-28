from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from .. import database, models
from ..schemas import TeamCreate
from pydantic import BaseModel
from .auth import get_current_admin


# ... (Ihr existierender Router)
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


router = APIRouter(prefix="/config", tags=["config"])


class LockStatusPayload(
    BaseModel
):  # Sie müssen pydantic für diesen Payload importieren
    teams_locked: bool


@router.get("/lock-status", status_code=status.HTTP_200_OK)
def get_lock_status(db: Session = Depends(get_db)):
    """Ruft den aktuellen Sperrstatus für Teams ab."""

    # 1. Status aus der DB abfragen
    # Hier wird angenommen, dass Sie ein Feld mit key='teams_locked' haben
    config_entry = (
        db.query(models.Config).filter(models.Config.key == "teams_locked").first()
    )

    # 2. Wert zurückgeben (Standardwert ist False, falls Eintrag nicht existiert)
    if config_entry:
        # Wandeln Sie den Wert in einen booleschen Typ um
        teams_locked = config_entry.value
    else:
        teams_locked = False

    return {"teams_locked": teams_locked}


# Angenommen, Sie haben diese Funktion


@router.post("/lock-status", status_code=status.HTTP_200_OK)
def set_lock_status(
    payload: LockStatusPayload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
):
    """Setzt den globalen Sperrstatus für Teams."""

    # 1. Prüfen, ob der Konfigurations-Eintrag existiert
    config_entry = (
        db.query(models.Config).filter(models.Config.key == "teams_locked").first()
    )

    if config_entry:
        # Aktualisieren
        config_entry.value = payload.teams_locked
    else:
        # Erstellen (falls dies der allererste Aufruf ist)
        new_entry = models.Config(key="teams_locked", value=payload.teams_locked)
        db.add(new_entry)

    db.commit()
    db.refresh(config_entry or new_entry)  # Aktualisieren Sie das Objekt, falls nötig

    return {"message": "Team lock status updated successfully."}
