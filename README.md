# TopTenPercent

Personal classic FPL analysis project. Official FPL endpoints are the agreed MVP source.

## Current stage

Fixture scoring, gameweek aggregation, bounded collection and reconciliation have
42 offline standard-library tests. The saved 2026/27 GW1–2 sample reconciled
eight player-fixture records and eight player-gameweeks with zero diagnostics.
Docker Compose runs React with Vite, Django REST Framework and PostgreSQL.
The offline tools use a separate Python 3.12 `.venv`, which Git ignores.

## Start the local app on Windows

Start Docker Desktop with the Linux engine and open PowerShell in `D:\FPL`.
If `.env` is missing, generate local credentials once and keep the file for later starts.

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    $djangoKey = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
    $dbPassword = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(24))"
    Set-Content .env -Encoding Ascii -Value @("DJANGO_SECRET_KEY=$djangoKey", "POSTGRES_PASSWORD=$dbPassword")
}
```

```powershell
docker compose up --build --watch
```

Open [localhost:4000](http://localhost:4000) and expect **PostgreSQL connected.**
The [API health endpoint](http://localhost:4000/api/health/) returns `{"database":"ok"}`.
Edits in `frontend/src/` update the page automatically. Rebuild after changing
other frontend files. Press Ctrl+C to stop, then run `docker compose down`
to remove the containers and keep the database volume.

## Offline commands (PowerShell, from the project directory)

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

## Fetch and report

To collect a fresh sample, use current-season player IDs (one per position)
and completed gameweeks that meet the collection rules above. This example
uses the IDs and gameweeks from the 2026/27 validation sample. Choose a new
snapshot path for each fetch.

```powershell
.\.venv\Scripts\python.exe -m fpl fetch --output .\data\snapshot.json --players 1 4 12 411 --gameweeks 1 2
```

To replay the saved sample offline, or any compatible snapshot, pass its
JSON path and an output directory.

```powershell
.\.venv\Scripts\python.exe -m fpl report .\data\validation-2026-11-07\snapshot.json --output-dir .\data\validation-2026-11-07\replay
```

The report writes `report.md` and `results.json`. Exit code 0 means the
records reconcile, 1 means reports were generated with diagnostics, and 2
means validation or I/O failed. Reporting checks saved bootstrap scoring
weights against the supported ruleset and requires review of scoring overrides.
Minute cutoffs, rounding and defensive action thresholds are checked separately
by synthetic scoring tests. The saved sample is local and ignored by Git.

## Structure

- `fpl/scoring.py`: pure fixture scoring and gameweek aggregation.
- `fpl/fetch.py`: bounded official collection, independent of scoring/reporting.
- `fpl/report.py`: offline reconciliation of saved fixture and gameweek data.
- `tests/test_scoring.py`: synthetic offline scoring checks.
- `tests/test_fetch.py`: synthetic offline HTTP collection checks.
- `tests/test_report.py`: synthetic reconciliation, scoring configuration and CLI checks.
- `data/`: local fetched inputs and generated reports; ignored by Git.
