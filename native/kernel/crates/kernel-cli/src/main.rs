use kernel_protocol::ExecutionRequest;
use std::fs;
use std::io::{self, Read};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let input = match std::env::args().nth(1) {
        Some(path) => fs::read_to_string(path)?,
        None => {
            let mut text = String::new();
            io::stdin().read_to_string(&mut text)?;
            text
        }
    };
    let request: ExecutionRequest = serde_json::from_str(&input)?;
    let result = process_supervisor::execute(&request)?;
    println!("{}", serde_json::to_string_pretty(&result)?);
    Ok(())
}
