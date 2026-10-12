//! The path jail for every tool that takes a file path. Blender and this server
//! run as the user, so a path an agent names could otherwise read or write
//! anything the user can. Each path is resolved here, symlinks included, and
//! refused unless it lands under a root: a write under BLENDER_WRITE_ROOTS, a
//! read under those or BLENDER_READ_ROOTS. The resolved path, not the one the
//! agent wrote, is what the tool then uses.
//!
//! Portable by construction: root lists split like PATH on the platform
//! (std::env::split_paths: ':' on Unix, ';' on Windows), the home directory is
//! HOME or USERPROFILE, and Windows' verbatim \\?\C:\ prefix from canonicalize
//! is dropped so Blender is handed an ordinary path.
//!
//! Declared with rust_file / rust_fn (from: :blender_jail). The DSL has no
//! filesystem calls of its own, and canonicalize is the whole point.

use std::path::{Path, PathBuf};

/// Resolve `path` for `mode` ("read" or "write"). A write must land under a
/// write root; a read under a write root or a read root, and the file must
/// exist. A relative `path` lands under the first write root (the first read
/// root when there is none). Missing directories below an existing one are
/// allowed for a write, since the tools create them.
///
/// Returns the resolved absolute path, or a sentence starting "refused:" that
/// the caller raises as is.
pub fn jail_path(path: impl AsRef<str>, write_roots: impl AsRef<str>, read_roots: impl AsRef<str>, mode: impl AsRef<str>) -> String {
    let write = mode.as_ref() == "write";
    match resolve(path.as_ref(), &roots(write_roots.as_ref()), &roots(read_roots.as_ref()), write) {
        Ok(resolved) => resolved.to_string_lossy().into_owned(),
        Err(why) => format!("refused: {why}"),
    }
}

/// The roots in `list` that exist, resolved, one per line: what Blender is
/// handed so its checks compare against the same directories as this file's.
pub fn jail_roots(list: impl AsRef<str>) -> String {
    roots(list.as_ref()).iter().map(|root| root.to_string_lossy().into_owned()).collect::<Vec<_>>().join("\n")
}

fn roots(list: &str) -> Vec<PathBuf> {
    std::env::split_paths(list)
        .filter(|root| !root.as_os_str().is_empty())
        .filter_map(|root| std::fs::canonicalize(expand_home(&root.to_string_lossy())).ok())
        .map(plain)
        .collect()
}

fn expand_home(path: &str) -> PathBuf {
    let rest = if path == "~" { Some("") } else { path.strip_prefix("~/").or_else(|| path.strip_prefix("~\\")) };
    if let Some(rest) = rest {
        if let Some(home) = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")) {
            return PathBuf::from(home).join(rest);
        }
    }
    PathBuf::from(path)
}

/// canonicalize on Windows answers \\?\C:\dir; Blender and most programs want
/// C:\dir. Other platforms pass through.
fn plain(path: PathBuf) -> PathBuf {
    #[cfg(windows)]
    {
        let text = path.to_string_lossy();
        if let Some(rest) = text.strip_prefix(r"\\?\") {
            if rest.as_bytes().get(1) == Some(&b':') {
                return PathBuf::from(rest);
            }
        }
    }
    path
}

fn under(path: &Path, roots: &[PathBuf]) -> bool {
    roots.iter().any(|root| path.starts_with(root))
}

fn shown(roots: &[PathBuf]) -> String {
    if roots.is_empty() {
        return "none".to_string();
    }
    roots.iter().map(|root| root.display().to_string()).collect::<Vec<_>>().join(", ")
}

