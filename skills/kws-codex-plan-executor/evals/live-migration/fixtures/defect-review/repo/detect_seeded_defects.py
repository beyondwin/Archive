from pathlib import Path

source = Path("ledger.py").read_text()
seeded = "return balance - amount" in source and "return account_id" in source
raise SystemExit(1 if seeded else 0)
