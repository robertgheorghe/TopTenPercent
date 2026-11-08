"""Bounded official HTTP collection, isolated from calculation and reporting."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

BASE = "https://fantasy.premierleague.com/api/"


def fetch_snapshot(destination, players=(1, 4, 12, 411), gameweeks=(1, 2)):
    players, gameweeks = tuple(players), tuple(gameweeks)
    if (len(players) != 4 or len(set(players)) != 4
            or len(gameweeks) != 2 or len(set(gameweeks)) != 2
            or any(type(identifier) is not int or identifier <= 0
                   for identifier in (*players, *gameweeks))):
        raise ValueError("Select exactly four distinct players and two distinct gameweeks")
    path = Path(destination)
    if path.exists():
        raise FileExistsError(f"Snapshot already exists: {path}")
    observations = {}

    def get(path):
        request = urllib.request.Request(BASE + path, headers={"User-Agent": "TopTenPercent-validation/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            payload = json.loads(raw)
        observations[path] = {
            "url": BASE + path,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "payload": payload,
        }
        return payload

    bootstrap = get("bootstrap-static/")
    selected = [p for p in bootstrap["elements"] if p["id"] in players]
    if len(selected) != 4 or {p["element_type"] for p in selected} != {1, 2, 3, 4}:
        raise ValueError("Players must exist and cover GKP, DEF, MID and FWD")
    events = {e["id"]: e for e in bootstrap["events"]}
    for gw in gameweeks:
        event = events.get(gw, {})
        if not (event.get("finished") is True and event.get("data_checked") is True):
            raise ValueError(f"GW{gw} is not completed and data checked")
        fixtures = get(f"fixtures/?event={gw}")
        if any(fixture.get("finished") is not True for fixture in fixtures):
            raise ValueError(f"GW{gw} has a fixture that is not completed")
        get(f"event/{gw}/live/")
    for player in players:
        history = get(f"element-summary/{player}/")["history"]
        for gw in gameweeks:
            if not any(r["round"] == gw and type(r.get("minutes")) is int
                       and r["minutes"] > 0 for r in history):
                raise ValueError(f"Player {player} needs actual minutes in GW{gw}")
    # The API has no explicit season ID here; retain the unmodified source anchor.
    anchor = min(bootstrap["events"], key=lambda e: e["id"])["deadline_time"]
    year = int(anchor[:4])
    snapshot = {
        "schema_version": 1, "season": f"{year}/{str(year + 1)[-2:]}",
        "season_identity_basis": {"first_event_deadline_time": anchor,
                                  "note": "Season label inferred from first deadline year; no official season ID supplied"},
        "players": list(players), "gameweeks": list(gameweeks),
        "observations": observations,
    }
    # Exclusive creation prevents accidentally overwriting an earlier observation.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return snapshot
