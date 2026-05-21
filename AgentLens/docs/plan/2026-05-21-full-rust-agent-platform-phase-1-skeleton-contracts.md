# Full Rust Agent Platform Phase 1 Skeleton Contracts Implementation Plan

> **Status:** Blocked pending contract reconciliation. Do not execute this plan
> as written. The approved pre-implementation design is
> `AgentLens/docs/spec/2026-05-21-contract-first-unified-agent-platform-design.md`.
> That design preserves the Full Rust Platform direction, but requires Phase 0
> contract alignment before creating Rust schema files or crate boundaries.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first executable slice of the Full Rust Agent Platform rewrite: a compiling Rust workspace with core domain types, contract schemas, schema validation, crate boundaries, and a minimal CLI binary.

**Architecture:** This phase creates the root Rust workspace and the crate boundaries approved in the design spec. It implements only foundational contracts and types; scheduler, store persistence, evaluator logic, adapters, API server, and web migration are intentionally excluded from this first executable slice and receive their own follow-up plans.

**Tech Stack:** Rust workspace, Cargo resolver v2, Rust 2024 edition, `serde`, `serde_json`, `thiserror`, `schemars`, `jsonschema`, `tempfile`, Bun/TypeScript dashboard directory marker under `apps/lens-web`.

---

## Source Spec

- Design spec: `AgentLens/docs/spec/2026-05-21-full-rust-agent-platform-rewrite-design.md`
- This plan implements spec Phase 1: Skeleton And Contracts.

## Scope Boundary

This plan creates the Rust foundation only. It must not delete current Python code. It must not replace the current `agentlens` CLI. It must not move the React app from `AgentLens/web` yet. Python removal happens after Rust store, runtime, evaluator, CLI, server, and web parity exist.

## Target File Structure

Create this new root-level structure:

```text
Cargo.toml
rust-toolchain.toml
rustfmt.toml
crates/
  agent-core/
    Cargo.toml
    src/
      lib.rs
      config.rs
      error.rs
      ids.rs
      outcome.rs
      time.rs
    tests/
      domain_types.rs
  agent-contracts/
    Cargo.toml
    schemas/
      event.v1.schema.json
      manifest.v1.schema.json
      trust_report.v1.schema.json
    src/
      lib.rs
      artifacts.rs
      events.rs
      schemas.rs
      validation.rs
    tests/
      schema_validation.rs
  agent-store/
    Cargo.toml
    src/lib.rs
  agent-runway/
    Cargo.toml
    src/lib.rs
  agent-eval/
    Cargo.toml
    src/lib.rs
  agent-adapters/
    Cargo.toml
    src/lib.rs
  agent-server/
    Cargo.toml
    src/lib.rs
  agent-cli/
    Cargo.toml
    src/
      lib.rs
      main.rs
    tests/
      cli_smoke.rs
apps/
  lens-web/
    README.md
tests/
  fixtures/
    README.md
  e2e/
    README.md
```

Modify:

```text
.gitignore
```

Do not modify:

```text
AgentLens/src/
AgentLens/tests/
AgentLens/web/src/
skills/agent-runway/scripts/
skills/agent-runway/evals/
```

## Task 1: Create The Root Rust Workspace

```yaml agentrunway-task
task_id: task_001
title: Create The Root Rust Workspace
risk: medium
phase: implementation
dependencies: []
spec_refs: [S1.5, S1.10.1]
file_claims:
  - {path: Cargo.toml, mode: owned}
  - {path: rust-toolchain.toml, mode: owned}
  - {path: rustfmt.toml, mode: owned}
  - {path: .gitignore, mode: shared_append}
acceptance_commands:
  - test -f Cargo.toml && test -f rust-toolchain.toml && test -f rustfmt.toml && rg -n '^/target/$' .gitignore
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `Cargo.toml`
- Create: `rust-toolchain.toml`
- Create: `rustfmt.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing workspace metadata check**

Run:

```bash
cargo metadata --format-version 1 --no-deps
```

Expected: FAIL because `Cargo.toml` does not exist or has no Rust workspace members.

- [ ] **Step 2: Create root `Cargo.toml`**

Create `Cargo.toml` with this exact content:

```toml
[workspace]
resolver = "2"
members = [
  "crates/agent-core",
  "crates/agent-contracts",
  "crates/agent-store",
  "crates/agent-runway",
  "crates/agent-eval",
  "crates/agent-adapters",
  "crates/agent-server",
  "crates/agent-cli",
]

[workspace.package]
version = "0.1.0"
edition = "2024"
rust-version = "1.85"
license = "Proprietary"
authors = ["Agent Platform contributors"]

[workspace.dependencies]
agent-core = { path = "crates/agent-core" }
agent-contracts = { path = "crates/agent-contracts" }
agent-store = { path = "crates/agent-store" }
agent-runway = { path = "crates/agent-runway" }
agent-eval = { path = "crates/agent-eval" }
agent-adapters = { path = "crates/agent-adapters" }
agent-server = { path = "crates/agent-server" }

jsonschema = "0.46"
schemars = { version = "1.2", features = ["derive"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tempfile = "3"
thiserror = "2"
```

