use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

/// Content hash of a git tree without the journal: SHA-1 (git blob) of the
/// filtered `git ls-tree -r -z --full-tree` listing, mirroring dacc's
/// `proof::content_hash`.
pub fn content_hash(root: &Path, journal: &str, tree: &str) -> Option<String> {
    let listing = git(root, &["ls-tree", "-r", "-z", "--full-tree", tree])?;
    let journal_dir = format!("{journal}/");
    let journal_file = format!("{journal}.toml");
    let mut kept: Vec<u8> = Vec::new();
    for entry in listing.split(|b| *b == 0) {
        if entry.is_empty() {
            continue;
        }
        let path = entry
            .iter()
            .position(|b| *b == b'\t')
            .map_or(entry, |i| &entry[i + 1..]);
        let path = String::from_utf8_lossy(path);
        if path.starts_with(&journal_dir) || path == journal_file {
            continue;
        }
        kept.extend_from_slice(entry);
        kept.push(0);
    }
    git_hash_stdin(root, &kept)
}

/// Hash of the tree being built (the git index), minus the journal.
pub fn index_hash(root: &Path, journal: &str) -> Option<String> {
    let tree = git(root, &["write-tree"])?;
    let tree = String::from_utf8_lossy(&tree).trim().to_string();
    content_hash(root, journal, &tree)
}

fn git(root: &Path, args: &[&str]) -> Option<Vec<u8>> {
    let out = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .ok()?;
    out.status.success().then_some(out.stdout)
}

fn git_hash_stdin(root: &Path, data: &[u8]) -> Option<String> {
    let mut child = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(["hash-object", "--stdin"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .ok()?;
    child.stdin.take()?.write_all(data).ok()?;
    let out = child.wait_with_output().ok()?;
    out.status
        .success()
        .then(|| String::from_utf8_lossy(&out.stdout).trim().to_string())
}
