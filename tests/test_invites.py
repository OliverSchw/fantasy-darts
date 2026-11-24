"""Persönliche Einmal-Einladungslinks."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.main import app


@pytest.fixture
def admin(db, make_user):
    make_user("boss", admin=True)
    with TestClient(app) as c:
        c.post("/login", data={"username": "boss", "password": "secret123"})
        yield c


def _create(admin, db, note="Anna") -> models.Invite:
    assert admin.post("/admin/invites", data={"note": note}, follow_redirects=False).status_code == 303
    return db.scalars(select(models.Invite).order_by(models.Invite.id.desc())).first()


def _register(token, username="anna", password="secret123"):
    with TestClient(app) as guest:
        return guest.post("/register", data={"username": username, "password": password, "invite": token},
                          follow_redirects=False)


def test_link_works_exactly_once(admin, db):
    inv = _create(admin, db)
    page = admin.get("/admin/users").text
    assert 'id="invites"' in page and f"register?invite={inv.token}" in page
    # Abschnitt steht über dem Code-Abschnitt
    assert page.index("Personal invite links") < page.index("Shared invite code")
    assert "1 invite link not used yet" in admin.get("/fantasy/admin").text  # To-do auf der Übersicht

    with TestClient(app) as guest:
        r = guest.get(f"/register?invite={inv.token}")
        assert r.status_code == 200 and 'name="code"' not in r.text  # kein Code-Feld
    # funktioniert auch, wenn der gemeinsame Code aus ist
    assert _register(inv.token).status_code == 303
    db.refresh(inv)
    anna = db.scalar(select(models.User).where(models.User.username == "anna"))
    assert inv.used_at is not None and inv.used_by_id == anna.id

    with TestClient(app) as guest:
        r = guest.get(f"/register?invite={inv.token}")
        assert r.status_code == 410 and "already used" in r.text
    r = _register(inv.token, username="anna2")
    assert r.status_code == 410
    assert db.scalar(select(models.User).where(models.User.username == "anna2")) is None

    page = admin.get("/admin/users").text
    assert f"register?invite={inv.token}" not in page  # nicht mehr unter "Open"
    assert "Anna → <strong>anna</strong>" in page
    assert "invited as “Anna”" in page  # Hinweis in der Mitgliederliste


def test_errors_keep_link_open(admin, db, make_user):
    make_user("taken")
    inv = _create(admin, db)
    r = _register(inv.token, username="Taken")
    assert r.status_code == 400 and "Username already taken" in r.text
    assert f'name="invite" value="{inv.token}"' in r.text  # Formular behält den Link
    assert _register(inv.token, password="kurz").status_code == 400
    assert _register(inv.token, username="").status_code in (400, 422)
    db.refresh(inv)
    assert inv.used_at is None
    assert _register(inv.token, username="anna").status_code == 303


def test_deleted_or_unknown_link_rejected(admin, db):
    inv = _create(admin, db)
    token, inv_id = inv.token, inv.id
    assert admin.post(f"/admin/invites/{inv_id}/delete", follow_redirects=False).status_code == 303
    db.expire_all()
    assert db.get(models.Invite, inv_id) is None
    for t in (token, "gibtsnicht"):
        with TestClient(app) as guest:
            assert guest.get(f"/register?invite={t}").status_code == 410
        assert _register(t).status_code == 410
    assert db.scalar(select(models.User).where(models.User.username == "anna")) is None


def test_deleting_user_keeps_used_entry(admin, db):
    inv = _create(admin, db)
    _register(inv.token)
    anna = db.scalar(select(models.User).where(models.User.username == "anna"))
    admin.post(f"/admin/users/{anna.id}/delete")
    db.expire_all()
    inv = db.get(models.Invite, inv.id)
    assert inv.used_at is not None and inv.used_by_id is None  # ON DELETE SET NULL
    assert "(deleted user)" in admin.get("/admin/users").text


def test_note_max_length(admin, db):
    admin.post("/admin/invites", data={"note": "x" * 61})
    assert db.scalar(select(models.Invite)) is None


def test_shared_code_still_works(admin, db):
    _create(admin, db)
    admin.post("/admin/invite", data={"action": "set", "code": "bulls26"})
    with TestClient(app) as guest:
        assert 'name="code"' in guest.get("/register?code=bulls26").text
        r = guest.post("/register", data={"username": "neu", "password": "secret123", "code": "bulls26"},
                       follow_redirects=False)
        assert r.status_code == 303
    assert db.scalar(select(models.Invite)).used_at is None  # Code verbraucht keinen Link


def test_non_admin_forbidden(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        assert c.post("/admin/invites", data={"note": "x"}).status_code == 403
        db.add(models.Invite(token="abc", note=""))
        db.commit()
        inv = db.scalar(select(models.Invite))
        assert c.post(f"/admin/invites/{inv.id}/delete").status_code == 403
    db.expire_all()
    assert db.scalar(select(models.Invite).where(models.Invite.note == "x")) is None
    assert db.get(models.Invite, inv.id) is not None


def test_conditional_update_blocks_race(admin, db, monkeypatch):
    """Zwei gleichzeitige Anfragen: beide sehen den Link als offen, nur eine darf ihn einlösen."""
    from datetime import datetime, timezone

    from app.web import account

    inv = _create(admin, db)
    stale = db.get(models.Invite, inv.id)
    monkeypatch.setattr(account, "_open_invite", lambda _db, _t: stale)  # Vorprüfung "zu spät"
    inv.used_at = datetime.now(timezone.utc)  # die andere Anfrage war schneller
    db.commit()
    assert _register(inv.token, username="zweiter").status_code == 410
    assert db.scalar(select(models.User).where(models.User.username == "zweiter")) is None
