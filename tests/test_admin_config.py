"""Admin-Oberfläche: Einladungscode, Spieler bearbeiten, Regeln & Punkte."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.bracket import save_result
from app.config_store import season_rules
from app.main import app
from app.season import season_players
from app.teams import TeamInput, save_team


@pytest.fixture
def admin(db, make_user):
    make_user("boss", admin=True)
    with TestClient(app) as c:
        c.post("/login", data={"username": "boss", "password": "secret123"})
        yield c


def _rules_form(c):
    """Aktuelles Formular auslesen, damit Tests nur einzelne Felder ändern."""
    import re
    html = c.get("/fantasy/admin/rules").text
    fields = dict(re.findall(r'name="([a-z_0-9]+)" value="([^"]*)"', html))
    # nicht angekreuzte Checkboxen schickt ein Browser nicht mit
    return {k: v for k, v in fields.items() if not k.startswith("stat_delete_")}


def test_admin_subpages_render(admin):
    for url in ("/admin", "/fantasy/admin", "/admin/users", "/fantasy/admin/players", "/fantasy/admin/players/new", "/fantasy/admin/rules"):
        assert admin.get(url).status_code == 200, url


def test_invite_code_lifecycle(admin, db):
    assert "register?code=" not in admin.get("/admin/users").text
    admin.post("/admin/invite", data={"action": "set", "code": "bulls26"})
    assert "register?code=bulls26" in admin.get("/admin/users").text

    with TestClient(app) as guest:
        assert guest.get("/register").status_code == 200
        r = guest.post("/register", data={"username": "neu", "password": "secret123", "code": "bulls26"},
                       follow_redirects=False)
        assert r.status_code == 303

    admin.post("/admin/invite", data={"action": "generate"})
    assert "bulls26" not in admin.get("/admin/users").text  # alter Code ungültig
    admin.post("/admin/invite", data={"action": "disable"})
    with TestClient(app) as guest:
        assert guest.get("/register").status_code == 404


def test_edit_player_and_price_freeze(admin, db, season):
    p = sorted(season_players(db, season).values(), key=lambda x: x.price)[0]
    r = admin.post(f"/fantasy/admin/players/{p.id}", data={"name": "Neuer Name", "nation": "Germany", "price": "3,5", "seed": ""},
                   follow_redirects=False)
    assert r.status_code == 303
    db.refresh(p)
    assert (p.name, p.nation, p.price, p.seed) == ("Neuer Name", "Germany", 3.5, None)

    # Doppelter Name
    other = next(x for x in season_players(db, season).values() if x.id != p.id)
    assert admin.post(f"/fantasy/admin/players/{p.id}", data={"name": other.name, "price": "3.5"}).status_code == 400

    season.teams_locked = True
    db.commit()
    r = admin.post(f"/fantasy/admin/players/{p.id}", data={"name": "Neuer Name", "nation": "Germany", "price": "9"})
    assert r.status_code == 400 and "Prices can" in r.text
    # Name ändern geht trotz Sperre
    assert admin.post(f"/fantasy/admin/players/{p.id}", data={"name": "Name 2", "nation": "", "price": "3.5"},
                      follow_redirects=False).status_code == 303


def test_create_and_replace_in_draw(admin, db, season):
    assert admin.post("/fantasy/admin/players/new", data={"name": "Nachrücker", "nation": "Austria", "price": "4"},
                      follow_redirects=False).status_code == 303
    new = db.scalar(select(models.Player).where(models.Player.name == "Nachrücker"))
    m = db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.slot == 5))
    old = m.p2_id
    admin.post(f"/fantasy/admin/players/{old}/replace", data={"replacement_id": new.id})
    db.refresh(m)
    assert m.p2_id == new.id

    # Bereits gespieltes Match: kein Ersetzen mehr
    m0 = db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.slot == 0))
    save_result(db, season_rules(db, season), m0, 3, 0, {}, {})
    admin.post(f"/fantasy/admin/players/{m0.p2_id}/replace", data={"replacement_id": old})
    db.refresh(m0)
    assert m0.p2_id != old


def test_change_points_in_admin(admin, db, season, make_user):
    m = db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.slot == 0))
    save_result(db, season_rules(db, season), m, 3, 1, {"s171": 2}, {})
    page = admin.get(f"/fantasy/players/{m.p1_id}").text
    assert "+52" in page  # 30 + 20 + 2

    form = _rules_form(admin)
    form.update({"per_set_won": "20", "stat_points_0": "5", "new_stat_label": "180s", "new_stat_points": "2"})
    assert admin.post("/fantasy/admin/rules", data=form, follow_redirects=False).status_code == 303
    rules = season_rules(db, season)
    assert rules.scoring.per_set_won == 20
    assert rules.scoring.stats[-1].label == "180s" and rules.scoring.stats[-1].key == "s180s"
    assert "+90" in admin.get(f"/fantasy/players/{m.p1_id}").text  # 60 + 20 + 2*5
    assert "180s" in admin.get(f"/fantasy/bracket/match/{m.id}").text  # neue Stat im Ergebnis-Formular

    # Ungültige Eingabe -> Fehler, nichts gespeichert
    bad = {**form, "sets_to_win_0": "0"}
    assert admin.post("/fantasy/admin/rules", data=bad).status_code == 400
    assert season_rules(db, season).tournament.sets_to_win[0] == 3

    # Zurücksetzen
    admin.post("/fantasy/admin/rules/reset")
    assert season_rules(db, season).scoring.per_set_won == 10


def test_rules_read_only_when_locked_and_invalid_team_warning(admin, db, season, make_user):
    u = make_user("olli")
    ids = [p.id for p in sorted(season_players(db, season).values(), key=lambda p: p.price)[:15]]
    save_team(db, models.Team(season_id=season.id, user_id=u.id), TeamInput("Bulls", ids, ids[-1], ids[0], ids[0]))

    form = _rules_form(admin)
    r = admin.post("/fantasy/admin/rules", data={**form, "squad_size": "16"})
    assert "no longer fit the new rules" in r.text and "Bulls" in r.text

    season.teams_locked = True
    db.commit()
    admin.post("/fantasy/admin/rules", data={**form, "squad_size": "12"})
    assert season_rules(db, season).team.squad_size == 16  # unverändert
    assert "read-only" in admin.get("/fantasy/admin/rules").text


def test_non_admin_blocked(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        for url in ("/fantasy/admin/rules", "/fantasy/admin/players", "/admin/users"):
            assert c.get(url).status_code == 403
        assert c.post("/fantasy/admin/rules", data={}).status_code == 403
        assert c.post("/admin/invite", data={"action": "generate"}).status_code == 403


def test_overview_todo(admin, db, season, make_user):
    from datetime import datetime, timedelta, timezone

    make_user("ohne_team")
    page = admin.get("/fantasy/admin").text
    assert "members without a team" in page and "ohne_team" in page
    assert "waiting for a result" not in page  # nichts angesetzt -> nichts überfällig

    m = db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.slot == 0))
    m.scheduled_at = datetime.now(timezone.utc) - timedelta(hours=1)
    later = db.scalar(select(models.Match).where(models.Match.round == 1, models.Match.slot == 1))
    later.scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)
    db.commit()
    assert "1 match waiting for a result" in admin.get("/fantasy/admin").text

    season.teams_locked = True
    db.commit()
    page = admin.get("/fantasy/admin").text
    assert "Teams are <strong>locked</strong>" in page and "members without a team" not in page


def test_account_shows_admin_button(admin, db, make_user):
    assert 'href="/admin" role="button"' in admin.get("/account").text
    make_user("normal")
    with TestClient(app) as c:
        c.post("/login", data={"username": "normal", "password": "secret123"})
        assert 'href="/admin" role="button"' not in c.get("/account").text


def test_sortable_tables_markup(admin, db, season):
    page = admin.get("/fantasy/players").text
    assert 'class="striped compact rowlinks sortable"' in page and "/static/sortable.js" in page
    assert 'data-sort="num" data-default="desc">Points' in page and "Still in only" in page
    assert page.count('data-alive="1"') > 0
    page = admin.get("/fantasy/admin/players").text
    assert "sortable" in page and 'data-first="asc"' in page
    assert admin.get("/static/sortable.js").status_code == 200
