from apps.console.view import render

summary = render()
raise SystemExit(0 if "core" in summary and "filesystem" in summary else 1)
