"""Öffentliche Seiten: Ranking, Team- und Spieler-Details, Turnierbaum, Insights, Regeln."""

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import models
from ..auth import require_user
from ..darts.service import competitor_for_user
from ..darts.stats import compute_stats
from ..scoring import side_breakdown
from ..teams import user_teams
from .common import State, get_state, render

router = APIRouter()


@router.get("/fantasy")
def leaderboard(request: Request, state: State = Depends(get_state)):
    return render(request, "leaderboard.html", state, rows=state.leaderboard(), latest=state.latest_results())


@router.get("/fantasy/teams/{team_id}")
def team_detail(team_id: int, request: Request, state: State = Depends(get_state)):
    team = state.db.get(models.Team, team_id)
    if team is None or team.season_id != state.season.id:
        raise HTTPException(404)
    if not state.can_view_team(team):
        return render(request, "message.html", state, status_code=403,
                      title="Not visible yet", text="Other teams become visible once teams are locked.")
    score = state.team_score(team)
    is_mine = state.user is not None and team.user_id == state.user.id
    overlap = set() if is_mine else state.my_player_ids & set(team.player_ids)
    n_alive = sum(1 for pid in team.player_ids if not state.score(pid).eliminated)
    return render(request, "team_detail.html", state, team=team, score=score, overlap=overlap, n_alive=n_alive)


@router.get("/users/{user_id}")
def user_profile(user_id: int, request: Request, state: State = Depends(get_state),
                 viewer: models.User = Depends(require_user)):
    """Profil eines Mitspielers: großes Bild, aktives Team mit Platz. Nur für eingeloggte User (wegen Fotos)."""
    person = state.db.get(models.User, user_id)
    if person is None:
        raise HTTPException(404)
    row = next((r for r in state.leaderboard() if r["team"].user_id == person.id), None)
    darts_me = competitor_for_user(state.db, person)
    return render(request, "user_profile.html", state, person=person, row=row,
                  n_ranked=len(state.active_teams), darts_me=darts_me,
                  darts_stats=compute_stats(state.db, [darts_me.id]).get(darts_me.id))


def _pick_counts(state: State) -> tuple[Counter, Counter, Counter, Counter]:
    squads, pms, uds, champs = Counter(), Counter(), Counter(), Counter()
    for t in state.active_teams:
        squads.update(t.player_ids)
        pms[t.playmaker_id] += 1
        uds[t.underdog_id] += 1
        champs[t.champion_pick_id] += 1
    return squads, pms, uds, champs


@router.get("/fantasy/players")
def players(request: Request, state: State = Depends(get_state)):
    picks = _pick_counts(state)[0] if state.locked else Counter()
    rows = sorted(state.players.values(), key=lambda p: (-state.score(p.id).points, -p.price))
    return render(request, "players.html", state, rows=rows, picks=picks, n_teams=len(state.active_teams))


@router.get("/fantasy/players/{player_id}")
def player_detail(player_id: int, request: Request, state: State = Depends(get_state)):
    p = state.players.get(player_id)
    if p is None:
        raise HTTPException(404)
    history = []
    totals = {"won": 0, "lost": 0, "sets_for": 0, "sets_against": 0,
              "stats": {s.key: 0 for s in state.rules.scoring.stats}}
    for m in state.matches:
        if not m.is_played or player_id not in (m.p1_id, m.p2_id):
            continue
        first = m.p1_id == player_id
        won = m.winner_id == player_id
        sets_for, sets_against = (m.sets_p1, m.sets_p2) if first else (m.sets_p2, m.sets_p1)
        stats = (m.stats_p1 if first else m.stats_p2) or {}
        parts = side_breakdown(state.rules, m.round, won, sets_for, sets_against, stats)
        history.append({
            "match": m, "won": won, "opponent": m.p2_id if first else m.p1_id,
            "score": f"{sets_for}–{sets_against}", "parts": parts, "points": sum(v for _, v in parts),
        })
        totals["won" if won else "lost"] += 1
        totals["sets_for"] += sets_for
        totals["sets_against"] += sets_against
        for key in totals["stats"]:
            totals["stats"][key] += int(stats.get(key, 0) or 0)

    # Welche Teams haben ihn? Nach dem Sperren alle aktiven, vorher nur die eigenen.
    if state.locked:
        pool = state.active_teams
    elif state.user is not None:
        pool = user_teams(state.db, state.season.id, state.user.id)
    else:
        pool = []
    teams = sorted((t for t in pool if player_id in t.player_ids or player_id == t.champion_pick_id),
                   key=lambda t: t.name.lower())
    squad_share = None
    if state.locked and state.active_teams:
        in_squad = sum(1 for t in state.active_teams if player_id in t.player_ids)
        squad_share = round(100 * in_squad / len(state.active_teams))
    return render(request, "player_detail.html", state, p=p, history=history, teams=teams, totals=totals,
                  squad_share=squad_share,
                  status=state.status(player_id), section=state.bracket.section_of(player_id))


