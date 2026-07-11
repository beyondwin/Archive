import subprocess

status = subprocess.run(["git", "status", "--porcelain"], text=True, capture_output=True, check=True).stdout
raise SystemExit(1 if status else 0)
