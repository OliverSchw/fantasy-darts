"""Punkteberechnung - reine Funktionen ohne Datenbank, komplett durch rules.toml gesteuert."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from .models import Match, Team
from .rules import Rules


@dataclass
class PlayerScore:
    points: float = 0
    eliminated: bool = False
    is_champion: bool = False
    matches_played: int = 0


@dataclass
class TeamLine:
    player_id: int
    base_points: float
    multiplier: float
    points: float


@dataclass
class TeamScore:
    total: float
    lines: list[TeamLine] = field(default_factory=list)
    champion_bonus: float = 0


def side_breakdown(
    rules: Rules, round_no: int, won: bool, sets_for: int, sets_against: int, stats: dict
) -> list[tuple[str, float]]:
    """Punkte für EINEN Spieler aus EINEM Match, aufgeschlüsselt als [(Beschreibung, Punkte)]."""
    sc = rules.scoring
    parts: list[tuple[str, float]] = []
    if sets_for and sc.per_set_won:
        parts.append((f"{sets_for} set{'s' if sets_for != 1 else ''} won", sets_for * sc.per_set_won))
    if won:
        margin = sets_for - sets_against
        if margin and sc.per_set_margin_winner:
            parts.append((f"win margin +{margin}", margin * sc.per_set_margin_winner))
        if bonus := rules.round_bonus(round_no):
            parts.append((f"{rules.tournament.round_names[round_no - 1]} won", bonus))
    for stat in sc.stats:
        n = int(stats.get(stat.key, 0) or 0)
        if n and stat.points:
            parts.append((f"{n}× {stat.label}", n * stat.points))
    return parts


def side_points(rules: Rules, round_no: int, won: bool, sets_for: int, sets_against: int, stats: dict) -> float:
    """Punkte für EINEN Spieler aus EINEM Match."""
    return sum(p for _, p in side_breakdown(rules, round_no, won, sets_for, sets_against, stats))


def player_scores(rules: Rules, matches: Iterable[Match]) -> dict[int, PlayerScore]:
    scores: dict[int, PlayerScore] = {}
    final_round = rules.tournament.num_rounds
    for m in matches:
        if not m.is_played or m.p1_id is None or m.p2_id is None:
            continue
        for pid, sets_for, sets_against, stats in (
            (m.p1_id, m.sets_p1, m.sets_p2, m.stats_p1 or {}),
            (m.p2_id, m.sets_p2, m.sets_p1, m.stats_p2 or {}),
        ):
            won = m.winner_id == pid
            s = scores.setdefault(pid, PlayerScore())
            s.points += side_points(rules, m.round, won, sets_for, sets_against, stats)
            s.matches_played += 1
            if not won:
                s.eliminated = True
            elif m.round == final_round:
                s.is_champion = True
    return scores


def multiplier(rules: Rules, team: Team, player_id: int) -> float:
    """Playmaker- und Underdog-Bonus addieren sich (2 + 2 -> x3)."""
    mult = 1.0
    if player_id == team.playmaker_id:
        mult += rules.team.playmaker.multiplier - 1
    if player_id == team.underdog_id:
        mult += rules.team.underdog.multiplier - 1
    return mult


def champion_id(scores: dict[int, PlayerScore]) -> int | None:
    return next((pid for pid, s in scores.items() if s.is_champion), None)


def team_score(rules: Rules, team: Team, scores: dict[int, PlayerScore]) -> TeamScore:
    lines = []
    for pid in team.player_ids:
        base = scores[pid].points if pid in scores else 0
        mult = multiplier(rules, team, pid)
        lines.append(TeamLine(pid, base, mult, base * mult))
    bonus = rules.team.champion_pick.bonus if champion_id(scores) == team.champion_pick_id else 0
    total = sum(line.points for line in lines) + bonus
    lines.sort(key=lambda line: line.points, reverse=True)
    return TeamScore(total=total, lines=lines, champion_bonus=bonus)