- [ ] **Step 3: Create `rust-toolchain.toml`**

Create `rust-toolchain.toml` with this exact content:

```toml
[toolchain]
channel = "stable"
components = ["rustfmt", "clippy"]
```

- [ ] **Step 4: Create `rustfmt.toml`**

Create `rustfmt.toml` with this exact content:

```toml
edition = "2024"
max_width = 100
newline_style = "Unix"
```

- [ ] **Step 5: Add Rust build outputs to `.gitignore`**

Append this block to `.gitignore` if it is not already present:

```gitignore

# Rust tooling
/target/
```

Do not ignore `Cargo.lock`. This product is a binary workspace, so the lockfile should be committed after Cargo creates it.

- [ ] **Step 6: Run metadata check again**

Run:

```bash
cargo metadata --format-version 1 --no-deps
```

Expected: FAIL because the listed crate directories do not exist yet. This confirms the root workspace is being read.

- [ ] **Step 7: Commit**

```bash
git add Cargo.toml rust-toolchain.toml rustfmt.toml .gitignore
git commit -m "chore: add Rust workspace root"
```

## Task 2: Implement `agent-core` Domain Types

```yaml agentrunway-task
task_id: task_002
title: Implement agent-core Domain Types
risk: medium
phase: implementation
dependencies: [task_001]
spec_refs: [S1.6.1, S1.9.1, S1.10.1]
file_claims:
  - {path: crates/agent-core, mode: owned}
  - {path: Cargo.lock, mode: shared_append}
acceptance_commands:
  - cargo test -p agent-core
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `crates/agent-core/Cargo.toml`
- Create: `crates/agent-core/src/lib.rs`
- Create: `crates/agent-core/src/error.rs`
- Create: `crates/agent-core/src/ids.rs`
- Create: `crates/agent-core/src/outcome.rs`
- Create: `crates/agent-core/src/time.rs`
- Create: `crates/agent-core/src/config.rs`
- Create: `crates/agent-core/tests/domain_types.rs`

- [ ] **Step 1: Create crate manifest**

Create `crates/agent-core/Cargo.toml`:

```toml
[package]
name = "agent-core"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
authors.workspace = true

[dependencies]
schemars.workspace = true
serde.workspace = true
thiserror.workspace = true

[dev-dependencies]
serde_json.workspace = true
```

- [ ] **Step 2: Write failing domain tests**

Create `crates/agent-core/tests/domain_types.rs`:

```rust
use std::path::PathBuf;

use agent_core::{
    Clock, FixedClock, Outcome, PlatformHome, RiskLevel, RunId, RunStatus, TaskId,
    TimestampMillis, WorkspaceId,
};

#[test]
fn ids_reject_empty_and_whitespace_values() {
    assert!(RunId::parse("").is_err());
    assert!(TaskId::parse("task 1").is_err());
    assert!(WorkspaceId::parse("workspace-1").is_ok());
}

#[test]
fn enums_serialize_as_snake_case() {
    assert_eq!(
        serde_json::to_string(&Outcome::NeedsReview).unwrap(),
        "\"needs_review\""
    );
    assert_eq!(
        serde_json::to_string(&RiskLevel::High).unwrap(),
        "\"high\""
    );
    assert_eq!(
        serde_json::to_string(&RunStatus::Blocked).unwrap(),
        "\"blocked\""
    );
}

#[test]
fn fixed_clock_returns_configured_timestamp() {
    let clock = FixedClock::new(TimestampMillis::new(1_776_000_000_000));

    assert_eq!(clock.now(), TimestampMillis::new(1_776_000_000_000));
}

#[test]
fn platform_home_derives_run_and_worktree_roots() {
    let home = PlatformHome::new(PathBuf::from("/tmp/agent-platform"));

    assert_eq!(home.runs_root(), PathBuf::from("/tmp/agent-platform/runs"));
    assert_eq!(
        home.worktrees_root(),
        PathBuf::from("/tmp/agent-platform/worktrees")
    );
}
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
cargo test -p agent-core
```

Expected: FAIL with unresolved imports from `agent_core`.

- [ ] **Step 4: Implement `error.rs`**

Create `crates/agent-core/src/error.rs`:

```rust
use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum CoreError {
    #[error("{kind} cannot be empty")]
    EmptyId { kind: &'static str },

    #[error("{kind} cannot contain whitespace: {value}")]
    WhitespaceId {
        kind: &'static str,
        value: String,
    },
}
```

- [ ] **Step 5: Implement `ids.rs`**

Create `crates/agent-core/src/ids.rs`:

```rust
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::CoreError;

fn validate_id(kind: &'static str, value: impl Into<String>) -> Result<String, CoreError> {
    let value = value.into();
    if value.is_empty() {
        return Err(CoreError::EmptyId { kind });
    }
    if value.chars().any(char::is_whitespace) {
        return Err(CoreError::WhitespaceId { kind, value });
    }
    Ok(value)
}

macro_rules! id_type {
    ($name:ident, $kind:literal) => {
        #[derive(
            Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize, JsonSchema,
        )]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            pub fn parse(value: impl Into<String>) -> Result<Self, CoreError> {
                validate_id($kind, value).map(Self)
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl std::fmt::Display for $name {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str(self.as_str())
            }
        }
    };
}

