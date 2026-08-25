# Spec — `flagset` CLI argument library

A small, self-contained Python library that parses command-line argument flags with type coercion and validation. Designed to be implemented in 6 incremental tasks (see `plan.md`).

The target repo layout after all 6 tasks land:

```
<repo-root>/
├── pyproject.toml          (provided up front; tasks do not edit it)
├── src/
│   └── flagset/
│       ├── __init__.py
│       ├── types.py
│       ├── registry.py
│       ├── parser.py
│       ├── validation.py
│       └── cli.py
└── tests/
    ├── test_init.py
    ├── test_types.py
    ├── test_registry.py
    ├── test_parser.py
    ├── test_validation.py
    └── test_cli.py
```

The repo is initialized with:
- `pyproject.toml` declaring `flagset` as a package with `pytest` as a dev dep
- `src/flagset/__init__.py` exists but is empty
- `tests/` exists but is empty

Each spec section §1–§6 governs exactly one task in plan.md. Tasks build up incrementally — module imports work the moment a submodule lands, and `__init__.py` re-exports are added in the final task.

---

## §1 Version constant (governs Task 0)

`src/flagset/__init__.py` introduces a single new declaration: `__version__: str = "0.1.0"` (string literal exactly `"0.1.0"`, never computed).

No imports, no re-exports, no other top-level statements at this stage. Re-exports are added in Task 5.

### Acceptance for Task 0

`PYTHONPATH=src python -c "import flagset; assert flagset.__version__ == '0.1.0'"` returns exit 0.

---

## §2 FlagType enum (governs Task 1)

`src/flagset/types.py` introduces a single new declaration: the `FlagType` enum.

### `FlagType` — `enum.Enum` (NOT `IntEnum`, NOT `StrEnum`)

Members (in this order; iteration order matters for `list(FlagType)`):

1. `BOOL`
2. `INT`
3. `FLOAT`
4. `STRING`

Each member's `.value` MUST be the lowercase string of its name (`"bool"`, `"int"`, `"float"`, `"string"`).

`parse_value` is NOT in this section. It is introduced in Task 2.

### Acceptance for Task 1

```bash
PYTHONPATH=src python -c "from flagset.types import FlagType; \
  assert list(FlagType) == [FlagType.BOOL, FlagType.INT, FlagType.FLOAT, FlagType.STRING]; \
  assert FlagType.BOOL.value == 'bool' and FlagType.STRING.value == 'string'"
```

---

## §3 Value parser + Flag and FlagRegistry (governs Task 2)

Task 2 adds three new declarations across two files: `parse_value` in `types.py`, and `Flag` plus `FlagRegistry` in `registry.py`.

### `parse_value(flag_type: FlagType, raw: str) -> bool | int | float | str` (added to `types.py`)

Parse a raw CLI string into the typed value. Rules:

- `BOOL`: accept `"true"`, `"1"`, `"yes"`, `"on"` (case-insensitive) → `True`; `"false"`, `"0"`, `"no"`, `"off"` → `False`. Any other input raises `ValueError` with message `"cannot parse bool from {raw!r}"`.
- `INT`: `int(raw)` semantics. Failures propagate `ValueError` from `int()` unchanged.
- `FLOAT`: `float(raw)` semantics. Failures propagate `ValueError` from `float()` unchanged.
- `STRING`: returns `raw` unchanged (no stripping, no quoting interpretation).

The `bool` parser MUST NOT call `bool(raw)` — that would coerce non-empty strings to `True`.

### `Flag` — `dataclass(frozen=True, slots=True)` (in `registry.py`)

Fields, in order:

1. `name: str` — long name, kebab-case (no leading dashes)
2. `flag_type: FlagType`
3. `short: str | None = None` — single-letter alias (no leading dash)
4. `default: object | None = None`
5. `required: bool = False`
6. `choices: tuple[object, ...] | None = None` — finite allowed set; must use `tuple` not `list` (frozen-dataclass hashable)
7. `help: str = ""`

The dataclass MUST be `frozen=True` AND `slots=True`.

### `FlagRegistry` (in `registry.py`)

A mutable class. Constructor takes no arguments.

Methods:

