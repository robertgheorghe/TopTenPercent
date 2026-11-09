"""Offline checks for saved-observation reconciliation and report output."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from fpl.report import markdown, reconcile
from fpl.scoring import CATEGORIES


def make_snapshot():
    # All four positions share one team. In GW1 the team doubles, and in
    # GW2 it blanks. Only the forward appears in both fixtures.
    observations = {}

    def save(endpoint, payload):
        observations[endpoint] = {
            "payload": payload,
            "url": f"https://fantasy.premierleague.com/api/{endpoint}",
            "fetched_at": "2026-11-07T17:06:00Z",
        }

    save("bootstrap-static/", {
        "game_config": {"scoring": {
            "long_play": 2, "short_play": 1, "saves": 1, "assists": 3,
            "penalties_saved": 5, "penalties_missed": -2, "own_goals": -2,
            "yellow_cards": -1, "red_cards": -3, "bonus": 1, "bps": 0,
            "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
            "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
            "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
            "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
        }},
        "elements": [
            {"id": pid, "web_name": f"P{pid}", "team": 7, "element_type": pid}
            for pid in range(1, 5)
        ],
        "events": [
            {"id": gw, "finished": True, "data_checked": True}
            for gw in (1, 2)
        ],
    })
    save("fixtures/?event=1", [
        {"id": fid, "event": 1, "team_h": 7, "team_a": 9,
         "finished": True, "finished_provisional": True}
        for fid in (11, 12)
    ])
    save("fixtures/?event=2", [])
    live = []
    for pid in range(1, 5):
        records, explain = [], []
        for fid in (11, 12):
            awards = {}
            if fid == 11:
                awards["minutes"] = (90, 2)
                if pid == 2:
                    awards.update(clean_sheets=(1, 4), defensive_contribution=(13, 2))
                if pid == 4:
                    awards["goals_scored"] = (1, 4)
            elif pid == 4:
                awards.update(minutes=(59, 1), assists=(1, 3), yellow_cards=(1, -1))
            points = sum(points for _, points in awards.values())
            records.append({
                **dict.fromkeys(CATEGORIES, 0),
                **{key: value for key, (value, _) in awards.items()},
                "round": 1, "fixture": fid, "element": pid, "value": 55,
                "total_points": points,
            })
            explain.append({"fixture": fid, "stats": [
                {"identifier": key, "value": value, "points": points}
                for key, (value, points) in awards.items()
            ]})
        save(f"element-summary/{pid}/", {"history": records})
        live.append({"id": pid, "explain": explain,
                     "stats": {"total_points": sum(r["total_points"] for r in records)}})
    save("event/1/live/", {"elements": live})
    save("event/2/live/", {"elements": [
        {"id": pid, "explain": [], "stats": {"total_points": 0}}
        for pid in range(1, 5)
    ]})
    return {
        "schema_version": 1, "season": "2026/27",
        "season_identity_basis": {"note": "Synthetic deadline anchor"},
        "players": [4, 3, 2, 1], "gameweeks": [2, 1], "observations": observations,
    }


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_snapshot()

    def payload(self, endpoint):
        return self.snapshot["observations"][endpoint]["payload"]

    def test_totals_and_categories_reconcile_with_deterministic_output(self):
        original = deepcopy(self.snapshot)
        result = reconcile(self.snapshot)
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["season"], "2026/27")
        self.assertEqual(len(result["fixtures"]), 8)
        self.assertEqual(len(result["gameweeks"]), 8)
        for row, expected in zip(result["fixtures"], [2, 0, 8, 0, 2, 0, 6, 3], strict=True):
            for key in ("total", "history_total", "explanation_total"):
                self.assertEqual(row[key], expected)
            self.assertEqual(row["value"], 55)
            self.assertEqual(row["calculated"], row["official"])
        defender = result["fixtures"][2]
        self.assertEqual(defender["calculated"], {
            **dict.fromkeys(CATEGORIES, 0), "minutes": 2, "clean_sheets": 4,
            "defensive_contribution": 2,
        })
        forward = result["gameweeks"][3]
        self.assertEqual((forward["player"], forward["gameweek"], forward["fixtures"]), (4, 1, [11, 12]))
        self.assertEqual((forward["total"], forward["history_total"], forward["official_total"]), (9, 9, 9))
        report = markdown(self.snapshot, result)
        self.assertIn("Attacking: P4 GW1, fixture 11", report)
        self.assertIn("Defensive contribution: P2 GW1, fixture 11", report)
        self.assertIn("defensive_contribution: 2/2", report)
        self.assertEqual(markdown(self.snapshot, reconcile(self.snapshot)), report)
        self.assertEqual(self.snapshot, original)

    def test_category_mismatches_surface_even_when_fixture_totals_match(self):
        stats = self.payload("event/1/live/")["elements"][3]["explain"][0]["stats"]
        stats[0]["points"] = 3
        stats[1]["points"] = 3
        result = reconcile(self.snapshot)
        self.assertEqual(result["issues"], [
            "Player 4 GW1 fixture 11: goals_scored: calculated 4, official 3",
            "Player 4 GW1 fixture 11: minutes: calculated 2, official 3",
        ])

    def test_history_and_live_totals_are_checked_independently(self):
        self.payload("element-summary/4/")["history"][0]["total_points"] = 7
        self.payload("event/1/live/")["elements"][3]["stats"]["total_points"] = 11
        issues = reconcile(self.snapshot)["issues"]
        self.assertIn("Player 4 GW1 fixture 11: totals differ or missing: calculation=6, history=7, explanation=6", issues)
        self.assertIn("Player 4 GW1: missing data or GW mismatch: calculated=9, history=10, live=11", issues)

    def test_missing_second_fixture_differs_from_blank_and_zero_minutes(self):
        self.payload("element-summary/4/")["history"].pop()
        result = reconcile(self.snapshot)
        zero_minutes = result["fixtures"][1]
        self.assertEqual((zero_minutes["minutes"], zero_minutes["total"]), (0, 0))
        missing, blank = result["gameweeks"][3], result["gameweeks"][7]
        self.assertEqual((missing["state"], missing["total"], missing["history_total"]), ("missing", None, None))
        self.assertEqual((blank["state"], blank["total"], blank["history_total"]), ("blank", 0, 0))
        self.assertIn("Player 4 GW1: missing history for fixtures [12]", result["issues"])

    def test_explanation_without_schedule_or_history_is_missing(self):
        live = self.payload("event/2/live/")["elements"][3]
        live["explain"] = [{"fixture": 99, "stats": []}]
        result = reconcile(self.snapshot)
        self.assertEqual(result["gameweeks"][7]["state"], "missing")
        self.assertIn("Player 4 GW2: unexpected explanation fixture IDs", result["issues"])

    def test_missing_fact_explanation_and_live_total_stay_unknown(self):
        self.payload("element-summary/4/")["history"][0]["goals_scored"] = None
        live = self.payload("event/1/live/")["elements"][3]
        live["explain"].pop(0)
        live["stats"] = None
        result = reconcile(self.snapshot)
        fixture, week = result["fixtures"][6], result["gameweeks"][3]
        self.assertIsNone(fixture["total"])
        self.assertIsNone(fixture["explanation_total"])
        self.assertIsNone(fixture["official"]["minutes"])
        self.assertEqual(week["history_total"], 9)
        self.assertIsNone(week["official_total"])
        report = markdown(self.snapshot, result)
        self.assertIn("goals_scored: MISSING/MISSING", report)
        self.assertIn("Player 4 GW1 fixture 11: missing official explanation", report)

    def test_scoring_weight_changes_and_missing_values_require_review(self):
        scoring = self.payload("bootstrap-static/")["game_config"]["scoring"]
        for key, value in (
            ("long_play", None), ("short_play", True), ("assists", 4),
            ("goals_scored", {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 5}),
            ("defensive_contribution", {"GKP": False, "DEF": 2, "MID": 2, "FWD": 2}),
        ):
            with self.subTest(key=key):
                previous = scoring[key]
                scoring[key] = value
                with self.assertRaisesRegex(ValueError, f"Scoring configuration {key}"):
                    reconcile(self.snapshot)
                scoring[key] = previous
        del self.payload("bootstrap-static/")["game_config"]
        with self.assertRaisesRegex(ValueError, "game_config.scoring"):
            reconcile(self.snapshot)

    def test_event_scoring_override_requires_review(self):
        event = self.payload("bootstrap-static/")["events"][0]
        event["overrides"] = {"scoring": {"long_play": 3}}
        with self.assertRaisesRegex(ValueError, "GW1: scoring overrides"):
            reconcile(self.snapshot)

    def test_cli_report_exit_codes_and_artifacts(self):
        data = Path("data")
        data.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=data) as folder:
            folder = Path(folder)
            snapshot_path = folder / "snapshot.json"
            for status, output in ((0, "0 diagnostics"), (1, "1 diagnostics"), (2, "Validation failed")):
                with self.subTest(status=status):
                    if status == 1:
                        self.payload("event/1/live/")["elements"][0]["stats"]["total_points"] = 3
                    elif status == 2:
                        self.snapshot["season"] = "2030/31"
                    raw = json.dumps(self.snapshot).encode("utf-8")
                    snapshot_path.write_bytes(raw)
                    destination = folder / str(status)
                    run = subprocess.run(
                        [sys.executable, "-m", "fpl", "report", str(snapshot_path),
                         "--output-dir", str(destination)],
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(run.returncode, status, run.stderr)
                    self.assertIn(output, run.stdout + run.stderr)
                    self.assertEqual(snapshot_path.read_bytes(), raw)
                    if status == 2:
                        self.assertFalse(destination.exists())
                    else:
                        result = json.loads((destination / "results.json").read_text(encoding="utf-8"))
                        self.assertEqual(len(result["issues"]), status)
                        self.assertEqual((destination / "report.md").read_text(encoding="utf-8"),
                                         markdown(self.snapshot, result))

    def test_cli_report_protects_input_from_output_path_collision(self):
        data = Path("data")
        data.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=data) as folder:
            folder = Path(folder)
            raw = json.dumps(self.snapshot).encode("utf-8")
            snapshot_path = folder / "results.json"
            snapshot_path.write_bytes(raw)
            run = subprocess.run(
                [sys.executable, "-m", "fpl", "report", str(snapshot_path),
                 "--output-dir", str(folder)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(run.returncode, 2, run.stderr)
            self.assertIn("would overwrite the input snapshot", run.stderr)
            self.assertEqual(snapshot_path.read_bytes(), raw)
            self.assertFalse((folder / "report.md").exists())