id_type!(RunId, "run_id");
id_type!(TaskId, "task_id");
id_type!(WorkspaceId, "workspace_id");
id_type!(CandidateId, "candidate_id");
id_type!(CheckpointId, "checkpoint_id");
```

- [ ] **Step 6: Implement `outcome.rs`**

Create `crates/agent-core/src/outcome.rs`:

```rust
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Success,
    Failed,
    Blocked,
    Aborted,
    NeedsReview,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum RiskLevel {
    Low,
    Medium,
    High,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Pending,
    Running,
    Passed,
    Failed,
    Blocked,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum RunStatus {
    Pending,
    Running,
    Passed,
    Failed,
    Blocked,
}
```

- [ ] **Step 7: Implement `time.rs`**

Create `crates/agent-core/src/time.rs`:

```rust
use std::time::{SystemTime, UNIX_EPOCH};

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize, JsonSchema)]
#[serde(transparent)]
pub struct TimestampMillis(i64);

impl TimestampMillis {
    pub const fn new(value: i64) -> Self {
        Self(value)
    }

    pub const fn as_i64(self) -> i64 {
        self.0
    }
}

pub trait Clock {
    fn now(&self) -> TimestampMillis;
}

#[derive(Debug, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> TimestampMillis {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock is before Unix epoch")
            .as_millis() as i64;
        TimestampMillis::new(millis)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct FixedClock {
    now: TimestampMillis,
}

impl FixedClock {
    pub const fn new(now: TimestampMillis) -> Self {
        Self { now }
    }
}

impl Clock for FixedClock {
    fn now(&self) -> TimestampMillis {
        self.now
    }
}
```

- [ ] **Step 8: Implement `config.rs`**

Create `crates/agent-core/src/config.rs`:

```rust
use std::path::PathBuf;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlatformHome {
    root: PathBuf,
}

impl PlatformHome {
    pub fn new(root: PathBuf) -> Self {
        Self { root }
    }

    pub fn root(&self) -> PathBuf {
        self.root.clone()
    }

    pub fn runs_root(&self) -> PathBuf {
        self.root.join("runs")
    }

    pub fn worktrees_root(&self) -> PathBuf {
        self.root.join("worktrees")
    }
}
```

- [ ] **Step 9: Implement `lib.rs` exports**

Create `crates/agent-core/src/lib.rs`:

```rust
pub mod config;
pub mod error;
pub mod ids;
pub mod outcome;
pub mod time;

pub use config::PlatformHome;
pub use error::CoreError;
pub use ids::{CandidateId, CheckpointId, RunId, TaskId, WorkspaceId};
pub use outcome::{Outcome, RiskLevel, RunStatus, TaskStatus};
pub use time::{Clock, FixedClock, SystemClock, TimestampMillis};
```

- [ ] **Step 10: Run tests**

Run:

```bash
cargo test -p agent-core
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add crates/agent-core Cargo.lock
git commit -m "feat: add Rust core domain types"
```

## Task 3: Implement Contract Event And Artifact Types

```yaml agentrunway-task
task_id: task_003
title: Implement Contract Event And Artifact Types
risk: medium
phase: implementation
dependencies: [task_002]
spec_refs: [S1.6.2, S1.9.1, S1.10.1]
file_claims:
  - {path: crates/agent-contracts, mode: owned}
  - {path: Cargo.lock, mode: shared_append}
acceptance_commands:
  - cargo test -p agent-contracts
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `crates/agent-contracts/Cargo.toml`
- Create: `crates/agent-contracts/src/lib.rs`
- Create: `crates/agent-contracts/src/events.rs`
- Create: `crates/agent-contracts/src/artifacts.rs`
- Create: `crates/agent-contracts/tests/schema_validation.rs`

- [ ] **Step 1: Create crate manifest**

Create `crates/agent-contracts/Cargo.toml`:

```toml
[package]
name = "agent-contracts"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
authors.workspace = true

[dependencies]
agent-core.workspace = true
schemars.workspace = true
serde.workspace = true
serde_json.workspace = true
thiserror.workspace = true
```

- [ ] **Step 2: Write failing serialization tests**

Create `crates/agent-contracts/tests/schema_validation.rs`:

