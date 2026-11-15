from app.models import Match, Team, TeamPlayer
from app.scoring import player_scores, side_points, team_score


def _match(rnd, p1, p2, s1, s2, st1=None, st2=None):
    return Match(round=rnd, slot=0, p1_id=p1, p2_id=p2, sets_p1=s1, sets_p2=s2,
                 winner_id=p1 if s1 > s2 else p2, stats_p1=st1 or {}, stats_p2=st2 or {})


def test_side_points_win_and_loss(rules):
    # 3-1 Sieg in Runde 1: 3*10 + (3-1)*10 = 50, Verlierer 1*10 = 10
    assert side_points(rules, 1, True, 3, 1, {}) == 50
    assert side_points(rules, 1, False, 1, 3, {}) == 10


def test_stats_and_final_bonus(rules):
    stats = {"s171": 4, "f161": 1, "ninedarter": 1, "unknown": 99}
    # Finale 7-3: 70 + 40 + 100 (Titel) + 4*1 + 5 + 100
    assert side_points(rules, 7, True, 7, 3, stats) == 70 + 40 + 100 + 4 + 5 + 100


def test_player_scores_elimination_and_champion(rules):
    scores = player_scores(rules, [_match(1, 1, 2, 3, 0), _match(7, 1, 3, 7, 6)])
    assert scores[2].eliminated and not scores[1].eliminated
    assert scores[1].is_champion
    assert scores[3].eliminated and not scores[3].is_champion


def test_unplayed_matches_are_ignored(rules):
    m = Match(round=2, slot=0, p1_id=1, p2_id=None, winner_id=None, sets_p1=0, sets_p2=0)
    assert player_scores(rules, [m]) == {}


def test_team_multipliers_and_champion_pick(rules):
    team = Team(playmaker_id=1, underdog_id=1, champion_pick_id=1,
                members=[TeamPlayer(player_id=i) for i in (1, 2)])
    scores = player_scores(rules, [_match(7, 1, 2, 7, 0)])
    sc = team_score(rules, team, scores)
    # Spieler 1: (70 + 70 + 100) * 3 = 720, Spieler 2: 0, Champion-Tipp +50
    assert sc.total == 720 + 50
    assert sc.champion_bonus == 50
    assert sc.lines[0].multiplier == 3
