mod hash;
mod hook;
mod journal;

use std::path::Path;
use std::process::ExitCode;

const JOURNAL: &str = "journal";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let root = std::env::current_dir().unwrap_or_default();
    match args.first().map(String::as_str) {
        Some("hash") => {
            let rev = args.get(1).map(String::as_str).unwrap_or("HEAD");
            match hash::content_hash(&root, JOURNAL, rev) {
                Some(h) => {
                    println!("{h}");
                    ExitCode::SUCCESS
                }
                None => {
                    eprintln!("journal hash: revision {rev} cannot be read");
                    ExitCode::from(2)
                }
            }
        }
        Some("check") => check(&root),
        Some("hooks") => match args.get(1).map(String::as_str) {
            Some("install") => {
                let force = args.get(2).map(String::as_str) == Some("--force");
                match hook::install(&root, force) {
                    Ok(()) => ExitCode::SUCCESS,
                    Err(e) => {
                        eprintln!("hooks install: {e}");
                        ExitCode::from(2)
                    }
                }
            }
            _ => {
                eprintln!("hooks: install [--force]");
                ExitCode::from(2)
            }
        },
        Some("hook") => match args.get(1).map(String::as_str) {
            Some("pre-commit") => match hook::pre_commit(&root, JOURNAL) {
                Ok(()) => ExitCode::SUCCESS,
                Err(e) => {
                    eprintln!("pre-commit: {e}");
                    ExitCode::from(1)
                }
            },
            _ => {
                eprintln!("hook: pre-commit");
                ExitCode::from(2)
            }
        },
        _ => {
            eprintln!("pydacc-gate: hash | check | hooks install | hook pre-commit");
            ExitCode::from(2)
        }
    }
}

fn check(root: &Path) -> ExitCode {
    let text = match std::fs::read_to_string(root.join(format!("{JOURNAL}.toml"))) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("check: {e}");
            return ExitCode::from(2);
        }
    };
    match journal::parse(&text) {
        Ok(_) => {
            println!("journal ok");
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("journal invalid: {e}");
            ExitCode::from(1)
        }
    }
}
