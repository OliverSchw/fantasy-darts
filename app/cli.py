"""Verwaltung über die Kommandozeile.

    python -m app.cli import-season wm2027            # Spieler + Auslosung importieren
    python -m app.cli import-season wm2027 --replace  # Saison komplett neu (löscht Teams/Ergebnisse!)
    python -m app.cli create-user olli --admin        # fragt nach dem Passwort
    python -m app.cli import-legacy-users sqlite:///alt.db   # User aus der alten Version übernehmen
    python -m app.cli check-rules wm2027              # rules.toml prüfen
    python -m app.cli backup                          # Komplett-Backup der aktiven Saison als JSON
    python -m app.cli restore-backup backup.json      # Backup in eine (neue) Datenbank einspielen

Gegen die Produktionsdatenbank: vorher DATABASE_URL setzen (bzw. in .env eintragen).
"""

import argparse
import getpass
import json
import sys
from datetime import date

from sqlalchemy import create_engine, func, select, text

from . import models
from .auth import hash_password
from .db import SessionLocal, create_tables
from .backup import export_backup, restore_backup
from .rules import load_rules
from .season import get_season, import_season
from .settings import get_settings


def cmd_import_season(args):
    create_tables()
    with SessionLocal() as db:
        season = import_season(db, args.key, replace=args.replace)
        n = db.scalar(select(func.count()).select_from(models.Player).where(models.Player.season_id == season.id))
        print(f"Saison '{season.key}' importiert: {n} Spieler, Turnierbaum angelegt.")


def cmd_create_user(args):
    create_tables()
    password = args.password or getpass.getpass(f"Passwort für {args.username}: ")
    with SessionLocal() as db:
        if db.scalar(select(models.User).where(func.lower(models.User.username) == args.username.lower())):
            sys.exit(f"User '{args.username}' existiert schon.")
        db.add(models.User(username=args.username, password_hash=hash_password(password), is_admin=args.admin))
        db.commit()
    print(f"User '{args.username}' angelegt{' (Admin)' if args.admin else ''}.")


def cmd_import_legacy_users(args):
    """Übernimmt Username, Passwort-Hash und Admin-Flag aus der alten Datenbank."""
    create_tables()
    old = create_engine(args.url.replace("postgres://", "postgresql+psycopg://", 1))
    with old.connect() as conn:
        rows = conn.execute(text("SELECT username, password_hash, is_admin FROM users")).all()
    added = 0
    with SessionLocal() as db:
        for username, pw_hash, is_admin in rows:
            if db.scalar(select(models.User).where(func.lower(models.User.username) == username.lower())):
                continue
            db.add(models.User(username=username, password_hash=pw_hash, is_admin=bool(is_admin)))
            added += 1
        db.commit()
    print(f"{added} User übernommen ({len(rows) - added} gab es schon).")


def cmd_check_rules(args):
    r = load_rules(args.key)
    print(f"OK: {r.name} - {r.tournament.num_rounds} Runden, Budget {r.team.budget}, {len(r.scoring.stats)} Stats")


def cmd_backup(args):
    key = args.season or get_settings().season
    with SessionLocal() as db:
        data = export_backup(db, get_season(db, key))
    out = args.out or f"fantasy-darts_backup_{key}_{date.today().isoformat()}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"Backup geschrieben: {out} ({len(data['teams'])} Teams, "
          f"{sum(1 for m in data['matches'] if m['winner_id'])} Ergebnisse, {len(data['users'])} User)")


def cmd_restore_backup(args):
    create_tables()
    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)
    with SessionLocal() as db:
        season = restore_backup(db, data)
    print(f"Saison '{season.key}' wiederhergestellt: {len(data['teams'])} Teams, {len(data['users'])} User.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("import-season")
    s.add_argument("key")
    s.add_argument("--replace", action="store_true")
    s.set_defaults(func=cmd_import_season)

    s = sub.add_parser("create-user")
    s.add_argument("username")
    s.add_argument("--admin", action="store_true")
    s.add_argument("--password", help="nur für Skripte; sonst wird interaktiv gefragt")
    s.set_defaults(func=cmd_create_user)

    s = sub.add_parser("import-legacy-users")
    s.add_argument("url", help="Datenbank-URL der alten Version, z.B. sqlite:///fantasy_old.db")
    s.set_defaults(func=cmd_import_legacy_users)

    s = sub.add_parser("check-rules")
    s.add_argument("key")
    s.set_defaults(func=cmd_check_rules)

    s = sub.add_parser("backup")
    s.add_argument("--season", help="Saison-Key (Standard: aktive Saison)")
    s.add_argument("--out", help="Zieldatei")
    s.set_defaults(func=cmd_backup)

    s = sub.add_parser("restore-backup")
    s.add_argument("file")
    s.set_defaults(func=cmd_restore_backup)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, OSError) as e:
        sys.exit(f"Fehler: {e}")


if __name__ == "__main__":
    main()