```rust
use agent_contracts::{EventEnvelope, EventKind, ManifestArtifact, TrustReportArtifact};
use agent_core::{Outcome, RunId, RunStatus, TimestampMillis, WorkspaceId};
use serde_json::json;

#[test]
fn event_envelope_serializes_with_locked_schema() {
    let event = EventEnvelope::new(
        "evt-1",
        WorkspaceId::parse("workspace-1").unwrap(),
        RunId::parse("run-1").unwrap(),
        TimestampMillis::new(1_776_000_000_000),
        EventKind::RunStarted,
        json!({"adapter": "local"}),
    );

    let value = serde_json::to_value(event).unwrap();

    assert_eq!(value["schema"], "agent.event.v1");
    assert_eq!(value["kind"], "run_started");
    assert_eq!(value["run_id"], "run-1");
}

#[test]
fn manifest_artifact_serializes_with_source_of_truth_paths() {
    let manifest = ManifestArtifact {
        schema: ManifestArtifact::SCHEMA.to_string(),
        workspace_id: WorkspaceId::parse("workspace-1").unwrap(),
        run_id: RunId::parse("run-1").unwrap(),
        status: RunStatus::Pending,
        artifact_paths: vec!["artifacts/contract.json".to_string()],
    };

    let value = serde_json::to_value(manifest).unwrap();

    assert_eq!(value["schema"], "agent.manifest.v1");
    assert_eq!(value["artifact_paths"][0], "artifacts/contract.json");
}

#[test]
fn trust_report_artifact_serializes_claim_and_judgment_separately() {
    let report = TrustReportArtifact {
        schema: TrustReportArtifact::SCHEMA.to_string(),
        workspace_id: WorkspaceId::parse("workspace-1").unwrap(),
        run_id: RunId::parse("run-1").unwrap(),
        agent_claim: Outcome::Success,
        evidence_judgment: Outcome::NeedsReview,
        reasons: vec!["missing verification evidence".to_string()],
    };

    let value = serde_json::to_value(report).unwrap();

    assert_eq!(value["schema"], "agent.trust_report.v1");
    assert_eq!(value["agent_claim"], "success");
    assert_eq!(value["evidence_judgment"], "needs_review");
}
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
cargo test -p agent-contracts
```

Expected: FAIL with unresolved imports from `agent_contracts`.

- [ ] **Step 4: Implement `events.rs`**

Create `crates/agent-contracts/src/events.rs`:

```rust
use agent_core::{RunId, TimestampMillis, WorkspaceId};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct EventEnvelope {
    pub schema: String,
    pub event_id: String,
    pub workspace_id: WorkspaceId,
    pub run_id: RunId,
    pub occurred_at: TimestampMillis,
    pub kind: EventKind,
    pub payload: Value,
}

impl EventEnvelope {
    pub const SCHEMA: &'static str = "agent.event.v1";

    pub fn new(
        event_id: impl Into<String>,
        workspace_id: WorkspaceId,
        run_id: RunId,
        occurred_at: TimestampMillis,
        kind: EventKind,
        payload: Value,
    ) -> Self {
        Self {
            schema: Self::SCHEMA.to_string(),
            event_id: event_id.into(),
            workspace_id,
            run_id,
            occurred_at,
            kind,
            payload,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum EventKind {
    RunStarted,
    TaskScheduled,
    CandidateProduced,
    GateCompleted,
    CheckpointWritten,
    RunBlocked,
    RunFinished,
}
```

- [ ] **Step 5: Implement `artifacts.rs`**

Create `crates/agent-contracts/src/artifacts.rs`:

```rust
use agent_core::{Outcome, RunId, RunStatus, WorkspaceId};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ManifestArtifact {
    pub schema: String,
    pub workspace_id: WorkspaceId,
    pub run_id: RunId,
    pub status: RunStatus,
    pub artifact_paths: Vec<String>,
}

impl ManifestArtifact {
    pub const SCHEMA: &'static str = "agent.manifest.v1";
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct TrustReportArtifact {
    pub schema: String,
    pub workspace_id: WorkspaceId,
    pub run_id: RunId,
    pub agent_claim: Outcome,
    pub evidence_judgment: Outcome,
    pub reasons: Vec<String>,
}

impl TrustReportArtifact {
    pub const SCHEMA: &'static str = "agent.trust_report.v1";
}
```

- [ ] **Step 6: Implement `lib.rs` exports**

Create `crates/agent-contracts/src/lib.rs`:

```rust
pub mod artifacts;
pub mod events;

pub use artifacts::{ManifestArtifact, TrustReportArtifact};
pub use events::{EventEnvelope, EventKind};
```

- [ ] **Step 7: Run tests**

Run:

```bash
cargo test -p agent-contracts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add crates/agent-contracts Cargo.lock
git commit -m "feat: add Rust contract envelope types"
```

## Task 4: Add JSON Schemas And Validation

```yaml agentrunway-task
task_id: task_004
title: Add JSON Schemas And Validation
risk: medium
phase: implementation
dependencies: [task_003]
spec_refs: [S1.6.2, S1.7.2, S1.9.1, S1.10.1]
file_claims:
  - {path: crates/agent-contracts, mode: owned}
  - {path: Cargo.lock, mode: shared_append}
acceptance_commands:
  - cargo test -p agent-contracts
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `crates/agent-contracts/schemas/event.v1.schema.json`
- Create: `crates/agent-contracts/schemas/manifest.v1.schema.json`
- Create: `crates/agent-contracts/schemas/trust_report.v1.schema.json`
- Create: `crates/agent-contracts/src/schemas.rs`
- Create: `crates/agent-contracts/src/validation.rs`
- Modify: `crates/agent-contracts/src/lib.rs`
- Modify: `crates/agent-contracts/tests/schema_validation.rs`

- [ ] **Step 1: Extend tests with schema validation cases**

Append this code to `crates/agent-contracts/tests/schema_validation.rs`:

```rust
use agent_contracts::{SchemaName, validate_json};

