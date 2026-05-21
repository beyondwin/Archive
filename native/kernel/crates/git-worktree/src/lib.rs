use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;

pub fn validate_owned_run_id(run_id: &str) -> io::Result<()> {
    if run_id.is_empty()
        || run_id.contains("..")
        || run_id.contains('/')
        || run_id.contains('\\')
        || run_id.starts_with('-')
    {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "unsafe run id"));
    }
    Ok(())
}

pub fn validate_owned_branch(branch: &str) -> io::Result<()> {
    if !branch.starts_with("waygent/")
        || branch.contains("..")
        || branch.contains('\\')
        || branch.starts_with('-')
        || branch.ends_with('/')
    {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "unsafe branch"));
    }
    Ok(())
}

pub fn create_run_main(source: &Path, target: &Path, branch: &str) -> io::Result<()> {
    validate_owned_branch(branch)?;
    run_git(source, ["worktree", "add", "-b", branch], Some(target))
}

pub fn checkpoint_commit(worktree: &Path, message: &str) -> io::Result<()> {
    run_git(worktree, ["add", "-A"], None)?;
    run_git(worktree, ["commit", "-m", message], None)
}

pub fn owned_cleanup_path(root: &Path, run_id: &str) -> io::Result<PathBuf> {
    validate_owned_run_id(run_id)?;
    Ok(root.join(run_id))
}

fn run_git<const N: usize>(
    cwd: &Path,
    args: [&str; N],
    extra_path: Option<&Path>,
) -> io::Result<()> {
    let mut command = Command::new("git");
    command.current_dir(cwd).args(args);
    if let Some(path) = extra_path {
        command.arg(path);
    }
    let status = command.status()?;
    if status.success() {
        Ok(())
    } else {
        Err(io::Error::other("git command failed"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn refuses_unowned_cleanup_ids() {
        assert!(validate_owned_run_id("../other").is_err());
        assert!(validate_owned_run_id("run_ok").is_ok());
    }

    #[test]
    fn accepts_waygent_owned_branch_names() {
        assert!(validate_owned_branch("waygent/run_demo/task_demo").is_ok());
        assert!(validate_owned_branch("../outside").is_err());
        assert!(validate_owned_branch("-bad").is_err());
    }

    #[test]
    fn refuses_non_waygent_owned_branch_names() {
        assert!(validate_owned_branch("codex/run/task").is_err());
        assert!(validate_owned_branch("kws-cpe/run/task").is_err());
    }
}
