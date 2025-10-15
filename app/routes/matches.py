from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from .. import models, database, schemas

router = APIRouter(prefix="/matches", tags=["matches"])


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Ergebnisse abrufen ---
@router.get("/results/", response_model=List[schemas.MatchResult])
def get_results(db: Session = Depends(get_db)):
    return db.query(models.Match).all()


# --- Match speichern / updaten ---
@router.put("/save_match/", response_model=dict)
def save_match(match: schemas.MatchResult, db: Session = Depends(get_db)):
    db_match = (
        db.query(models.Match).filter(models.Match.match_id == match.match_id).first()
    )
    if db_match:
        # Update vorhandener Match
        for key, value in match.dict().items():
            setattr(db_match, key, value)
        db.commit()
        db.refresh(db_match)
        return {"msg": "Match updated"}
    else:
        # Neues Match hinzufügen
        new_match = models.Match(**match.dict())
        db.add(new_match)
        db.commit()
        db.refresh(new_match)
        return {"msg": "Match saved"}