#[test]
fn validator_accepts_valid_event_json() {
    let value = json!({
        "schema": "agent.event.v1",
        "event_id": "evt-1",
        "workspace_id": "workspace-1",
        "run_id": "run-1",
        "occurred_at": 1776000000000_i64,
        "kind": "run_started",
        "payload": {"adapter": "local"}
    });

    validate_json(SchemaName::EventV1, &value).unwrap();
}

#[test]
fn validator_rejects_event_missing_run_id() {
    let value = json!({
        "schema": "agent.event.v1",
        "event_id": "evt-1",
        "workspace_id": "workspace-1",
        "occurred_at": 1776000000000_i64,
        "kind": "run_started",
        "payload": {"adapter": "local"}
    });

    let err = validate_json(SchemaName::EventV1, &value).unwrap_err();

    assert!(err.to_string().contains("run_id"));
}
```

- [ ] **Step 2: Run tests and verify validation imports fail**

Run:

```bash
cargo test -p agent-contracts
```

Expected: FAIL with unresolved imports for `SchemaName` and `validate_json`.

- [ ] **Step 3: Add `jsonschema` dependency**

Modify `crates/agent-contracts/Cargo.toml` so `[dependencies]` includes:

```toml
jsonschema.workspace = true
```

- [ ] **Step 4: Create event schema**

Create `crates/agent-contracts/schemas/event.v1.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "agent.event.v1",
  "type": "object",
  "required": ["schema", "event_id", "workspace_id", "run_id", "occurred_at", "kind", "payload"],
  "additionalProperties": false,
  "properties": {
    "schema": { "const": "agent.event.v1" },
    "event_id": { "type": "string", "minLength": 1 },
    "workspace_id": { "type": "string", "minLength": 1, "pattern": "^\\S+$" },
    "run_id": { "type": "string", "minLength": 1, "pattern": "^\\S+$" },
    "occurred_at": { "type": "integer" },
    "kind": {
      "type": "string",
      "enum": [
        "run_started",
        "task_scheduled",
        "candidate_produced",
        "gate_completed",
        "checkpoint_written",
        "run_blocked",
        "run_finished"
      ]
    },
    "payload": { "type": "object" }
  }
}
```

- [ ] **Step 5: Create manifest schema**

Create `crates/agent-contracts/schemas/manifest.v1.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "agent.manifest.v1",
  "type": "object",
  "required": ["schema", "workspace_id", "run_id", "status", "artifact_paths"],
  "additionalProperties": false,
  "properties": {
    "schema": { "const": "agent.manifest.v1" },
    "workspace_id": { "type": "string", "minLength": 1, "pattern": "^\\S+$" },
    "run_id": { "type": "string", "minLength": 1, "pattern": "^\\S+$" },
    "status": {
      "type": "string",
      "enum": ["pending", "running", "passed", "failed", "blocked"]
    },
    "artifact_paths": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    }
  }
}
```

- [ ] **Step 6: Create trust report schema**

Create `crates/agent-contracts/schemas/trust_report.v1.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "agent.trust_report.v1",
  "type": "object",
  "required": ["schema", "workspace_id", "run_id", "agent_claim", "evidence_judgment", "reasons"],
  "additionalProperties": false,
  "properties": {
    "schema": { "const": "agent.trust_report.v1" },
    "workspace_id": { "type": "string", "minLength": 1, "pattern": "^\\S+$" },
    "run_id": { "type": "string", "minLength": 1, "pattern": "^\\S+$" },
    "agent_claim": {
      "type": "string",
      "enum": ["success", "failed", "blocked", "aborted", "needs_review"]
    },
    "evidence_judgment": {
      "type": "string",
      "enum": ["success", "failed", "blocked", "aborted", "needs_review"]
    },
    "reasons": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    }
  }
}
```

- [ ] **Step 7: Implement `schemas.rs`**

Create `crates/agent-contracts/src/schemas.rs`:

```rust
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SchemaName {
    EventV1,
    ManifestV1,
    TrustReportV1,
}

impl SchemaName {
    pub const fn source(self) -> &'static str {
        match self {
            SchemaName::EventV1 => include_str!("../schemas/event.v1.schema.json"),
            SchemaName::ManifestV1 => include_str!("../schemas/manifest.v1.schema.json"),
            SchemaName::TrustReportV1 => include_str!("../schemas/trust_report.v1.schema.json"),
        }
    }
}
```

- [ ] **Step 8: Implement `validation.rs`**

Create `crates/agent-contracts/src/validation.rs`:

```rust
use jsonschema::ValidationError;
use serde_json::Value;
use thiserror::Error;

