use serde_json::Value;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::Path;

pub fn append_event(path: impl AsRef<Path>, event: &Value) -> io::Result<()> {
    if event.is_null() || event.as_object().is_some_and(|object| object.is_empty()) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "event journal refuses empty payloads",
        ));
    }
    if let Some(parent) = path.as_ref().parent() {
        fs::create_dir_all(parent)?;
    }
    let mut file = OpenOptions::new().create(true).append(true).open(path)?;
    writeln!(file, "{event}")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn refuses_empty_event_payload() {
        let path = std::env::temp_dir().join("waygent-empty-event.jsonl");
        assert!(append_event(path, &serde_json::json!({})).is_err());
    }
}