fn resolve(path: &str, write_roots: &[PathBuf], read_roots: &[PathBuf], write: bool) -> Result<PathBuf, String> {
    let Some(base_root) = write_roots.first().or_else(|| read_roots.first()) else {
        return Err("no file root exists; set BLENDER_WRITE_ROOTS (and BLENDER_READ_ROOTS) to existing directories".to_string());
    };
    let path = path.trim();
    if path.is_empty() {
        return Err("the path is empty".to_string());
    }
    let asked = expand_home(path);
    let asked = if asked.is_absolute() { asked } else { base_root.join(asked) };

    // Walk up to the longest prefix that exists (a dangling symlink counts as
    // existing, so canonicalize refuses it below) and keep the missing names.
    // A missing part that is ".." has no file_name, so it is refused here
    // rather than resolved against a directory that is not there.
    let mut base = asked.clone();
    let mut missing = Vec::new();
    while std::fs::symlink_metadata(&base).is_err() {
        match (base.file_name(), base.parent()) {
            (Some(name), Some(parent)) => {
                missing.push(name.to_owned());
                base = parent.to_path_buf();
            }
            _ => return Err(format!("{path} has a part that does not exist")),
        }
    }
    if !write && !missing.is_empty() {
        return Err(format!("no file at {path}"));
    }
    let mut resolved = plain(std::fs::canonicalize(&base).map_err(|e| format!("cannot resolve {path}: {e}"))?);
    for name in missing.iter().rev() {
        resolved.push(name);
    }
    if write && !under(&resolved, write_roots) {
        return Err(format!("{} is outside the write roots ({}); BLENDER_WRITE_ROOTS sets them", resolved.display(), shown(write_roots)));
    }
    if !write && !under(&resolved, write_roots) && !under(&resolved, read_roots) {
        return Err(format!(
            "{} is outside the file roots (write: {}; read: {}); BLENDER_WRITE_ROOTS and BLENDER_READ_ROOTS set them",
            resolved.display(),
            shown(write_roots),
            shown(read_roots)
        ));
    }
    if !write && !resolved.is_file() {
        return Err(format!("{} is not a file", resolved.display()));
    }
    Ok(resolved)
}

#[cfg(test)]
mod tests {
    use super::{jail_path, jail_roots};
    use std::path::PathBuf;

    fn scratch(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("blender_jail_{tag}_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("root").join("sub")).unwrap();
        std::fs::create_dir_all(dir.join("library")).unwrap();
        std::fs::write(dir.join("root").join("sub").join("a.png"), b"x").unwrap();
        std::fs::write(dir.join("library").join("t.png"), b"x").unwrap();
        std::fs::write(dir.join("outside.png"), b"x").unwrap();
        super::plain(std::fs::canonicalize(&dir).unwrap())
    }

    fn s(path: &PathBuf) -> String {
        path.to_string_lossy().into_owned()
    }

    #[test]
    fn reads_inside_either_root_and_refuses_outside() {
        let dir = scratch("read");
        let (root, library) = (dir.join("root"), dir.join("library"));
        let (w, r) = (s(&root), s(&library));
        assert_eq!(jail_path("sub/a.png", &w, &r, "read"), s(&root.join("sub").join("a.png")));
        assert_eq!(jail_path(s(&library.join("t.png")), &w, &r, "read"), s(&library.join("t.png")));
        assert!(jail_path(s(&dir.join("outside.png")), &w, &r, "read").starts_with("refused:"));
        assert!(jail_path("sub/../../outside.png", &w, &r, "read").starts_with("refused:"));
        assert!(jail_path("sub", &w, &r, "read").starts_with("refused:"));
    }

    #[test]
    fn writes_only_under_write_roots() {
        let dir = scratch("write");
        let (root, library) = (dir.join("root"), dir.join("library"));
        let (w, r) = (s(&root), s(&library));
        assert_eq!(jail_path("renders/new/x.png", &w, &r, "write"), s(&root.join("renders").join("new").join("x.png")));
        assert!(jail_path(s(&library.join("x.png")), &w, &r, "write").starts_with("refused:"));
        assert!(jail_path("nope/../../x.png", &w, &r, "write").starts_with("refused:"));
        assert!(jail_path("x.png", "", &r, "write").starts_with("refused:"));
    }

    #[test]
    fn root_lists_split_like_path() {
        let dir = scratch("list");
        let list = std::env::join_paths([dir.join("root"), dir.join("missing"), dir.join("library")]).unwrap();
        assert_eq!(jail_roots(list.to_string_lossy()), format!("{}\n{}", s(&dir.join("root")), s(&dir.join("library"))));
    }

    #[cfg(unix)]
    #[test]
    fn writes_not_through_links() {
        let dir = scratch("links");
        let root = dir.join("root");
        let w = s(&root);
        std::os::unix::fs::symlink(&dir, root.join("out")).unwrap();
        assert!(jail_path("out/x.png", &w, "", "write").starts_with("refused:"));
        std::os::unix::fs::symlink(dir.join("gone"), root.join("dangling")).unwrap();
        assert!(jail_path("dangling", &w, "", "write").starts_with("refused:"));
    }
}
