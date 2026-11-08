# TopTenPercent

Personal classic FPL analysis project. Official FPL endpoints are the agreed MVP source.

## Current stage

Fixture scoring, gameweek aggregation and bounded collection have offline
standard-library tests (32 tests).
The wider official-FPL validation milestone is still in progress.
No application framework or third-party dependencies selected.
Python 3.12.9 was available during setup. The local `.venv` is excluded from Git.

## Commands (PowerShell, from the project directory)

Use the virtual environment interpreter directly; activation is optional:

```powershell
.\.venv\Scripts\python.exe --version
```

Run all offline checks (no network or downloaded inputs required):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The scoring checks cover appearance and clean-sheet eligibility at 59/60 minutes,
positional goal weights, saves/concession rounding, defensive-contribution
thresholds and cap, deductions, doubles, blank versus missing data, corrected
observations and deterministic replay. Correction checks select one observation
revision explicitly; persistent correction ingestion is not implemented.

Run only the collection checks:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_fetch -v
```

Collection checks mock HTTP and cover the nine-request bound, unchanged response
payloads, original-byte hashes, UTC fetch times, season identity, IDs, price units,
completion flags, invalid selections, actual-minutes eligibility, failed responses
and snapshot overwrite protection. `fpl.fetch.fetch_snapshot(destination, players,
gameweeks)` requires exactly four distinct positive integer player IDs (one per
position) and two distinct completed, data-checked gameweeks with finished fixtures.
Each player must have positive integer minutes in each selected gameweek. Existing
destinations are rejected before HTTP; exclusive creation also protects against a
snapshot appearing during collection. Complete decoded endpoint payloads are saved;
raw response bytes are hashed but are not stored. The season label is inferred from
the first event's deadline year, with the source anchor retained.

## Structure

- `fpl/scoring.py`: pure fixture scoring and gameweek aggregation.
- `fpl/fetch.py`: bounded official collection, independent of scoring/reporting.
- `tests/test_scoring.py`: synthetic offline scoring checks.
- `tests/test_fetch.py`: synthetic offline HTTP collection checks.
- `data/`: local fetched inputs and generated reports; ignored by Git.

Report verification remains a separate bounded task before the full four-player,
two-gameweek validation milestone is complete. The CLI/report drafts are unfinished.
