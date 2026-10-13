use std::fs;
use std::path::Path;
use std::process::Command;

const HOOK_MARKER: &str = "pydacc rules (hook)";
const HOOKS_DIR: &str = ".githooks";
const PRE_COMMIT: &str = "pre-commit";

/// Write the one-liner hook and point git at it. A foreign file refuses the
/// install until `--force`, so a partial install can't look complete.
pub fn install(root: &Path, force: bool) -> Result<(), String> {
    let dir = root.join(HOOKS_DIR);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let path = dir.join(PRE_COMMIT);
    if path.exists() && !force {
        let text = fs::read_to_string(&path).unwrap_or_default();
        if !text.contains(HOOK_MARKER) {
            return Err(format!(
                "{HOOKS_DIR}/{PRE_COMMIT} is not written by pydacc — use --force to replace it"
            ));
        }
    }
    let text = format!(
        "#!/bin/sh\n# {HOOK_MARKER}: calls the installed pydacc-gate.\nexec pydacc-gate hook pre-commit\n"
    );
    fs::write(&path, text).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perm = fs::metadata(&path).map_err(|e| e.to_string())?.permissions();
        perm.set_mode(0o755);
        fs::set_permissions(&path, perm).map_err(|e| e.to_string())?;
    }
    let status = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(["config", "core.hooksPath", HOOKS_DIR])
        .status()
        .map_err(|e| e.to_string())?;
    if !status.success() {
        return Err("core.hooksPath is not set".to_string());
    }
    println!("hook {PRE_COMMIT}: written");
    println!("core.hooksPath = {HOOKS_DIR}");
    Ok(())
}

/// pre-commit: materialize the commit index to a temp tree, compute the content
/// hash and verify the journal there — the gate checks what will be committed,
/// not the working tree.
pub fn pre_commit(root: &Path, journal: &str) -> Result<(), String> {
    let work = root.join(".git/pydacc-gate");
    let tree = work.join("tree");
    let _ = fs::remove_dir_all(&work);
    fs::create_dir_all(&tree).map_err(|e| e.to_string())?;

    let prefix = format!("--prefix={}/", tree.display());
    let status = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(["checkout-index", "--all", &prefix])
        .status()
        .map_err(|e| e.to_string())?;
    if !status.success() {
        return Err("git checkout-index did not export the commit index".to_string());
    }

    let hash = crate::hash::index_hash(root, journal).ok_or("cannot hash the commit index")?;

    let journal_file = tree.join(format!("{journal}.toml"));
    if journal_file.exists() {
        let text = fs::read_to_string(&journal_file).map_err(|e| e.to_string())?;
        crate::journal::parse(&text)?;
    }

    println!(
        "pre-commit: tree without journal checked ({})",
        &hash[..hash.len().min(12)]
    );
    Ok(())
}
