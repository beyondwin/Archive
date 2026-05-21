use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PatchDiagnostic {
    pub path: String,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PatchDryRun {
    pub changed_files: Vec<String>,
    pub diagnostics: Vec<PatchDiagnostic>,
}

pub fn dry_run_patch(worktree: &Path, patch: &str) -> PatchDryRun {
    let mut changed_files = Vec::new();
    let mut diagnostics = Vec::new();
    for line in patch.lines() {
        if !line.starts_with("+++ b/") && !line.starts_with("--- a/") {
            continue;
        }
        let path = line[6..].to_string();
        if path == "/dev/null" {
            continue;
        }
        if escapes_worktree(worktree, &path) {
            diagnostics.push(PatchDiagnostic {
                path,
                message: "patch path escapes candidate worktree".to_string(),
            });
        } else if !changed_files.contains(&path) {
            changed_files.push(path);
        }
    }
    PatchDryRun {
        changed_files,
        diagnostics,
    }
}

fn escapes_worktree(worktree: &Path, path: &str) -> bool {
    let candidate = worktree.join(path);
    normalize(&candidate)
        .strip_prefix(normalize(worktree))
        .is_err()
}

fn normalize(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            std::path::Component::ParentDir => {
                out.pop();
            }
            std::path::Component::CurDir => {}
            other => out.push(other.as_os_str()),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_paths_outside_worktree() {
        let result = dry_run_patch(
            Path::new("/tmp/worktree"),
            "--- a/../../secret\n+++ b/../../secret\n",
        );
        assert!(!result.diagnostics.is_empty());
    }
}
