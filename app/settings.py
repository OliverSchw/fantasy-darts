"""Zentrale Konfiguration über Umgebungsvariablen (bzw. eine lokale .env-Datei)."""

import logging
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
log = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    # Lokal reicht SQLite. In Produktion die Postgres-URL (z.B. von Neon) setzen.
    database_url: str = f"sqlite:///{ROOT_DIR / 'fantasy.db'}"

    # Signiert die Login-Cookies. In Produktion UNBEDINGT setzen
    # (z.B. `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
    secret_key: str = ""

    # Welche Saison (Ordner unter seasons/) aktiv ist.
    season: str = "wm2026"
    seasons_dir: Path = ROOT_DIR / "seasons"

    # Cookies nur über HTTPS senden (in Produktion True).
    secure_cookies: bool = False

    # Wenn gesetzt, können sich neue User unter /register selbst anmelden,
    # sofern sie diesen Code kennen. Leer = nur der Admin legt User an.
    invite_code: str = ""

    # Zeitzone für Anzeige und "Spieltage" (Bewegung im Ranking)
    timezone: str = "Europe/Berlin"

    @property
    def sqlalchemy_url(self) -> str:
        """Normalisiert Postgres-URLs auf den psycopg-3-Treiber."""
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.secret_key:
        log.warning("SECRET_KEY ist nicht gesetzt - verwende zufälligen Schlüssel (Logins überleben keinen Neustart).")
        s.secret_key = secrets.token_urlsafe(32)
    return s
