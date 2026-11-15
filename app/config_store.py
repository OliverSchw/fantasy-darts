"""Einstellungen, die der Admin in der Oberfläche pflegt (statt im Code / in Dateien).

- Regeln: seasons/<key>/rules.toml ist nur die Vorlage. Speichert der Admin Regeln in der
  Oberfläche, liegen sie komplett in der DB und haben Vorrang.
- Einladungscode: aus der DB, sonst aus der Umgebungsvariable INVITE_CODE.
"""

from sqlalchemy.orm import Session

from . import models
from .rules import Rules, load_rules
from .settings import get_settings

INVITE_KEY = "invite_code"


def _rules_key(season_key: str) -> str:
    return f"rules:{season_key}"


def get_setting(db: Session, key: str):
    row = db.get(models.AppSetting, key)
    return row.value if row else None


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(models.AppSetting, key)
    if value is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(models.AppSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


# ---------------------------------------------------------------- Regeln


def season_rules(db: Session, season: models.Season) -> Rules:
    override = get_setting(db, _rules_key(season.key))
    if override:
        return Rules.model_validate(override)
    return load_rules(season.key)


def rules_customized(db: Session, season: models.Season) -> bool:
    return get_setting(db, _rules_key(season.key)) is not None


def save_rules(db: Session, season: models.Season, rules: Rules) -> None:
    set_setting(db, _rules_key(season.key), rules.model_dump(mode="json"))


def reset_rules(db: Session, season: models.Season) -> None:
    set_setting(db, _rules_key(season.key), None)


# ---------------------------------------------------------------- Einladungscode


def invite_code(db: Session) -> str:
    return get_setting(db, INVITE_KEY) or get_settings().invite_code
