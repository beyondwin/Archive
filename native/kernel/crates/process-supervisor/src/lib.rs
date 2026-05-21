use kernel_protocol::{ExecutionRequest, ExecutionResult, PermissionDecision, StdinPolicy};
use sha2::{Digest, Sha256};
use std::io::{self, Write};
use std::process::{Command, Stdio};
use std::time::Duration;
use wait_timeout::ChildExt;

pub fn execute(request: &ExecutionRequest) -> io::Result<ExecutionResult> {
    let mut command = Command::new(request.argv.first().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "execution request requires argv",
        )
    })?);
    command.args(request.argv.iter().skip(1));
    command.current_dir(&request.cwd);
    command.envs(&request.env);
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());
    match &request.stdin {
        StdinPolicy::Closed(_) => {
            command.stdin(Stdio::null());
        }
        StdinPolicy::Text { .. } => {
            command.stdin(Stdio::piped());
        }
    }

    let mut child = command.spawn()?;
    if let StdinPolicy::Text { text } = &request.stdin
        && let Some(mut stdin) = child.stdin.take()
    {
        stdin.write_all(text.as_bytes())?;
    }

    let timeout = Duration::from_millis(request.timeout_ms);
    let timed_out = match child.wait_timeout(timeout)? {
        Some(_) => false,
        None => {
            child.kill()?;
            true
        }
    };
    let output = child.wait_with_output()?;
    let stdout_full = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr_full = String::from_utf8_lossy(&output.stderr).to_string();
    let stdout = bounded(&stdout_full, request.capture.stdout_limit_bytes);
    let stderr = bounded(&stderr_full, request.capture.stderr_limit_bytes);

    Ok(ExecutionResult {
        schema: "kernel.execution_result.v1".to_string(),
        request_id: request.request_id.clone(),
        run_id: request.run_id.clone(),
        task_id: request.task_id.clone(),
        exit_code: output.status.code(),
        signal: None,
        timed_out,
        stdout: stdout.0,
        stderr: stderr.0,
        stdout_truncated: stdout.1,
        stderr_truncated: stderr.1,
        stdout_sha256: digest(&stdout_full),
        stderr_sha256: digest(&stderr_full),
        changed_files: Vec::new(),
        permission_decision: Some(PermissionDecision {
            allowed: true,
            reason: "process-supervisor executed request".to_string(),
            denied_by: None,
        }),
    })
}

fn bounded(text: &str, limit: usize) -> (String, bool) {
    if text.len() <= limit {
        return (text.to_string(), false);
    }
    let mut end = limit;
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    (text[..end].to_string(), true)
}

fn digest(text: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(text.as_bytes());
    hex::encode(hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    use kernel_protocol::{CapturePolicy, ExecutionRequest, StdinPolicy};
    use std::collections::BTreeMap;

    #[test]
    fn bounds_output_and_marks_truncation() {
        let request = request(vec!["printf".into(), "hello".into()], 2);
        let result = execute(&request).expect("printf should execute");
        assert_eq!(result.stdout, "he");
        assert!(result.stdout_truncated);
        assert_eq!(result.changed_files, Vec::<String>::new());
    }

    fn request(argv: Vec<String>, limit: usize) -> ExecutionRequest {
        ExecutionRequest {
            schema: "kernel.execution_request.v1".to_string(),
            request_id: "exec_demo".to_string(),
            run_id: "run_demo".to_string(),
            task_id: "task_demo".to_string(),
            kind: Some("process.exec".to_string()),
            cwd: ".".to_string(),
            argv,
            env: BTreeMap::new(),
            timeout_ms: 1000,
            stdin: StdinPolicy::Closed("closed".to_string()),
            tty: false,
            permission_profile: None,
            capture: CapturePolicy {
                stdout_limit_bytes: limit,
                stderr_limit_bytes: limit,
            },
        }
    }
}
