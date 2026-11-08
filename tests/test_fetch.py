"""Offline collection contracts using synthetic standard-library HTTP responses."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from fpl.fetch import BASE, fetch_snapshot


PLAYERS = (1, 4, 12, 411)
GAMEWEEKS = (1, 2)
FETCHED_AT = datetime(2026, 11, 8, 12, 30, tzinfo=timezone.utc)


def responses():
    # Deliberately unordered events: season identity must use the first event ID.
    payloads = {
        "bootstrap-static/": {
            "events": [
                {"id": 2, "deadline_time": "2027-01-02T11:00:00Z",
                 "finished": True, "data_checked": True},
                {"id": 1, "deadline_time": "2026-08-14T17:30:00Z",
                 "finished": True, "data_checked": True},
            ],
            "elements": [
                {"id": player, "element_type": position, "now_cost": 50 + position}
                for position, player in enumerate(PLAYERS, 1)
            ] + [{"id": 999, "element_type": 3, "now_cost": 76}],
            "unknown_source_field": {"label": "unmodified £ price", "value": None},
        },
    }
    for gw in GAMEWEEKS:
        fixture = 100 + gw
        payloads[f"fixtures/?event={gw}"] = [
            {"id": fixture, "event": gw, "finished": True, "finished_provisional": True},
        ]
        payloads[f"event/{gw}/live/"] = {
            "elements": [{"id": player, "explain": [{"fixture": fixture, "stats": []}]}
                         for player in (*PLAYERS, 999)],
        }
    for player in PLAYERS:
        payloads[f"element-summary/{player}/"] = {
            "history": [{"element": player, "fixture": 100 + gw, "round": gw,
                         "minutes": 90, "value": 79 + gw} for gw in GAMEWEEKS]
                       + [{"element": player, "fixture": 103, "round": 3,
                           "minutes": None, "value": 82}],
            "history_past": [{"season_name": "2025/26", "total_points": 100}],
            "fixtures": [],
        }
    return payloads


class CollectionTests(unittest.TestCase):
    def setUp(self):
        data = Path(__file__).resolve().parents[1] / "data"
        data.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="collection-tests-", dir=data)
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name) / "nested" / "snapshot.json"
        self.payloads = responses()
        self.raw = {}
        self.requests = []
        http_patch = patch("fpl.fetch.urllib.request.urlopen", side_effect=self.respond)
        self.http = http_patch.start()
        self.addCleanup(http_patch.stop)
        clock_patch = patch("fpl.fetch.datetime")
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.clock.now.return_value = FETCHED_AT

    def respond(self, request, timeout):
        path = request.full_url.removeprefix(BASE)
        self.requests.append((path, timeout))
        # Whitespace and Unicode make the raw hash distinct from re-encoded JSON.
        raw = (" \n" + json.dumps(self.payloads[path], ensure_ascii=False, indent=1)).encode("utf-8")
        self.raw[path] = raw
        return BytesIO(raw)

    def reject(self, message, **selection):
        with self.assertRaisesRegex(ValueError, message):
            fetch_snapshot(self.destination, **selection)
        self.assertFalse(self.destination.exists())

    def test_bounded_requests_and_lossless_saved_payloads_and_metadata(self):
        original = deepcopy(self.payloads)
        snapshot = fetch_snapshot(self.destination)
        expected_paths = ["bootstrap-static/", "fixtures/?event=1", "event/1/live/",
                          "fixtures/?event=2", "event/2/live/"]
        expected_paths += [f"element-summary/{player}/" for player in PLAYERS]
        self.assertEqual(self.requests, [(path, 30) for path in expected_paths])
        self.assertEqual(self.http.call_count, 9)
        self.assertEqual(snapshot["players"], list(PLAYERS))
        self.assertEqual(snapshot["gameweeks"], list(GAMEWEEKS))
        self.assertEqual(snapshot["season"], "2026/27")
        self.assertEqual(snapshot["season_identity_basis"]["first_event_deadline_time"],
                         "2026-08-14T17:30:00Z")
        for path, observation in snapshot["observations"].items():
            self.assertEqual(observation["payload"], original[path])
            self.assertEqual(observation["url"], BASE + path)
            self.assertEqual(observation["fetched_at"], FETCHED_AT.isoformat())
            self.assertEqual(observation["sha256"], hashlib.sha256(self.raw[path]).hexdigest())
        self.clock.now.assert_called_with(timezone.utc)
        self.assertEqual(json.loads(self.destination.read_text(encoding="utf-8")), snapshot)
        self.assertEqual(self.payloads, original)

    def test_exact_selection_rejected_before_http(self):
        for players in (PLAYERS[:3], (*PLAYERS, 1), (1, 4, 12, 12),
                        (True, 4, 12, 411), (1.0, 4, 12, 411), (0, 4, 12, 411)):
            with self.subTest(players=players):
                self.reject("Select exactly", players=players)
        for gameweeks in ((1,), (1, 1), (1, 2, 1), (True, 2), (1.0, 2), (0, 2)):
            with self.subTest(gameweeks=gameweeks):
                self.reject("Select exactly", gameweeks=gameweeks)
        self.http.assert_not_called()

    def test_unknown_player_or_missing_position_rejected_after_bootstrap(self):
        for change in ("unknown", "position"):
            with self.subTest(change=change):
                self.payloads = responses()
                if change == "unknown":
                    self.payloads["bootstrap-static/"]["elements"].pop(0)
                else:
                    self.payloads["bootstrap-static/"]["elements"][0]["element_type"] = 2
                self.http.reset_mock()
                self.reject("cover GKP")
                self.assertEqual(self.http.call_count, 1)

    def test_unfinished_unchecked_or_missing_event_rejected(self):
        for flag in ("finished", "data_checked"):
            for state in (False, None, 1, "true", "absent"):
                with self.subTest(flag=flag, state=state):
                    self.payloads = responses()
                    event = self.payloads["bootstrap-static/"]["events"][1]
                    if state == "absent":
                        del event[flag]
                    else:
                        event[flag] = state
                    self.reject("GW1 is not completed")
        self.payloads = responses()
        self.payloads["bootstrap-static/"]["events"].pop()
        self.reject("GW1 is not completed")

    def test_unfinished_or_unknown_fixture_completion_rejected(self):
        for state in (False, None, 1, "true", "absent"):
            with self.subTest(state=state):
                self.payloads = responses()
                fixture = self.payloads["fixtures/?event=1"][0]
                if state == "absent":
                    del fixture["finished"]
                else:
                    fixture["finished"] = state
                self.reject("GW1.*fixture")

    def test_missing_zero_or_malformed_minutes_are_not_actual_minutes(self):
        for minutes in (0, None, -1, "90", 90.0, True, "absent"):
            with self.subTest(minutes=minutes):
                self.payloads = responses()
                row = self.payloads["element-summary/411/"]["history"][1]
                if minutes == "absent":
                    del row["minutes"]
                else:
                    row["minutes"] = minutes
                self.reject("Player 411 needs actual minutes in GW2")
        self.payloads = responses()
        self.payloads["element-summary/411/"]["history"].pop(1)
        self.reject("Player 411 needs actual minutes in GW2")

    def test_double_with_one_appearance_preserves_zero_missing_and_null_rows(self):
        history = self.payloads["element-summary/4/"]["history"]
        history[0]["minutes"] = 1
        history.extend([
            {"element": 4, "round": 1, "fixture": 104, "minutes": 0, "value": 80},
            {"element": 4, "round": 1, "fixture": 105, "minutes": None, "value": 80},
            {"element": 4, "round": 1, "fixture": 106, "value": 80},
        ])
        self.payloads["fixtures/?event=1"].extend(
            {"id": fixture, "event": 1, "finished": True}
            for fixture in (104, 105, 106)
        )
        snapshot = fetch_snapshot(self.destination)
        self.assertEqual(snapshot["observations"]["element-summary/4/"]["payload"]["history"], history)

    def test_blank_gameweek_does_not_qualify_as_an_actual_appearance(self):
        self.payloads["fixtures/?event=1"] = []
        for player in PLAYERS:
            history = self.payloads[f"element-summary/{player}/"]["history"]
            history[:] = [row for row in history if row["round"] != 1]
        # This bounded sample requires actual minutes in both GWs, so a blank
        # cannot qualify; it must not be filled with synthetic zero appearances.
        self.reject("needs actual minutes in GW1")

    def test_existing_snapshot_rejected_before_http_and_kept_unchanged(self):
        self.destination.parent.mkdir()
        original = b"previous observation\n"
        self.destination.write_bytes(original)
        with self.assertRaises(FileExistsError):
            fetch_snapshot(self.destination)
        self.http.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), original)

    def test_exclusive_creation_also_protects_snapshot_created_during_fetch(self):
        def racing_response(request, timeout):
            if not self.destination.exists():
                self.destination.parent.mkdir()
                self.destination.write_bytes(b"concurrent observation")
            return self.respond(request, timeout)
        self.http.side_effect = racing_response
        with self.assertRaises(FileExistsError):
            fetch_snapshot(self.destination)
        self.assertEqual(self.destination.read_bytes(), b"concurrent observation")

    def test_http_failure_leaves_no_snapshot(self):
        self.http.side_effect = URLError("synthetic offline failure")
        with self.assertRaises(URLError):
            fetch_snapshot(self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.http.call_count, 1)

    def test_invalid_json_leaves_no_snapshot(self):
        self.http.side_effect = lambda request, timeout: BytesIO(b"invalid JSON")
        with self.assertRaises(json.JSONDecodeError):
            fetch_snapshot(self.destination)
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
