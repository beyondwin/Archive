use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ArtifactSeal {
    pub path: PathBuf,
    pub byte_length: u64,
    pub sha256: String,
}

pub fn seal_existing(path: impl AsRef<Path>) -> io::Result<ArtifactSeal> {
    let data = fs::read(&path)?;
    Ok(ArtifactSeal {
        path: path.as_ref().to_path_buf(),
        byte_length: data.len() as u64,
        sha256: digest(&data),
    })
}

pub fn write_and_seal(path: impl AsRef<Path>, data: &[u8]) -> io::Result<ArtifactSeal> {
    if let Some(parent) = path.as_ref().parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&path, data)?;
    seal_existing(path)
}

fn digest(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    hex::encode(hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn seals_artifact_metadata() {
        let path = std::env::temp_dir().join("waygent-artifact-seal.txt");
        let seal = write_and_seal(&path, b"hello").expect("seal should write");
        assert_eq!(seal.byte_length, 5);
        assert_eq!(seal.sha256.len(), 64);
    }
}
