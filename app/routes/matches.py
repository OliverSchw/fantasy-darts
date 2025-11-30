from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from typing import List
from .. import models, database, schemas
from .auth import get_current_admin

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
# @router.put("/save_match/", response_model=dict)
# def save_match(match: schemas.MatchResult, db: Session = Depends(get_db)):
#     db_match = (
#         db.query(models.Match).filter(models.Match.match_id == match.match_id).first()
#     )
#     if db_match:
#         # Update vorhandener Match
#         for key, value in match.dict().items():
#             setattr(db_match, key, value)
#         db.commit()
#         db.refresh(db_match)
#         return {"msg": "Match updated"}
#     else:
#         # Neues Match hinzufügen
#         new_match = models.Match(**match.dict())
#         db.add(new_match)
#         db.commit()
#         db.refresh(new_match)
#         return {"msg": "Match saved"}
@router.put("/save_match/", response_model=dict)
def save_match(
    match: schemas.MatchResult,
    db: Session = Depends(get_db),
    # Hinzufügen der Admin-Prüfung:
    current_admin: models.User = Depends(get_current_admin),
):
    """Speichert oder aktualisiert Match-Ergebnisse. Nur für Admins."""

    # Der Code im Funktionskörper bleibt gleich, da der Schutz bereits durch Depends(get_current_admin) gewährleistet ist.

    db_match = (
        db.query(models.Match).filter(models.Match.match_id == match.match_id).first()
    )

    if db_match:
        #
        for key, value in match.dict().items():
            setattr(db_match, key, value)
        db.commit()
        db.refresh(db_match)
        return {"msg": "Match updated"}
    else:
        #
        new_match = models.Match(**match.dict())
        db.add(new_match)
        db.commit()
        db.refresh(new_match)
        return {"msg": "Match saved"}


@router.delete("/{match_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_match(
    match_id: str,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),  # Admin-Schutz beibehalten
):
    deleted_count = (
        db.query(models.Match)
        .filter(models.Match.match_id == match_id)
        .delete(synchronize_session=False)
    )

    db.commit()

    if deleted_count == 0:
        # Wenn 0 Zeilen gelöscht wurden, existierte das Match nicht.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Match with ID '{match_id}' not found.",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
