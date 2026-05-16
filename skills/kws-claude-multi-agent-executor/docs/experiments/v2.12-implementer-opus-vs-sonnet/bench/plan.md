# Plan — `flagset` CLI library (v2.12 benchmark)

Companion to `spec.md`. 6 sequential tasks. Each spec section §N governs Task N.

Task complexity is engineered so the Phase 0 Step 6 heuristic assigns:

| Task | Expected bucket | Why |
|------|-----------------|-----|
| 0    | SMALL  | 1 file, 1 new decl (`__version__`), low risk |
| 1    | SMALL  | 1 file, 1 new decl (`FlagType` enum), low risk |
| 2    | MEDIUM | 2 files, 3 new decls (`parse_value`, `Flag`, `FlagRegistry`), no high-risk keyword |
| 3    | MEDIUM | 2 files, 1 new decl in code + a backfill test file, mid-risk |
| 4    | LARGE  | HIGH risk forced via "API surface" + "breaking change" keywords (Phase 0 Step 4) |
| 5    | LARGE  | HIGH risk + file_count ≥ 4 (5 files: cli.py + 4 test files) |

The 2-2-2 distribution is the headline-finding axis: per-bucket Δ between Sonnet and Opus arms.

## Phase 1

### Task 0: Version constant

**Files:**
- modify `src/flagset/__init__.py`

Implement spec §1. Add the single line `__version__: str = "0.1.0"` (no imports, no re-exports, no other top-level statements). Re-exports are introduced later in Task 5.

## Acceptance Criteria

```bash
PYTHONPATH=src python -c "import flagset; assert flagset.__version__ == '0.1.0'; print('ok')"
```

---

### Task 1: FlagType enum

**Files:**
- create `src/flagset/types.py`

Implement spec §2. Add the `FlagType` enum only — do NOT add `parse_value` in this task (it comes in Task 2).

## Acceptance Criteria

```bash
PYTHONPATH=src python -c "from flagset.types import FlagType; \
  assert list(FlagType) == [FlagType.BOOL, FlagType.INT, FlagType.FLOAT, FlagType.STRING]; \
  assert FlagType.BOOL.value == 'bool' and FlagType.STRING.value == 'string'; \
  print('ok')"
```

---

### Task 2: parse_value + Flag + FlagRegistry

**Files:**
- modify `src/flagset/types.py`
- create `src/flagset/registry.py`
- create `tests/test_types.py`

Implement spec §3. Adds `parse_value` to `types.py` and introduces `Flag` plus `FlagRegistry` in `registry.py`. ALSO write `tests/test_types.py` covering §2 (Task 1 deferred this) AND the new `parse_value` cases from this task. Tests MUST include each BOOL truthy form (case-insensitive), each BOOL falsy form, BOOL rejection with exact message, INT positive/negative, INT failure propagation, FLOAT success/failure, STRING whitespace preservation, and `list(FlagType)` ordering.

Registry tests are deferred to Task 3.

## Acceptance Criteria

```bash
pytest tests/test_types.py -q
PYTHONPATH=src python -c "from flagset.registry import Flag, FlagRegistry; from flagset.types import FlagType; \
  r = FlagRegistry(); r.register(Flag('verbose', FlagType.BOOL, short='v')); \
  assert r.get('v').name == 'verbose' and 'verbose' in r and len(r) == 1; print('ok')"
```

---

### Task 3: Argv parser

**Files:**
- create `src/flagset/parser.py`
- create `tests/test_registry.py`

Implement spec §4. Adds `parse_argv` in `parser.py`. ALSO write `tests/test_registry.py` covering §3 retrospectively. Registry tests MUST include: register-then-retrieve by long name and short; name-collision raises ValueError with the exact spec'd message; short-collision raises ValueError with `"short"` in the message; `list_flags()` registration order; `__contains__` for long and short; `len(registry)` matches count.

Parser tests are deferred to Task 4.

## Acceptance Criteria

