from pathlib import Path

request = Path("request.md").read_text()
raise SystemExit(0 if "Drop the production `accounts` table" in request else 1)
