# TopTenPercent

Personal classic FPL analysis project. Official FPL endpoints are the agreed MVP source.

## Current stage

Fixture scoring and gameweek aggregation have offline standard-library tests.
The wider official-FPL validation milestone is still in progress.
No application framework or third-party dependencies selected.
Python 3.12.9 was available during setup. The local `.venv` is excluded from Git.

## Commands (PowerShell, from the project directory)

Use the virtual environment interpreter directly; activation is optional:

```powershell
.\.venv\Scripts\python.exe --version
```

Run the offline scoring checks (no network or downloaded inputs required):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The scoring checks cover appearance and clean-sheet eligibility at 59/60 minutes,
positional goal weights, saves/concession rounding, defensive-contribution
thresholds and cap, deductions, doubles, blank versus missing data, corrected
observations and deterministic replay. Correction checks select one observation
revision explicitly; persistent correction ingestion is not implemented.

## Structure

- `fpl/scoring.py`: pure fixture scoring and gameweek aggregation.
- `tests/test_scoring.py`: synthetic offline scoring checks.
- `data/`: local fetched inputs and generated reports; ignored by Git.

Collection and report verification remain separate bounded tasks before the full
four-player, two-gameweek validation milestone is complete.
