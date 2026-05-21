use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CapturePolicy {
    pub stdout_limit_bytes: usize,
    pub stderr_limit_bytes: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(untagged)]
pub enum StdinPolicy {
    Closed(String),
    Text { text: String },
}

impl StdinPolicy {
    pub fn is_closed(&self) -> bool {
        matches!(self, Self::Closed(value) if value == "closed")
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct FilesystemPolicy {
    pub read: Vec<String>,
    pub write: Vec<String>,
    pub deny: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(untagged)]
pub enum NetworkPolicy {
    Named(String),
    Allow { allow: Vec<String> },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PermissionProfile {
    pub filesystem: FilesystemPolicy,
    pub network: NetworkPolicy,
    pub command_prefixes: Vec<String>,
    pub escalation_reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExecutionRequest {
    pub schema: String,
    pub request_id: String,
    pub run_id: String,
    pub task_id: String,
    pub kind: Option<String>,
    pub cwd: String,
    pub argv: Vec<String>,
    pub env: BTreeMap<String, String>,
    pub timeout_ms: u64,
    pub stdin: StdinPolicy,
    pub tty: bool,
    pub permission_profile: Option<PermissionProfile>,
    pub capture: CapturePolicy,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PermissionDecision {
    pub allowed: bool,
    pub reason: String,
    pub denied_by: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExecutionResult {
    pub schema: String,
    pub request_id: String,
    pub run_id: String,
    pub task_id: String,
    pub exit_code: Option<i32>,
    pub signal: Option<String>,
    pub timed_out: bool,
    pub stdout: String,
    pub stderr: String,
    pub stdout_truncated: bool,
    pub stderr_truncated: bool,
    pub stdout_sha256: String,
    pub stderr_sha256: String,
    pub changed_files: Vec<String>,
    pub permission_decision: Option<PermissionDecision>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_closed_stdin() {
        let request: ExecutionRequest = serde_json::from_str(
            r#"{
              "schema":"kernel.execution_request.v1",
              "request_id":"exec_demo",
              "run_id":"run_demo",
              "task_id":"task_demo",
              "cwd":".",
              "argv":["printf","hello"],
              "env":{},
              "timeout_ms":1000,
              "stdin":"closed",
              "tty":false,
              "capture":{"stdout_limit_bytes":100,"stderr_limit_bytes":100}
            }"#,
        )
        .expect("request should parse");
        assert!(request.stdin.is_closed());
    }
}