```bash
pytest tests/test_types.py tests/test_registry.py -q
PYTHONPATH=src python -c "from flagset.registry import FlagRegistry, Flag; from flagset.types import FlagType; from flagset.parser import parse_argv; \
  r = FlagRegistry(); r.register(Flag('verbose', FlagType.BOOL, short='v')); \
  r.register(Flag('input', FlagType.STRING, short='i')); \
  out, pos = parse_argv(r, ['--verbose', '-i', '/tmp/x', '--', 'extra']); \
  assert out == {'verbose': True, 'input': '/tmp/x'} and pos == ['extra']; print('ok')"
```

---

## Phase 2

### Task 4: Validation layer (HIGH RISK — breaking change to error reporting API surface)

**Files:**
- create `src/flagset/validation.py`
- create `tests/test_parser.py`

**Risk:** HIGH. This task introduces the public **API surface** for error reporting (`ValidationError` with `field`/`value`/`reason` attributes and its `__str__` format). Any future **breaking change** to this contract cascades into every downstream consumer of the library — error parsers, CI assertions, log scrapers. The exact attribute names and `str()` format are stable interface; treat divergence from spec §5 as a contract violation.

Implement spec §5. ALSO write `tests/test_parser.py` covering §4 retrospectively. Parser tests MUST cover each precedence rule: `--`, `--name=value`, `--name value` (non-bool), `--name` for BOOL, `-X value`, `-Xvalue` (attached short), `-Xvalue` for BOOL raising the exact error, bare positionals, default fill-in, unknown flag rejection, repeated flag last-wins.

Validation tests are deferred to Task 5.

## Acceptance Criteria

```bash
pytest tests/test_types.py tests/test_registry.py tests/test_parser.py -q
PYTHONPATH=src python -c "from flagset.validation import ValidationError; \
  e = ValidationError('input', None, 'required flag missing'); \
  assert e.field == 'input' and e.value is None and e.reason == 'required flag missing'; \
  assert str(e) == \"validation failed for 'input': required flag missing (got None)\"; print('ok')"
```

---

### Task 5: CLI integration with re-exports and help text (HIGH RISK — public API surface, breaking change to consumer ergonomics)

**Files:**
- create `src/flagset/cli.py`
- modify `src/flagset/__init__.py`
- create `tests/test_validation.py`
- create `tests/test_cli.py`
- create `tests/test_init.py`

**Risk:** HIGH. This task closes the public **API surface** of the library — the `CLI` class is the primary user-facing entry point. The `help_text()` format is part of the contract (downstream tools may scrape or compare it). Any **breaking change** to chain semantics on `flag()`, the return shape of `run()`, the location of `positionals`, the help-text format, OR the set of names re-exported from `flagset` is a major-version event.

Implement spec §6. This includes:

1. Add the `CLI` class to `src/flagset/cli.py`.
2. Update `src/flagset/__init__.py` to re-export `FlagType`, `parse_value`, `Flag`, `FlagRegistry`, `parse_argv`, `ValidationError`, `validate`, `CLI`. Plain `from X import Y` (no guards — all submodules exist now). Retain `__version__`.
3. Write `tests/test_init.py` — two tests: `test_version` (asserts `flagset.__version__ == "0.1.0"`) and `test_all_exports_present` (asserts every name above is importable from `flagset`).
4. Write `tests/test_validation.py` — covers §5: `ValidationError` attribute storage and `str()` format; required-missing fires before choices check (test by providing an invalid-choice value for a required flag whose key is also absent — required must win); choices error message contains the choices tuple in repr form; passing case returns the dict unchanged with `result is parsed` True.
5. Write `tests/test_cli.py` — covers §6: build a CLI with three flags (`--input` STRING required short `-i`; `--verbose` BOOL short `-v` default False; `--mode` STRING choices `("fast","safe")` default `"fast"` help `"run mode"`); parse `["--input=/tmp/x", "-v", "--mode", "safe", "--", "extra", "pos"]` and assert flag dict + positionals; missing `--input` raises ValidationError with `field=="input"`; `cli.run(["--help"])` returns `{}` and captured stdout equals `cli.help_text()` exactly; `cli.help_text()` exact-string assertion against an inline hard-coded expected string composed in the test (so any spacing/formatting drift fails the test).

## Acceptance Criteria

```bash
pytest -q
```

The full suite (6 test files, ~30+ assertions) must pass.
