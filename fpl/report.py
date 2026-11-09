"""Offline reconciliation and deterministic Markdown output."""

from collections import Counter

from .scoring import CATEGORIES, POSITIONS, RULESET, aggregate, calculate, total


# Saved bootstrap weights for this ruleset. Minute cutoffs, rounding divisors
# and defensive action thresholds are verified separately by scoring tests.
SCORING_WEIGHTS = {
    "long_play": 2,
    "short_play": 1,
    "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "assists": 3,
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "saves": 1,
    "penalties_saved": 5,
    "penalties_missed": -2,
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
    "own_goals": -2,
    "yellow_cards": -1,
    "red_cards": -3,
    "bonus": 1,
    "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
}


def validate_scoring(bootstrap):
    config = bootstrap.get("game_config")
    scoring = config.get("scoring") if isinstance(config, dict) else None
    if not isinstance(scoring, dict):
        raise ValueError("Missing or invalid game_config.scoring")
    for key, expected in SCORING_WEIGHTS.items():
        actual = scoring.get(key)
        if isinstance(expected, dict) and isinstance(actual, dict):
            matches = actual == expected and all(type(value) is int for value in actual.values())
        else:
            matches = type(actual) is int and actual == expected
        if not matches:
            raise ValueError(f"Scoring configuration {key}: expected {expected}, got {actual}")


