from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTIVE_MODEL = "2.0.0-matchup"
LEGACY = "MLB-Baseline-0.1"
EXPERIMENTAL_ROUTE = "/api/v1/predictions/experimental"

files = [
    ROOT / "main.py",
    ROOT / "prediction.py",
    ROOT / "repository.py",
    ROOT / "analyzer.py",
    ROOT / "matchup_engine.py",
]

errors = []
for path in files:
    text = path.read_text(encoding="utf-8")
    if path.name != "repository.py" and LEGACY in text:
        errors.append(f"{path.name}: legacy model reference found")
    if path.name == "main.py" and EXPERIMENTAL_ROUTE in text:
        errors.append("main.py: experimental route still present")

if ACTIVE_MODEL not in (ROOT / "prediction.py").read_text(encoding="utf-8"):
    errors.append("prediction.py: official model version missing")

if errors:
    for error in errors:
        print("ERROR:", error)
    raise SystemExit(1)

print("OK: backend cleanup verification passed")
print("Official model:", ACTIVE_MODEL)
print("Legacy historical rows are preserved in the database; no data deletion is performed.")