# ------------------------------------------------------------ Team-Vergleich


def _comparable_teams(state: State) -> list[models.Team]:
    """Teams, die der User vergleichen darf: nach dem Sperren alle aktiven (+ eigene), vorher nur eigene."""
    own = user_teams(state.db, state.season.id, state.user.id) if state.user else []
    teams = {t.id: t for t in own}
    if state.locked or (state.user and state.user.is_admin):
        teams.update({t.id: t for t in state.active_teams})
    return sorted(teams.values(), key=lambda t: t.name.lower())


@router.get("/fantasy/compare")
def compare(request: Request, state: State = Depends(get_state), a: int | None = None, b: int | None = None):
    options = _comparable_teams(state)
    if len(options) < 2:
        text = ("Build a second team to compare your own teams." if not state.locked
                else "There are not enough teams to compare yet.")
        if state.user is None and not state.locked:
            text = "Teams can be compared once they are locked."
        return render(request, "message.html", state, title="Compare teams", text=text)
    by_id = {t.id: t for t in options}
    if (a is not None and a not in by_id) or (b is not None and b not in by_id):
        raise HTTPException(404)

    if a is None:
        a = state.my_team.id if state.my_team and state.my_team.id in by_id else options[0].id
    if b is None or b == a:
        ranked = [r["team"].id for r in state.leaderboard() if r["team"].id in by_id and r["team"].id != a]
        b = ranked[0] if ranked else next(t.id for t in options if t.id != a)
    ta, tb = by_id[a], by_id[b]
    sa, sb = state.team_score(ta), state.team_score(tb)
    la = {line.player_id: line for line in sa.lines}
    lb = {line.player_id: line for line in sb.lines}

    shared = sorted(la.keys() & lb.keys(), key=lambda pid: -max(la[pid].points, lb[pid].points))
    only_a = [la[pid] for pid in la if pid not in lb]  # schon nach Punkten sortiert
    only_b = [lb[pid] for pid in lb if pid not in la]
    summary = {
        "shared_a": sum(la[pid].points for pid in shared),
        "shared_b": sum(lb[pid].points for pid in shared),
        "only_a": sum(line.points for line in only_a),
        "only_b": sum(line.points for line in only_b),
    }
    alive = {t.id: sum(1 for pid in t.player_ids if not state.score(pid).eliminated) for t in (ta, tb)}
    return render(request, "compare.html", state, options=options, ta=ta, tb=tb, sa=sa, sb=sb,
                  la=la, lb=lb, shared=shared, only_a=only_a, only_b=only_b, summary=summary, alive=alive)


@router.get("/fantasy/bracket")
def bracket(request: Request, state: State = Depends(get_state), view: str = "tree",
            section: str | None = None, round: int | None = None):
    played = Counter(m.round for m in state.matches if m.is_played)
    if view == "list":
        n = state.rules.tournament.num_rounds
        rnd = round if round and 1 <= round <= n else next((m.round for m in state.matches if not m.is_played), n)
        matches = [state.bracket.view(m) for m in state.matches if m.round == rnd]
        return render(request, "bracket_list.html", state, rnd=rnd, matches=matches, played=played)

    sections = state.bracket.sections()
    keys = [s.key for s in sections]
    if section not in keys:
        split_done = played[state.bracket.split_round] == state.rules.matches_in_round(state.bracket.split_round)
        section = "finals" if split_done else keys[0]
    current = sections[keys.index(section)]
    mine_by_section = Counter(
        state.bracket.section_of(pid) for pid in state.my_player_ids if state.status(pid).state == "alive"
    )
    return render(request, "bracket_tree.html", state, sections=sections, current=current, played=played,
                  mine_by_section=mine_by_section)


