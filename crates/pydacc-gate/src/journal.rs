//! Minimal journal enforcement: parse the flat-TOML subset and check the
//! gate-before-landed invariant (a landed event requires a preceding gate
//! event with the same tree).

pub struct Event {
    pub kind: String,
    pub fields: Vec<(String, String)>,
}

impl Event {
    pub fn get(&self, key: &str) -> Option<&str> {
        self.fields
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_str())
    }
}

pub fn parse(text: &str) -> Result<Vec<Event>, String> {
    let mut events: Vec<Event> = Vec::new();
    let mut current: Option<Vec<(String, String)>> = None;
    for (i, raw) in text.lines().enumerate() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let n = i + 1;
        if line == "[[events]]" {
            if let Some(fields) = current.take() {
                events.push(Event {
                    kind: String::new(),
                    fields,
                });
            }
            current = Some(Vec::new());
            continue;
        }
        let cur = current
            .as_mut()
            .ok_or_else(|| format!("line {n}: expected `[[events]]` before the first event"))?;
        let (key, value) = parse_pair(line, n)?;
        if cur.iter().any(|(k, _)| *k == key) {
            return Err(format!("line {n}: key `{key}` is repeated"));
        }
        cur.push((key, value));
    }
    if let Some(fields) = current {
        events.push(Event {
            kind: String::new(),
            fields,
        });
    }
    if events.is_empty() {
        return Err("the journal has no events".to_string());
    }
    for event in &mut events {
        event.kind = event.get("event").ok_or("no event field")?.to_string();
    }
    check_invariants(&events)?;
    Ok(events)
}

fn parse_pair(line: &str, n: usize) -> Result<(String, String), String> {
    let (key, value) = line
        .split_once('=')
        .ok_or_else(|| format!("line {n}: expected `key = \"string\"`"))?;
    let key = key.trim();
    if key.is_empty()
        || !key.starts_with(|c: char| c.is_ascii_lowercase())
        || !key
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
    {
        return Err(format!(
            "line {n}: key `{key}` is lowercase latin letters, digits and `_`, starting with a letter"
        ));
    }
    let value = parse_string(value.trim(), n)?;
    Ok((key.to_string(), value))
}

fn parse_string(value: &str, n: usize) -> Result<String, String> {
    let inner = value
        .strip_prefix('"')
        .and_then(|s| s.strip_suffix('"'))
        .ok_or_else(|| {
            format!("line {n}: a value is a double-quoted string and nothing else on the line")
        })?;
    let mut out = String::new();
    let mut chars = inner.chars();
    while let Some(c) = chars.next() {
        match c {
            '\\' => match chars.next() {
                Some('"') => out.push('"'),
                Some('\\') => out.push('\\'),
                Some('n') => out.push('\n'),
                Some('t') => out.push('\t'),
                _ => {
                    return Err(format!(
                        "line {n}: a string allows only the escapes \\\" \\\\ \\n \\t"
                    ))
                }
            },
            '"' => return Err(format!("line {n}: an unescaped quote inside a string")),
            c if c.is_control() => {
                return Err(format!("line {n}: a control character in a string"))
            }
            c => out.push(c),
        }
    }
    Ok(out)
}

fn is_hash(value: &str) -> bool {
    (value.len() == 40 || value.len() == 64)
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// The load-bearing invariant: a landed event requires a preceding gate event
/// with the same tree.
fn check_invariants(events: &[Event]) -> Result<(), String> {
    for (idx, event) in events.iter().enumerate() {
        if event.kind != "landed" {
            continue;
        }
        let tree = event.get("tree").ok_or("landed event has no tree")?;
        if !is_hash(tree) {
            return Err(format!("landed event: field tree is a git hash, not {tree:?}"));
        }
        let commit = event.get("commit").unwrap_or("");
        if commit != "self" && !is_hash(commit) {
            return Err(format!(
                "landed event: field commit is a git hash, not {commit:?}"
            ));
        }
        let proven = events[..idx]
            .iter()
            .any(|prev| prev.kind == "gate" && prev.get("tree") == Some(tree));
        if !proven {
            return Err(format!("landing without proof: no gate event with tree {tree}"));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const TREE: &str = "0123456789abcdef0123456789abcdef01234567";

    #[test]
    fn landed_requires_a_preceding_gate() {
        let good = format!(
            "[[events]]\nevent = \"gate\"\nwork = \"w-001\"\nat = \"2026-09-11T03:15:00Z\"\ngate = \"commit\"\ntree = \"{TREE}\"\npassed = \"1\"\ntotal = \"1\"\nattacks = \"0\"\n[[events]]\nevent = \"landed\"\nwork = \"w-001\"\nat = \"2026-09-11T03:15:00Z\"\ncommit = \"self\"\ntree = \"{TREE}\"\n"
        );
        assert!(parse(&good).is_ok());

        let bad = format!(
            "[[events]]\nevent = \"landed\"\nwork = \"w-001\"\nat = \"2026-09-11T03:15:00Z\"\ncommit = \"self\"\ntree = \"{TREE}\"\n"
        );
        assert!(parse(&bad).is_err());
    }

    #[test]
    fn bad_hash_is_rejected() {
        let text = "[[events]]\nevent = \"landed\"\nwork = \"w-001\"\nat = \"2026-09-11T03:15:00Z\"\ncommit = \"XYZ\"\ntree = \"0123456789abcdef0123456789abcdef01234567\"\n";
        assert!(parse(text).is_err());
    }
}
