use kernel_protocol::{ExecutionRequest, PermissionDecision};

pub fn evaluate(request: &ExecutionRequest) -> PermissionDecision {
    let Some(profile) = &request.permission_profile else {
        return PermissionDecision {
            allowed: true,
            reason: "no permission profile supplied".to_string(),
            denied_by: None,
        };
    };
    let prefix = request.argv.first().cloned().unwrap_or_default();
    if !profile.command_prefixes.contains(&prefix) {
        return PermissionDecision {
            allowed: false,
            reason: format!("command prefix {prefix} is not allowed"),
            denied_by: Some("command_prefixes".to_string()),
        };
    }
    if profile
        .filesystem
        .deny
        .iter()
        .any(|denied| request.cwd == *denied || request.cwd.starts_with(&format!("{denied}/")))
    {
        return PermissionDecision {
            allowed: false,
            reason: "cwd is denied by filesystem policy".to_string(),
            denied_by: Some("filesystem.deny".to_string()),
        };
    }
    PermissionDecision {
        allowed: true,
        reason: "allowed by sandbox policy".to_string(),
        denied_by: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use kernel_protocol::{
        CapturePolicy, ExecutionRequest, FilesystemPolicy, NetworkPolicy, PermissionProfile,
        StdinPolicy,
    };
    use std::collections::BTreeMap;

    #[test]
    fn denies_disallowed_prefix() {
        let request = ExecutionRequest {
            schema: "kernel.execution_request.v1".into(),
            request_id: "exec_demo".into(),
            run_id: "run_demo".into(),
            task_id: "task_demo".into(),
            kind: Some("process.exec".into()),
            cwd: ".".into(),
            argv: vec!["rm".into(), "-rf".into(), "x".into()],
            env: BTreeMap::new(),
            timeout_ms: 1000,
            stdin: StdinPolicy::Closed("closed".into()),
            tty: false,
            permission_profile: Some(PermissionProfile {
                filesystem: FilesystemPolicy {
                    read: vec![".".into()],
                    write: vec![],
                    deny: vec![".git/config".into()],
                },
                network: NetworkPolicy::Named("disabled".into()),
                command_prefixes: vec!["bun".into()],
                escalation_reason: None,
            }),
            capture: CapturePolicy {
                stdout_limit_bytes: 100,
                stderr_limit_bytes: 100,
            },
        };
        assert!(!evaluate(&request).allowed);
    }
}