@router.get("/fantasy/insights")
def insights(request: Request, state: State = Depends(get_state)):
    if not state.locked and not (state.user and state.user.is_admin):
        return render(request, "message.html", state, status_code=403, title="Insights",
                      text="Insights about everyone's picks are shown once teams are locked.")
    squads, pms, uds, champs = _pick_counts(state)
    n_teams = len(state.active_teams)
    scored = [p for p in state.players.values() if state.score(p.id).points > 0]
    value = sorted(scored, key=lambda p: -state.score(p.id).points / max(p.price, 0.1))[:10]
    top = sorted(scored, key=lambda p: -state.score(p.id).points)[:10]
    teams_alive = sorted(
        ((t, sum(1 for pid in t.player_ids if not state.score(pid).eliminated)) for t in state.active_teams),
        key=lambda x: -x[1],
    )[:5]
    return render(request, "insights.html", state, n_teams=n_teams,
                  champs=champs.most_common(), squads=squads.most_common(10),
                  pms=pms.most_common(5), uds=uds.most_common(5),
                  value=value, top=top, teams_alive=teams_alive,
                  never=sorted((p for p in state.players.values() if p.id not in squads),
                               key=lambda p: -state.score(p.id).points)[:5])


@router.get("/fantasy/rules")
def rules_page(request: Request, state: State = Depends(get_state)):
    return render(request, "rules.html", state)


@router.get("/fantasy/schedule")
def schedule(request: Request, state: State = Depends(get_state), mine: bool = False):
    days = state.schedule_by_day()
    if mine and state.my_player_ids:
        bracket = state.bracket

        def involves_mine(m: models.Match) -> bool:
            sides = (bracket.side(m, 0), bracket.side(m, 1))
            ids = {s.pid for s in sides if s.pid} | {c for s in sides for c in s.candidates}
            return bool(ids & state.my_player_ids)

        days = [(d, [m for m in ms if involves_mine(m)]) for d, ms in days]
        days = [(d, ms) for d, ms in days if ms]
    unscheduled = sum(1 for m in state.matches if not m.scheduled_at and not m.is_played)
    return render(request, "schedule.html", state, days=days, mine=mine, unscheduled=unscheduled)


@router.get("/fantasy/matches/{match_id}")
def match_detail(match_id: int, request: Request, state: State = Depends(get_state)):
    m = state.db.get(models.Match, match_id)
    if m is None or m.season_id != state.season.id:
        raise HTTPException(404)
    br = state.bracket
    m = br.by_pos[(m.round, m.slot)]  # gleiche Instanz wie im Baum
    picks = _pick_counts(state)[0] if state.locked else Counter()
    sides = []
    for idx in (0, 1):
        side = br.side(m, idx)
        info = {"side": side, "feeder": br.feeder(m, idx), "path": [], "parts": [], "points": 0, "stats": {}}
        if side.pid is not None:
            info["path"] = br.path(side.pid, m.round)
            if m.is_played:
                first = idx == 0
                sets_for, sets_against = (m.sets_p1, m.sets_p2) if first else (m.sets_p2, m.sets_p1)
                info["stats"] = (m.stats_p1 if first else m.stats_p2) or {}
                info["parts"] = side_breakdown(state.rules, m.round, m.winner_id == side.pid,
                                               sets_for, sets_against, info["stats"])
                info["points"] = sum(v for _, v in info["parts"])
            info["picked"] = picks[side.pid]
            info["mine"] = side.pid in state.my_player_ids
        sides.append(info)
    nxt = br.next_match(m)
    nxt_other = None
    if nxt is not None:
        nxt_other = br.side(nxt, 1 if m.slot % 2 == 0 else 0)
    return render(request, "match_detail.html", state, m=m, sides=sides, nxt=nxt, nxt_other=nxt_other,
                  n_teams=len(state.active_teams), section=br.section_of_match(m))
