#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 evals/check_skill_contract.py --skill SKILL.md

python3 scripts/check_doc_quality.py \
  --spec evals/fixtures/good-spec.md \
  --implementation evals/fixtures/good-implementation.md \
  --repo-root .

if python3 scripts/check_doc_quality.py \
  --spec evals/fixtures/bad-spec.md \
  --implementation evals/fixtures/bad-implementation.md \
  --repo-root . >/tmp/kws-doc-quality-bad.out 2>&1; then
  echo "bad fixture unexpectedly passed" >&2
  cat /tmp/kws-doc-quality-bad.out >&2
  exit 1
fi

rm -f /tmp/kws-doc-quality-bad.out