- `register(flag: Flag) -> None` — adds the flag. Raises `ValueError` if a flag with the same `name` or with a conflicting `short` already exists. Error message format MUST match: `f"flag {flag.name!r} conflicts with existing flag {existing.name!r} on {field!r}"` where `field` is `"name"` or `"short"` depending on which collided.
- `get(name_or_short: str) -> Flag` — accept either the long name (`"verbose"`) or single-letter short (`"v"`). Raises `KeyError(f"unknown flag {name_or_short!r}")` if not found.
- `list_flags() -> list[Flag]` — returns flags in registration order.
- `__len__` returns the number of registered flags.
- `__contains__(name_or_short: str)` — supports `"verbose" in registry`.

No public attribute is mutable directly — all mutation goes through `register`. The class MUST NOT expose `flags` or `_flags` as a public field.

### Acceptance for Task 2

`pytest tests/test_types.py -q` passes (Task 2 writes `tests/test_types.py` covering both §2 and the parse_value additions).

Plus a smoke check on registry:

```bash
PYTHONPATH=src python -c "from flagset.registry import Flag, FlagRegistry; from flagset.types import FlagType; \
  r = FlagRegistry(); r.register(Flag('verbose', FlagType.BOOL, short='v')); \
  assert r.get('v').name == 'verbose' and 'verbose' in r and len(r) == 1"
```

---

## §4 Argv parser (governs Task 3)

`src/flagset/parser.py` introduces a single new declaration: `parse_argv`.

### `parse_argv(registry: FlagRegistry, argv: list[str]) -> tuple[dict[str, object], list[str]]`

Parse `argv` (which excludes the program name) into:

1. A dict of `{flag.name: typed_value}` — keys are always long names, never shorts.
2. A list of leftover positional arguments (everything after `--` or non-flag tokens that follow a fully-consumed flag set; see precedence below).

Token grammar (precedence top to bottom):

1. **`--`** — terminator. Everything after goes into positionals as-is. The `--` itself is NOT in either output.
2. **`--name=value`** — long flag with attached value. Value is everything after the first `=`. The flag's type determines parsing.
3. **`--name value`** — long flag with separated value. Consumes the next token as value. EXCEPT if the flag's type is `BOOL`, in which case the value is implicitly `True` and the next token is NOT consumed.
4. **`--name`** — long flag without value. For `BOOL` type → `True`. For all other types → `ValueError(f"flag {name!r} requires a value")`.
5. **`-X` / `-Xvalue` / `-X value`** — short flag. Same rules as long flag but with single dash. `-Xvalue` (attached, no `=`) only applies when type is NOT `BOOL`; for `BOOL` shorts attached values are forbidden — raise `ValueError(f"bool flag {name!r} does not accept inline value")`.
6. **Bare token (not starting with `-`)** — appended to positionals.

After parsing the entire `argv`, any flag with a `default` not present in the returned dict MUST be filled in with its default value. Flags with no default and not present are simply absent from the dict.

Unknown flags (names/shorts not in the registry) raise `ValueError(f"unknown flag {token!r}")`. Repeated flag values: the LAST occurrence wins (no list accumulation).

### Acceptance for Task 3

`pytest tests/test_types.py tests/test_registry.py -q` passes (Task 3 adds `tests/test_registry.py` retrospectively covering §3 registry).

Plus a smoke check on parser:

```bash
PYTHONPATH=src python -c "from flagset.registry import FlagRegistry, Flag; from flagset.types import FlagType; from flagset.parser import parse_argv; \
  r = FlagRegistry(); r.register(Flag('verbose', FlagType.BOOL, short='v')); \
  r.register(Flag('input', FlagType.STRING, short='i')); \
  out, pos = parse_argv(r, ['--verbose', '-i', '/tmp/x', '--', 'extra']); \
  assert out == {'verbose': True, 'input': '/tmp/x'} and pos == ['extra']"
```

---

## §5 Validation (governs Task 4 — HIGH RISK)

`src/flagset/validation.py` introduces two new declarations: `ValidationError` and `validate`.

This task touches the public **API surface** for error reporting. Any future **breaking change** to the `ValidationError` shape or `str()` format would cascade into every downstream consumer (CI assertions, log scrapers, error-handling code). Treat divergence from this section as a contract violation.

