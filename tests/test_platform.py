"""Plattform: Startseite mit Bereichen, Weiterleitung alter Fantasy-Adressen, Admin-Übersicht."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.main import app, legacy_fantasy_url
from app.platform import SECTIONS, section_for_path, tab_active


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def olli(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        yield c


def test_home_shows_sections(client, db, season):
    page = client.get("/").text
    assert "Mönninghausen Games" in page and 'href="/fantasy"' in page
    assert 'href="/darts"' in page and 'href="/beerpong"' in page and "Coming soon" not in page
    assert 'href="/login"' in page


def test_home_shows_fantasy_status(olli, db, season, rules):
    from tests.test_features import _team_form

    assert "Hi olli!" in olli.get("/").text and "No team yet" in olli.get("/").text
    olli.post("/fantasy/my/new", data=_team_form(db, season, rules, "Bulls"))
    assert "You're <strong>#1</strong> of 1" in olli.get("/").text


def test_login_and_register_land_on_home(client, db, make_user, monkeypatch):
    from app.settings import get_settings

    make_user("olli")
    r = client.post("/login", data={"username": "olli", "password": "secret123"}, follow_redirects=False)
    assert r.headers["location"] == "/"
    client.post("/logout")
    monkeypatch.setattr(get_settings(), "invite_code", "darts")
    r = client.post("/register", data={"username": "neu", "password": "secret123", "code": "darts"},
                    follow_redirects=False)
    assert r.headers["location"] == "/"


@pytest.mark.parametrize("old,new", [
    ("/my", "/fantasy/my"), ("/my/new?copy=3", "/fantasy/my/new?copy=3"), ("/bracket?section=2", "/fantasy/bracket?section=2"),
    ("/teams/5", "/fantasy/teams/5"), ("/players", "/fantasy/players"), ("/rules", "/fantasy/rules"),
    ("/admin/rules", "/fantasy/admin/rules"), ("/admin/export/teams", "/fantasy/admin/export/teams"),
])
def test_legacy_urls_redirect(client, db, old, new):
    r = client.get(old, follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == new


def test_legacy_post_keeps_method(client, db):
    r = client.post("/my/new", data={"name": "x"}, follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/fantasy/my/new"


def test_core_urls_are_not_redirected():
    for path in ("/", "/login", "/account", "/admin", "/admin/users", "/admin/invites", "/users/3", "/avatars/3",
                 "/fantasy", "/fantasy/my", "/mystery", "/rulesx"):
        assert legacy_fantasy_url(path) is None, path


def test_admin_home(client, db, make_user):
    make_user("boss", admin=True)
    make_user("olli")
    client.post("/login", data={"username": "olli", "password": "secret123"})
    assert client.get("/admin").status_code == 403
    client.post("/logout")
    client.post("/login", data={"username": "boss", "password": "secret123"})
    page = client.get("/admin").text
    assert 'href="/admin/users"' in page and 'href="/fantasy/admin"' in page
    assert "<span>2</span><small>Members</small>" in page


def test_navigation_per_section(olli, db, season):
    page = olli.get("/fantasy/bracket").text
    assert "<title>Bracket · Fantasy Darts</title>" in page
    assert 'href="/fantasy/my"' in page and 'class="home-link"' in page
    home = olli.get("/").text
    assert "<title>Mönninghausen Games</title>" in home
    assert '<span>Home</span>' in home and '<span>My Teams</span>' not in home


def test_section_helpers():
    fantasy = next(s for s in SECTIONS if s.key == "fantasy")
    assert section_for_path("/fantasy/teams/1") is fantasy
    assert section_for_path("/fantasyx") is None and section_for_path("/account") is None
    assert section_for_path("/darts/games/1").key == "darts"
    assert section_for_path("/beerpong/games/1").key == "beerpong"
    assert section_for_path("/beerpongx") is None
    assert tab_active("/fantasy", "/fantasy", fantasy) and not tab_active("/fantasy", "/fantasy/my", fantasy)
    assert tab_active("/fantasy/my", "/fantasy/my/new", fantasy)
