"""Pure fixture scoring. Inputs are FPL awarded facts, not event inference."""

RULESET = "classic-2025-2027-v1"
POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
CATEGORIES = (
    "minutes", "goals_scored", "assists", "clean_sheets", "saves",
    "penalties_saved", "penalties_missed", "goals_conceded", "own_goals",
    "yellow_cards", "red_cards", "bonus", "defensive_contribution",
)


def calculate(record, position):
    """Return every category; absent/null/invalid facts remain unknown (None)."""
    if position not in POSITIONS:
        raise ValueError(f"Unknown position: {position}")

    def number(key):
        value = record.get(key)
        return value if type(value) is int and value >= 0 else None

    def scaled(key, weight):
        if weight == 0:
            return 0  # category is inapplicable to this position
        value = number(key)
        return None if value is None else value * weight

    minutes = number("minutes")
    cs = number("clean_sheets")
    saves = number("saves")
    conceded = number("goals_conceded")
    dc = number("defensive_contribution")
    return {
        "minutes": None if minutes is None else (2 if minutes >= 60 else int(minutes > 0)),
        "goals_scored": scaled("goals_scored", {1: 10, 2: 6, 3: 5, 4: 4}[position]),
        "assists": scaled("assists", 3),
        # clean_sheets is the official player eligibility fact, not the team score.
        "clean_sheets": 0 if position == 4 else (
            None if cs is None or minutes is None else
            cs * {1: 4, 2: 4, 3: 1}[position] if minutes >= 60 else 0),
        "saves": 0 if position != 1 else None if saves is None else saves // 3,
        "penalties_saved": scaled("penalties_saved", 5 if position == 1 else 0),
        "penalties_missed": scaled("penalties_missed", -2),
        "goals_conceded": 0 if position > 2 else None if conceded is None else -(conceded // 2),
        "own_goals": scaled("own_goals", -2),
        "yellow_cards": scaled("yellow_cards", -1),
        "red_cards": scaled("red_cards", -3),
        "bonus": scaled("bonus", 1),
        "defensive_contribution": 0 if position == 1 else None if dc is None else
            2 * int(dc >= (10 if position == 2 else 12)),
    }


def total(categories):
    return None if any(v is None for v in categories.values()) else sum(categories.values())


def aggregate(records, expected_fixtures, position):
    """Do not turn a missing fixture into a blank or sum before rounding."""
    ids = [r["fixture"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate fixture observations; select one snapshot revision")
    if set(ids) != set(expected_fixtures):
        return {"state": "missing", "total": None}
    if not ids:
        return {"state": "blank", "total": 0}
    points = [total(calculate(r, position)) for r in records]
    return {"state": "complete" if all(p is not None for p in points) else "missing",
            "total": None if None in points else sum(points)}
