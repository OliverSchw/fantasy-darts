"""Profilbilder hochladen, anzeigen, löschen."""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app import models
from app.main import app


def _png(w=800, h=600, color=(200, 30, 30), mode="RGB") -> bytes:
    out = BytesIO()
    Image.new(mode, (w, h), color).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def olli(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        yield c


def _user(db, name="olli") -> models.User:
    db.expire_all()
    return db.scalar(select(models.User).where(models.User.username == name))


def _upload(c, data, name="foto.png"):
    return c.post("/account/avatar", files={"image": (name, data, "image/png")}, follow_redirects=False)


def test_upload_resizes_and_serves(olli, db):
    assert _upload(olli, _png()).status_code == 303
    u = _user(db)
    assert u.avatar_version
    r = olli.get(f"/avatars/{u.id}?v={u.avatar_version}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert r.headers["x-content-type-options"] == "nosniff"
    img = Image.open(BytesIO(r.content))
    assert img.format == "WEBP" and img.size == (512, 512)
    page = olli.get("/account").text
    assert f'/avatars/{u.id}?v={u.avatar_version}' in page and "Remove picture" in page


def test_transparent_png_and_new_version(olli, db):
    _upload(olli, _png(300, 300, (0, 0, 0, 0), mode="RGBA"))
    first = _user(db).avatar_version
    _upload(olli, _png(300, 300))
    assert _user(db).avatar_version > first  # neue URL -> kein veraltetes Bild aus dem Cache


def test_invalid_files_rejected(olli, db):
    r = _upload(olli, b"kein bild", "virus.png")
    assert r.status_code == 303
    assert "not a supported image" in olli.get("/account").text
    assert _upload(olli, b"x" * (5 * 1024 * 1024 + 10)).status_code == 303
    assert "too large" in olli.get("/account").text
    assert _user(db).avatar_version is None
    assert db.scalar(select(models.Avatar)) is None


def test_delete_avatar(olli, db):
    _upload(olli, _png())
    uid = _user(db).id
    assert olli.post("/account/avatar/delete", follow_redirects=False).status_code == 303
    assert _user(db).avatar_version is None
    assert olli.get(f"/avatars/{uid}").status_code == 404


def test_only_logged_in_users_see_pictures(olli, db, season, rules):
    _upload(olli, _png())
    u = _user(db)
    with TestClient(app) as guest:
        assert guest.get(f"/avatars/{u.id}", follow_redirects=False).status_code == 303  # -> Login
    # Macro: Foto nur für eingeloggte Betrachter, sonst Initialen
    from app.web.common import templates
    macro = templates.env.get_template("_macros.html").module.avatar
    assert "<img" in str(macro(u, u)) and "<img" not in str(macro(u, None))
    assert ">O<" in str(macro(u, None))


def test_admin_can_remove_picture_and_user_delete_cascades(olli, db, make_user):
    _upload(olli, _png())
    uid = _user(db).id
    make_user("boss", admin=True)
    with TestClient(app) as admin:
        admin.post("/login", data={"username": "boss", "password": "secret123"})
        assert "Remove picture" in admin.get("/admin/users").text
        assert olli.post(f"/admin/users/{uid}/avatar/delete").status_code == 403  # nur Admins
        assert admin.post(f"/admin/users/{uid}/avatar/delete", follow_redirects=False).status_code == 303
        assert _user(db).avatar_version is None

        _upload(olli, _png())
        admin.post(f"/admin/users/{uid}/delete")
    db.expire_all()
    assert db.get(models.Avatar, uid) is None  # Bild wird mit dem User gelöscht


def test_user_profile_page(olli, db, season, rules, make_user):
    from tests.test_features import _team_form

    anna = make_user("anna")
    olli.post("/my/new", data=_team_form(db, season, rules, "Bulls"))
    _upload(olli, _png())
    me = _user(db)

    with TestClient(app) as c:
        c.post("/login", data={"username": "anna", "password": "secret123"})
        page = c.get(f"/users/{me.id}").text
        assert f"/avatars/{me.id}?v={me.avatar_version}" in page and 'class="avatar xl"' in page
        assert "Bulls" in page and "visible once teams are locked" in page  # Team vor der Sperre nicht verlinkt
        assert f'href="/users/{me.id}"' in c.get("/").text  # Rangliste verlinkt aufs Profil
        assert "has no active team yet" in c.get(f"/users/{anna.id}").text
        assert c.get("/users/9999").status_code == 404

    season.teams_locked = True
    db.commit()
    with TestClient(app) as c:
        c.post("/login", data={"username": "anna", "password": "secret123"})
        assert '/teams/' in c.get(f"/users/{me.id}").text  # nach der Sperre verlinkt
    assert "Change picture or password" in olli.get(f"/users/{me.id}").text  # eigenes Profil

    with TestClient(app) as guest:
        assert guest.get(f"/users/{me.id}", follow_redirects=False).status_code == 303  # -> Login
        assert f'href="/users/{me.id}"' not in guest.get("/").text