### `ValidationError(Exception)`

Constructor: `ValidationError(field: str, value: object, reason: str)`. The three arguments MUST be stored as attributes with the same names. `str(err)` MUST equal `f"validation failed for {field!r}: {reason} (got {value!r})"`.

### `validate(registry: FlagRegistry, parsed: dict[str, object]) -> dict[str, object]`

Apply, in this order:

1. **Required check.** For each flag in `registry.list_flags()` with `required=True`: if its `name` is not a key in `parsed`, raise `ValidationError(name, None, "required flag missing")`.
2. **Choices check.** For each key in `parsed`: if the corresponding `Flag.choices` is not None and the value is not in `choices`, raise `ValidationError(name, value, f"value not in choices {choices!r}")`. Use the choices tuple as-is in the error message (use the literal `!r` formatting; no manual quoting).
3. **Type post-check.** After successful checks, the function returns `parsed` unchanged (identity, not a copy: `result is parsed` MUST be True).

The order matters because the test suite asserts which check fires when more than one would fail.

### Acceptance for Task 4

`pytest tests/test_types.py tests/test_registry.py tests/test_parser.py -q` passes (Task 4 adds `tests/test_parser.py` retrospectively covering §4 parser).

Plus a smoke check on validation:

```bash
PYTHONPATH=src python -c "from flagset.validation import ValidationError; \
  e = ValidationError('input', None, 'required flag missing'); \
  assert e.field == 'input' and e.value is None and e.reason == 'required flag missing'; \
  assert str(e) == \"validation failed for 'input': required flag missing (got None)\""
```

---

## §6 CLI integration (governs Task 5 — HIGH RISK)

This task is the public **API surface** of the library. The `CLI` class is the primary user-facing entry point. The `help_text()` format is part of the contract — downstream tools may scrape or compare it. Any **breaking change** to chain semantics on `flag()`, the return shape of `run()`, the location of `positionals`, or the help-text format is a major-version event.

Task 5 introduces several declarations across multiple files: the `CLI` class in `src/flagset/cli.py`, full re-exports in `src/flagset/__init__.py`, and four test files.

### `__init__.py` re-exports (added in this task)

At module load time, re-export the following names from their respective submodules:

- `FlagType` and `parse_value` from `flagset.types`
- `Flag` and `FlagRegistry` from `flagset.registry`
- `parse_argv` from `flagset.parser`
- `ValidationError` and `validate` from `flagset.validation`
- `CLI` from `flagset.cli`

The re-exports are plain `from X import Y` statements — no guards needed since all submodules now exist. `__init__.py` retains `__version__` from §1.

### `CLI` (in `src/flagset/cli.py`)

Constructor: `CLI(name: str, description: str = "")`.

Public methods:

- `flag(name, flag_type, *, short=None, default=None, required=False, choices=None, help="") -> "CLI"` — chainable. Internally constructs a `Flag` and calls `registry.register`. The choices argument accepts a list OR tuple — coerce to tuple before registration.
- `run(argv: list[str]) -> dict[str, object]` — end-to-end: parse, validate, return the parsed+validated dict. Positionals are stored on `self.positionals` (a list); the method returns ONLY the flag dict for clarity.
- `help_text() -> str` — formatted help string. Format MUST be:

  ```
  {name} — {description}

  Usage: {name} [OPTIONS] [-- POSITIONAL...]

  Options:
  {options block}
  ```

  When `description` is empty, the first line is `{name}` only (no em-dash, no trailing space). The options block lists each flag in registration order, one per line:

  ```
    --<name>[, -<short>]  <type>  <help>  [required] [default=<repr(default)>] [choices=<repr(choices)>]
  ```

  Each bracketed annotation is included only when applicable. Tags are separated by single spaces; no leading/trailing whitespace per line. Long-name and short-name segment uses `, -<short>` with a comma-space when a short is set; just `--<name>` when not.

- `run` with `argv` containing `--help` or `-h` (when not registered as a regular flag) MUST print `help_text()` to stdout and return `{}` without invoking validation. If `--help` IS registered as a regular flag, treat it as a normal flag (the user opted in).

### Acceptance for Task 5

`pytest -q` (full suite) passes.
