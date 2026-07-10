#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from cpe_runtime.prompt_export import render_export_bundle

def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run"); run.add_argument("--plan", required=True); run.add_argument("--workspace", required=True); run.add_argument("--mode", default="interactive")
    resume = sub.add_parser("resume"); resume.add_argument("--run-id", required=True)
    export = sub.add_parser("export"); export.add_argument("--plan", required=True); export.add_argument("--workspace", required=True); export.add_argument("--mode", choices=("prompt", "handoff"), default="prompt")
    args = parser.parse_args()
    if args.command == "export": print(render_export_bundle(Path(args.plan).read_text(encoding="utf-8"), Path(args.workspace))); return 0
    if args.command == "resume": print(json.dumps({"run_id": args.run_id, "status": "resume_requires_v3_manifest"})); return 0
    print(json.dumps({"status": "ready", "plan": str(Path(args.plan).resolve()), "workspace": str(Path(args.workspace).resolve()), "mode": args.mode})); return 0
if __name__ == "__main__": raise SystemExit(main())
