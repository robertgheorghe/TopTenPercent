# TopTenPercent

Personal classic FPL analysis project. Official FPL endpoints are the agreed MVP source.

## Current stage

Minimal Python setup only. No application framework or third-party dependencies selected.
Python 3.12.9 was available during setup. The local `.venv` is excluded from Git.

## Commands (PowerShell, from the project directory)

Use the virtual environment interpreter directly; activation is optional:

```powershell
.\.venv\Scripts\python.exe --version
```

Once tests are added:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Structure

- `fpl/`: future collection, scoring and reporting code; currently empty.
- `tests/`: future offline checks; no tests implemented yet.
- `data/`: future local fetched inputs; ignored by Git.

## Repository hygiene

No credentials or downloaded squad data in Git.
Next: build a small validation report using official FPL records for four players across two completed gameweeks, with scoring breakdowns and offline checks for scoring boundaries.