def reconcile(snapshot):
    if snapshot["schema_version"] != 1:
        raise ValueError("Unsupported snapshot schema")
    if snapshot["season"] not in ("2025/26", "2026/27"):
        raise ValueError("Season needs scoring-rule review before calculation")
    obs = snapshot["observations"]
    bootstrap = obs["bootstrap-static/"]["payload"]
    validate_scoring(bootstrap)
    players = {p["id"]: p for p in bootstrap["elements"]}
    events = {e["id"]: e for e in bootstrap["events"]}
    results, weeks, issues = [], [], []
    if (len(snapshot["players"]) != 4 or len(set(snapshot["players"])) != 4
            or len(snapshot["gameweeks"]) != 2 or len(set(snapshot["gameweeks"])) != 2):
        raise ValueError("Snapshot must select four players and two gameweeks")
    if {players[p]["element_type"] for p in snapshot["players"]} != {1, 2, 3, 4}:
        raise ValueError("Snapshot must cover all four positions")
    for gw in sorted(snapshot["gameweeks"]):
        event = events[gw]
        if event.get("finished") is not True or event.get("data_checked") is not True:
            issues.append(f"GW{gw}: event is not finished/data_checked")
        overrides = event.get("overrides") or {}
        if overrides.get("scoring") or overrides.get("rules") or overrides.get("element_types"):
            raise ValueError(f"GW{gw}: scoring overrides require review")
        fixtures = obs[f"fixtures/?event={gw}"]["payload"]
        fixture_map = {f["id"]: f for f in fixtures}
        if len(fixture_map) != len(fixtures):
            raise ValueError(f"GW{gw}: duplicate fixture IDs")
        live_elements = obs[f"event/{gw}/live/"]["payload"]["elements"]
        live_map = {p["id"]: p for p in live_elements}
        for pid in sorted(snapshot["players"]):
            player = players[pid]
            position = player["element_type"]
            history = obs[f"element-summary/{pid}/"]["payload"]["history"]
            records = [r for r in history if r["round"] == gw]
            # Include history IDs as well as current-team schedule so missing fixture
            # metadata cannot masquerade as a blank. Transfers are a documented gap.
            expected = {f["id"] for f in fixtures if player["team"] in (f["team_h"], f["team_a"])}
            observed = {r["fixture"] for r in records}
            expected.update(observed)
            live = live_map.get(pid)
            explanations = live.get("explain") if live else None
            explanation_map = {}
            if isinstance(explanations, list):
                for explanation in explanations:
                    fid = explanation["fixture"]
                    if fid in explanation_map:
                        issues.append(f"Player {pid} GW{gw}: duplicate fixture explanation {fid}")
                    explanation_map[fid] = explanation
            if set(explanation_map) - expected:
                issues.append(f"Player {pid} GW{gw}: unexpected explanation fixture IDs")
            expected.update(explanation_map)
            summary = aggregate(records, expected, position)
            for record in sorted(records, key=lambda r: r["fixture"]):
                fid = record["fixture"]
                label = f"Player {pid} GW{gw} fixture {fid}"
                local = []
                fixture = fixture_map.get(fid)
                if not fixture or fixture.get("event") != gw or fixture.get("finished") is not True:
                    local.append("missing, wrong-event or unfinished fixture metadata")
                if record.get("element") != pid:
                    local.append("history player ID mismatch")
                calculated = calculate(record, position)
                explanation = explanation_map.get(fid)
                official = {k: 0 for k in CATEGORIES}
                stats = explanation.get("stats") if explanation else None
                if not isinstance(stats, list):
                    official = {k: None for k in CATEGORIES}
                    local.append("missing official explanation")
                else:
                    seen = set()
                    for stat in stats:
                        key = stat["identifier"]
                        if key in seen:
                            local.append(f"duplicate explanation category {key}")
                        seen.add(key)
                        points = stat.get("points")
                        official[key] = points if type(points) is int else None
                        if key not in CATEGORIES:
                            local.append(f"unhandled explanation category {key}")
                        if stat.get("value") != record.get(key):
                            local.append(f"{key} fact differs: history={record.get(key)} explanation={stat.get('value')}")
                        if stat.get("points_modification") not in (None, 0):
                            local.append(f"{key} official points_modification={stat['points_modification']}")
                for key in sorted(set(calculated) | set(official)):
                    a, b = calculated.get(key), official.get(key)
                    if a is None or b is None:
                        local.append(f"{key}: missing/invalid data (calculated={a}, official={b})")
                    elif a != b:
                        local.append(f"{key}: calculated {a}, official {b}")
                calc_total, explain_total = total(calculated), total(official)
                history_total = record.get("total_points")
                if type(history_total) is not int or calc_total != history_total or explain_total != history_total:
                    local.append(f"totals differ or missing: calculation={calc_total}, history={history_total}, explanation={explain_total}")
                results.append({"player": pid, "name": player["web_name"], "position": POSITIONS[position],
                                "gameweek": gw, "fixture": fid, "minutes": record.get("minutes"),
                                "value": record.get("value"), "calculated": calculated, "official": official,
                                "total": calc_total, "history_total": history_total, "explanation_total": explain_total,
                                "finished": fixture.get("finished") if fixture else None,
                                "finished_provisional": fixture.get("finished_provisional") if fixture else None,
                                "issues": local})
                issues.extend(f"{label}: {issue}" for issue in local)
            live_stats = live.get("stats") if live else None
            official_gw = live_stats.get("total_points") if isinstance(live_stats, dict) else None
            history_points = [r.get("total_points") for r in records]
            history_gw = None
            if observed == expected and all(type(p) is int for p in history_points):
                history_gw = sum(history_points)
            week = {"player": pid, "name": player["web_name"], "gameweek": gw,
                    "fixtures": sorted(expected), **summary, "history_total": history_gw,
                    "official_total": official_gw, "finished": event.get("finished"),
                    "data_checked": event.get("data_checked")}
            weeks.append(week)
            if summary["state"] == "missing" or type(official_gw) is not int or summary["total"] != official_gw or history_gw != official_gw:
                issues.append(f"Player {pid} GW{gw}: missing data or GW mismatch: calculated={summary['total']}, history={history_gw}, live={official_gw}")
            if expected - observed:
                issues.append(f"Player {pid} GW{gw}: missing history for fixtures {sorted(expected - observed)}")
    return {"ruleset": RULESET, "season": snapshot["season"], "fixtures": results,
            "gameweeks": weeks, "issues": issues}


def display(value):
    return "MISSING" if value is None else str(value)


