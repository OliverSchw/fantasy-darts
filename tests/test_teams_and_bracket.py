import pytest
from sqlalchemy import select

from app import models
from app.bracket import BracketError, delete_result, save_result
from app.season import season_players
from app.teams import TeamInput, validate_team


def _match(db, season, rnd, slot):
    return db.scalar(select(models.Match).where(
        models.Match.season_id == season.id, models.Match.round == rnd, models.Match.slot == slot))


def _cheap_team(players, rules, n=None):
    """Die günstigsten Spieler -> passt sicher ins Budget."""
    n = n or rules.team.squad_size
    cheap = sorted(players.values(), key=lambda p: p.price)[:n]
    ids = [p.id for p in cheap]
    return TeamInput("Test", ids, ids[-1], ids[0], ids[0])


def test_import_creates_full_bracket(db, season, rules):
    assert len(season_players(db, season)) == 128
    total = db.scalar(select(models.Match.id).where(models.Match.season_id == season.id).order_by(models.Match.id.desc()))
    assert total == 127  # 64+32+16+8+4+2+1


def test_valid_team_has_no_errors(db, season, rules):
    players = season_players(db, season)
    assert validate_team(rules, _cheap_team(players, rules), players) == []


def test_team_rule_violations(db, season, rules):
    players = season_players(db, season)
    expensive = sorted(players.values(), key=lambda p: -p.price)
    ids = [p.id for p in expensive[: rules.team.squad_size]]
    data = TeamInput("", ids, ids[0], ids[0], None)
    errors = " | ".join(validate_team(rules, data, players))
    assert "name" in errors
    assert "Budget exceeded" in errors
    assert "Playmaker may cost at most" in errors
    assert "Underdog may cost at most" in errors
    assert "champion pick" in errors

    short = _cheap_team(players, rules, n=rules.team.squad_size - 1)
    assert any("exactly" in e for e in validate_team(rules, short, players))


def test_result_propagates_and_protects_followups(db, season, rules):
    m0, m1 = _match(db, season, 1, 0), _match(db, season, 1, 1)
    save_result(db, rules, m0, 3, 1, {"s171": 2}, {})
    save_result(db, rules, m1, 0, 3, {}, {})
    r2 = _match(db, season, 2, 0)
    assert (r2.p1_id, r2.p2_id) == (m0.p1_id, m1.p2_id)

    # Ungültiges Ergebnis
    with pytest.raises(BracketError):
        save_result(db, rules, r2, 2, 1, {}, {})

    save_result(db, rules, r2, 3, 2, {}, {})
    # Sieger von m0 ändern, obwohl Folgematch gespielt ist -> verboten
    with pytest.raises(BracketError):
        save_result(db, rules, m0, 1, 3, {}, {})
    # Gleicher Sieger, andere Stats -> erlaubt
    save_result(db, rules, m0, 3, 2, {"s171": 5}, {})
    assert m0.stats_p1 == {"s171": 5}

    with pytest.raises(BracketError):
        delete_result(db, m0)
    delete_result(db, r2)
    delete_result(db, m0)
    assert r2.p1_id is None and m0.winner_id is None


def test_match_needs_both_players(db, season, rules):
    with pytest.raises(BracketError):
        save_result(db, rules, _match(db, season, 2, 0), 3, 0, {}, {})