use crate::SchemaName;

#[derive(Debug, Error)]
pub enum ContractError {
    #[error("schema source is invalid JSON: {0}")]
    InvalidSchemaJson(#[from] serde_json::Error),

    #[error("schema compilation failed: {0}")]
    SchemaCompilation(String),

    #[error("JSON failed schema validation: {0}")]
    Validation(String),
}

pub fn validate_json(schema_name: SchemaName, value: &Value) -> Result<(), ContractError> {
    let schema: Value = serde_json::from_str(schema_name.source())?;
    let validator = jsonschema::validator_for(&schema)
        .map_err(|err| ContractError::SchemaCompilation(err.to_string()))?;

    if let Err(err) = validator.validate(value) {
        return Err(ContractError::Validation(format_validation_error(err)));
    }

    Ok(())
}

fn format_validation_error(err: ValidationError<'_>) -> String {
    format!("{} at {}", err, err.instance_path())
}
```

- [ ] **Step 9: Export schema modules from `lib.rs`**

Modify `crates/agent-contracts/src/lib.rs` to this exact content:

```rust
pub mod artifacts;
pub mod events;
pub mod schemas;
pub mod validation;

pub use artifacts::{ManifestArtifact, TrustReportArtifact};
pub use events::{EventEnvelope, EventKind};
pub use schemas::SchemaName;
pub use validation::{ContractError, validate_json};
```

- [ ] **Step 10: Run contract tests**

Run:

```bash
cargo test -p agent-contracts
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add crates/agent-contracts Cargo.lock
git commit -m "feat: validate Rust contract schemas"
```

## Task 5: Create Compiling Skeleton Crates For Product Boundaries

```yaml agentrunway-task
task_id: task_005
title: Create Compiling Skeleton Crates For Product Boundaries
risk: medium
phase: implementation
dependencies: [task_004]
spec_refs: [S1.6, S1.10.1]
file_claims:
  - {path: crates/agent-store, mode: owned}
  - {path: crates/agent-runway, mode: owned}
  - {path: crates/agent-eval, mode: owned}
  - {path: crates/agent-adapters, mode: owned}
  - {path: crates/agent-server, mode: owned}
  - {path: Cargo.lock, mode: shared_append}
acceptance_commands:
  - test -f crates/agent-store/src/lib.rs && test -f crates/agent-runway/src/lib.rs && test -f crates/agent-eval/src/lib.rs && test -f crates/agent-adapters/src/lib.rs && test -f crates/agent-server/src/lib.rs
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `crates/agent-store/Cargo.toml`
- Create: `crates/agent-store/src/lib.rs`
- Create: `crates/agent-runway/Cargo.toml`
- Create: `crates/agent-runway/src/lib.rs`
- Create: `crates/agent-eval/Cargo.toml`
- Create: `crates/agent-eval/src/lib.rs`
- Create: `crates/agent-adapters/Cargo.toml`
- Create: `crates/agent-adapters/src/lib.rs`
- Create: `crates/agent-server/Cargo.toml`
- Create: `crates/agent-server/src/lib.rs`

- [ ] **Step 1: Run workspace tests and verify missing crates fail**

Run:

```bash
cargo test --workspace
```

Expected: FAIL because workspace members other than `agent-core` and `agent-contracts` do not exist.

- [ ] **Step 2: Create `agent-store`**

Create `crates/agent-store/Cargo.toml`:

```toml
[package]
name = "agent-store"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
authors.workspace = true

[dependencies]
agent-contracts.workspace = true
agent-core.workspace = true
```

Create `crates/agent-store/src/lib.rs`:

```rust
//! Durable artifact store boundary.
//!
//! Phase 1 only defines the crate boundary. Filesystem writes, SQLite indexes,
//! locks, query read models, and retention are implemented in the store phase.

pub const CRATE_BOUNDARY: &str = "agent-store";
```

- [ ] **Step 3: Create `agent-runway`**

Create `crates/agent-runway/Cargo.toml`:

```toml
[package]
name = "agent-runway"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
authors.workspace = true

[dependencies]
agent-contracts.workspace = true
agent-core.workspace = true
agent-store.workspace = true
```

Create `crates/agent-runway/src/lib.rs`:

```rust
//! Execution engine boundary.
//!
//! This crate owns plan parsing, safe-wave scheduling, worktrees, gates, merge,
//! recovery, checkpoints, and human decision packets.

pub const CRATE_BOUNDARY: &str = "agent-runway";
```

- [ ] **Step 4: Create `agent-eval`**

Create `crates/agent-eval/Cargo.toml`:

```toml
[package]
name = "agent-eval"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
authors.workspace = true

[dependencies]
agent-contracts.workspace = true
agent-core.workspace = true
agent-store.workspace = true
```

Create `crates/agent-eval/src/lib.rs`:

```rust
//! Evidence evaluation boundary.
//!
//! This crate owns deterministic checks, trust reports, failure projection, and
//! final-claim-versus-evidence judgment.

pub const CRATE_BOUNDARY: &str = "agent-eval";
```

- [ ] **Step 5: Create `agent-adapters`**

Create `crates/agent-adapters/Cargo.toml`:

```toml
[package]
name = "agent-adapters"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
authors.workspace = true

[dependencies]
agent-contracts.workspace = true
agent-core.workspace = true
```

Create `crates/agent-adapters/src/lib.rs`:

```rust
//! Process adapter boundary.
//!
//! This crate owns supervised Codex, Claude, local fake, and sandbox process
//! execution adapters.

pub const CRATE_BOUNDARY: &str = "agent-adapters";
```

- [ ] **Step 6: Create `agent-server`**

Create `crates/agent-server/Cargo.toml`:

```toml
[package]
name = "agent-server"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
authors.workspace = true

[dependencies]
agent-contracts.workspace = true
agent-core.workspace = true
agent-eval.workspace = true
agent-runway.workspace = true
agent-store.workspace = true
```

Create `crates/agent-server/src/lib.rs`:

```rust
//! Local HTTP API boundary.
//!
//! This crate owns API routing and dashboard asset serving. Runtime decisions
//! stay in library crates and are not implemented in the server boundary.

pub const CRATE_BOUNDARY: &str = "agent-server";
```

- [ ] **Step 7: Run workspace tests**

Run:

```bash
cargo test --workspace
```

Expected: FAIL because `agent-cli` is still missing.

- [ ] **Step 8: Commit**

```bash
git add crates/agent-store crates/agent-runway crates/agent-eval crates/agent-adapters crates/agent-server Cargo.lock
git commit -m "chore: add Rust product boundary crates"
```

## Task 6: Add Minimal `agent-cli` Binary

```yaml agentrunway-task
task_id: task_006
title: Add Minimal agent-cli Binary
risk: medium
phase: implementation
dependencies: [task_005]
spec_refs: [S1.6.8, S1.9.1, S1.10.1]
file_claims:
  - {path: crates/agent-cli, mode: owned}
  - {path: Cargo.lock, mode: shared_append}
acceptance_commands:
  - cargo test --workspace
required_skills: [test-driven-development]
serial: true
```

**Files:**
- Create: `crates/agent-cli/Cargo.toml`
- Create: `crates/agent-cli/src/lib.rs`
- Create: `crates/agent-cli/src/main.rs`
- Create: `crates/agent-cli/tests/cli_smoke.rs`

- [ ] **Step 1: Create CLI manifest**

Create `crates/agent-cli/Cargo.toml`:

```toml
[package]
name = "agent-cli"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
authors.workspace = true

[dependencies]
agent-contracts.workspace = true
agent-core.workspace = true
agent-eval.workspace = true
agent-runway.workspace = true
agent-server.workspace = true
agent-store.workspace = true

[dev-dependencies]
tempfile.workspace = true
```

- [ ] **Step 2: Write failing CLI smoke test**

Create `crates/agent-cli/tests/cli_smoke.rs`:

```rust
use std::process::Command;

#[test]
fn cli_prints_version() {
    let output = Command::new(env!("CARGO_BIN_EXE_agent-cli"))
        .arg("--version")
        .output()
        .expect("agent-cli binary should run");

    assert!(output.status.success());

    let stdout = String::from_utf8(output.stdout).unwrap();
    assert!(stdout.contains("agent-cli 0.1.0"));
}
```

- [ ] **Step 3: Run CLI tests and verify they fail**

Run:

```bash
cargo test -p agent-cli
```

Expected: FAIL because the crate and binary do not exist.

- [ ] **Step 4: Implement CLI library**

Create `crates/agent-cli/src/lib.rs`:

```rust
pub fn render_version() -> String {
    format!("agent-cli {}", env!("CARGO_PKG_VERSION"))
}
```

- [ ] **Step 5: Implement CLI binary**

Create `crates/agent-cli/src/main.rs`:

```rust
fn main() {
    let mut args = std::env::args().skip(1);

    match args.next().as_deref() {
        Some("--version") | Some("-V") => {
            println!("{}", agent_cli::render_version());
        }
        Some("--help") | Some("-h") | None => {
            println!("agent-cli 0.1.0");
            println!();
            println!("Usage: agent-cli [--version]");
            println!();
            println!("Phase 1 exposes only workspace and contract scaffolding.");
        }
        Some(arg) => {
            eprintln!("unknown argument: {arg}");
            std::process::exit(2);
        }
    }
}
```

- [ ] **Step 6: Run CLI tests**

Run:

```bash
cargo test -p agent-cli
```

Expected: PASS.

- [ ] **Step 7: Run workspace tests**

Run:

```bash
cargo test --workspace
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add crates/agent-cli Cargo.lock
git commit -m "feat: add minimal Rust CLI binary"
```

## Task 7: Add Web And Test Directory Markers

```yaml agentrunway-task
task_id: task_007
title: Add Web And Test Directory Markers
risk: low
phase: docs
dependencies: [task_006]
spec_refs: [S1.6.9, S1.9, S1.10.1]
file_claims:
  - {path: apps/lens-web/README.md, mode: owned}
  - {path: tests/fixtures/README.md, mode: owned}
  - {path: tests/e2e/README.md, mode: owned}
acceptance_commands:
  - test -f apps/lens-web/README.md && test -f tests/fixtures/README.md && test -f tests/e2e/README.md
required_skills: []
serial: true
```

**Files:**
- Create: `apps/lens-web/README.md`
- Create: `tests/fixtures/README.md`
- Create: `tests/e2e/README.md`

- [ ] **Step 1: Create web relocation note**

Create `apps/lens-web/README.md`:

```markdown
# Lens Web

This directory is the destination for the TypeScript/React dashboard in the
Full Rust Agent Platform rewrite.

Phase 1 keeps the existing dashboard under `AgentLens/web` unchanged. The web
app moves here only after the Rust server exposes the read API required by the
dashboard.

Runtime decisions, store mutation, evaluator judgment, and schema definitions
belong in Rust crates. This directory owns UI rendering and browser tests only.
```

- [ ] **Step 2: Create fixture directory note**

Create `tests/fixtures/README.md`:

```markdown
# Fixtures

This directory stores cross-crate JSON fixtures for the Rust platform.

Phase 1 keeps fixture coverage inside crate integration tests. Shared fixtures
move here when store, evaluator, and runtime tests need the same evidence
artifacts.
```

- [ ] **Step 3: Create e2e directory note**

Create `tests/e2e/README.md`:

```markdown
# End-To-End Tests

This directory stores full platform scenarios that exercise the Rust CLI,
contract validation, store, runtime, evaluator, server, and dashboard together.

Phase 1 creates the directory boundary only. Executable scenarios are added
when the local fake adapter and filesystem store exist.
```

- [ ] **Step 4: Commit**

```bash
git add apps/lens-web/README.md tests/fixtures/README.md tests/e2e/README.md
git commit -m "docs: mark platform app and test directories"
```

## Task 8: Final Verification For Phase 1

```yaml agentrunway-task
task_id: task_008
title: Final Verification For Phase 1
risk: low
phase: verification
dependencies: [task_007]
spec_refs: [S1.9.2, S1.9.3, S1.12]
file_claims:
  - {path: Cargo.toml, mode: read_only}
  - {path: crates, mode: read_only}
  - {path: apps, mode: read_only}
  - {path: tests, mode: read_only}
acceptance_commands:
  - cargo fmt --all -- --check
  - cargo clippy --workspace --all-targets -- -D warnings
  - cargo test --workspace
  - '! rg -n "python|pytest|pyproject|\\.py\\b" crates apps tests'
  - git diff --check
required_skills: []
serial: true
```

**Files:**
- No new files.
- Verify all files created by Tasks 1-7.

- [ ] **Step 1: Format check**

Run:

```bash
cargo fmt --all -- --check
```

Expected: PASS.

- [ ] **Step 2: Clippy check**

Run:

```bash
cargo clippy --workspace --all-targets -- -D warnings
```

Expected: PASS.

- [ ] **Step 3: Rust test suite**

Run:

```bash
cargo test --workspace
```

Expected: PASS.

- [ ] **Step 4: Confirm no Python was added to the new Rust product tree**

Run:

```bash
! rg -n "python|pytest|pyproject|\\.py\\b" crates apps tests
```

Expected: no matches.

- [ ] **Step 5: Repository diff check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 6: Commit verification note if any files changed**

If formatting changed files, commit them:

```bash
git add Cargo.toml Cargo.lock rust-toolchain.toml rustfmt.toml .gitignore crates apps
git commit -m "chore: verify Rust platform phase 1"
```

If no files changed, do not create an empty commit.

## Execution Notes

- Current local machine may not have Rust installed. If `cargo` is unavailable, install Rust through `rustup` before Task 1 and rerun the first command.
- The `jsonschema` crate version in this plan is `0.46`, which requires Rust 1.83 or newer. The workspace uses Rust 2024 edition with `rust-version = "1.85"`.
- Do not delete current Python files during this plan. Python removal is a separate legacy-removal plan after the Rust product reaches runtime parity.
- Do not commit `.DS_Store`, `.agentlens/`, `.claude/`, `.codex-orchestrator/`, `.orchestrator/`, `.superpowers/`, `node_modules/`, `.venv/`, or `target/`.

## Handoff Criteria

Phase 1 is complete when:

- `cargo test --workspace` passes.
- `cargo clippy --workspace --all-targets -- -D warnings` passes.
- `cargo fmt --all -- --check` passes.
- `agent-core` exposes validated domain IDs, outcome enums, clocks, and platform home paths.
- `agent-contracts` exposes event, manifest, and trust report artifacts plus schema validation.
- All approved product boundary crates exist and compile.
- `agent-cli --version` has a passing smoke test.
- `apps/lens-web/README.md` documents the future dashboard destination.
- `tests/fixtures/README.md` and `tests/e2e/README.md` document shared fixture and full-platform test boundaries.
- No Python implementation files or Python packaging were added under `crates`, `apps`, or `tests`.