def markdown(snapshot, result):
    lines = ["# Official FPL validation", "", f"Season: {result['season']} | rules: {RULESET}",
             "Season identity: " + snapshot["season_identity_basis"]["note"],
             "", "## Source observations (UTC)", ""]
    for key, observation in sorted(snapshot["observations"].items()):
        lines.append(f"- {observation['fetched_at']} — {observation['url']}")
    lines += ["", "## Fixture totals", "", "All calculated categories and their zero values are retained in results.json.", "",
              "Player (ID/position) | GW | Fixture | Min | Value (0.1m) | Calc | History | Explain | Delta | Finished/provisional",
              "---|---:|---:|---:|---:|---:|---:|---:|---:|---"]
    for row in result["fixtures"]:
        delta = row["total"] - row["history_total"] if type(row["total"]) is int and type(row["history_total"]) is int else None
        lines.append(f"{row['name']} ({row['player']}/{row['position']}) | {row['gameweek']} | {row['fixture']} | {display(row['minutes'])} | {display(row['value'])} | {display(row['total'])} | {display(row['history_total'])} | {display(row['explanation_total'])} | {display(delta)} | {row['finished']}/{row['finished_provisional']}")
    lines += ["", "## Category reconciliation per fixture", "", "Entries show calculated/official points; omitted categories are 0/0.", ""]
    for row in result["fixtures"]:
        parts = [f"{k}: {display(row['calculated'].get(k))}/{display(row['official'].get(k))}" for k in sorted(set(row['calculated']) | set(row['official'])) if row['calculated'].get(k) != 0 or row['official'].get(k) != 0]
        lines.append(f"- {row['name']} GW{row['gameweek']} fixture {row['fixture']}: " + "; ".join(parts))
    lines += ["", "## Gameweek reconciliation", "", "Player (ID) | GW | Fixtures | State | Calc | History sum | Official live | Finished/checked",
              "---|---:|---|---|---:|---:|---:|---"]
    for w in result["gameweeks"]:
        lines.append(f"{w['name']} ({w['player']}) | {w['gameweek']} | {w['fixtures']} | {w['state']} | {display(w['total'])} | {display(w['history_total'])} | {display(w['official_total'])} | {w['finished']}/{w['data_checked']}")
    lines += ["", "## Award explanations", ""]
    for kind, keys in (("Attacking", ("goals_scored", "assists")), ("Defensive contribution", ("defensive_contribution",))):
        found = False
        for row in result["fixtures"]:
            for key in keys:
                if (row["calculated"][key] or 0) > 0:
                    record = next(r for r in snapshot["observations"][f"element-summary/{row['player']}/"]["payload"]["history"] if r['fixture'] == row['fixture'])
                    explanation = (
                        f"{key} count of {record[key]} → {row['calculated'][key]} calculated points. "
                        f"Official award: {display(row['official'][key])}."
                    )
                    if key == "defensive_contribution":
                        explanation += f" {row['position']} threshold is {10 if row['position'] == 'DEF' else 12} actions, capped at 2 points per fixture."
                    lines.append(f"- {kind}: {row['name']} GW{row['gameweek']}, fixture {row['fixture']}: {explanation}")
                    found = True
                    break
            if found:
                break
        if not found:
            lines.append(f"- {kind}: no award available in this sample.")
    lines += ["", "## Diagnostics", ""]
    lines.extend([f"- {issue}" for issue in result["issues"]] or ["No category, fixture-total or gameweek-total discrepancies found."])
    covered = Counter(k for r in result["fixtures"] for k, v in r["calculated"].items() if v is not None and v != 0)
    absent = [k for k in CATEGORIES if not covered[k]]
    lines += ["", "## Coverage and limits", "",
              "- This slice covers four players, one per position, across two selected gameweeks. See the completion flags and diagnostics above.",
              "- Categories without nonzero calculated points in this slice: " + (", ".join(absent) or "none") + ".",
              "- Synthetic offline tests cover scoring boundaries, double gameweeks, blank and missing records, and replay with an explicitly selected corrected observation.",
              "- Saved bootstrap scoring weights are checked against the ruleset. Minute cutoffs, rounding and defensive contribution thresholds are covered by synthetic scoring tests.",
              "- The calculations use official facts for goals, FPL assists, clean-sheet eligibility, bonus and defensive action counts.",
              "- Fixture rounding precedes gameweek aggregation. A blank requires an empty schedule; absent scheduled records remain missing. Zero minutes remain explicit records.",
              "- Schedule coverage uses current bootstrap team and fixture IDs in saved history and explanations. Historical transfers can require team-at-fixture data.",
              "- History prices retain the original 0.1 million units.",
              "- Each endpoint is fetched separately. Corrections between requests can cause discrepancies. A fresh fetch saves a separate snapshot.",
              "- Completion flags describe the saved observation. Unsupported seasons or event scoring overrides require rule review.",
              "- [FPL scoring rules](https://www.premierleague.com/en/news/2174909) and [defensive contribution rules](https://www.premierleague.com/en/news/4361991).", ""]
    return "\n".join(lines)
