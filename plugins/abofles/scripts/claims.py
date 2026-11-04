#!/usr/bin/env python3
"""Abo Fles claims: who works on which branch and files of a repository, so several sessions and agents do not collide.

    claims.py list                                       one line per live claim; overlaps flagged
    claims.py claim --session S --branch B [--worktree W] [--files f ...]   record (or replace) S's claim
    claims.py heartbeat --session S                      keep S's claim alive
    claims.py release --session S                        drop S's claim

The store is `<git rev-parse --git-common-dir>/abofles-claims.json`: inside .git, so it is never committed and every worktree of
the repository shares it. One claim per session; a claim with no heartbeat for 2 hours drops out. An overlap is the same branch or
the same file (a folder claims what is under it) held by two sessions.
      exit codes: 0 ok · 1 no claim for the session · 2 usage, or not in a git repository
                  · 3 `claim` written, but another live session holds the same branch or a file (the lines say which)
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from abofles_hook import lock_file, unlock_file, replace_file  # noqa: E402

TTL = 2 * 3600  # seconds without a heartbeat before a claim drops out


def store_path():
    r = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return Path(os.path.abspath(r.stdout.strip())) / "abofles-claims.json"  # a relative answer (`.git`) is relative to the current folder


_warned = False


def read(path):
    """The stored claims. No file or an empty one is no claims; a file that is not valid claims JSON is copied to `<store>.bak`,
    warned about once on stderr, and read as no claims (the next write replaces it)."""
    global _warned
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    if not text.strip():
        return []
    try:
        data = json.loads(text)
        return [c for c in data.get("claims", []) if isinstance(c, dict) and c.get("session")]
    except (ValueError, AttributeError, TypeError):
        if not _warned:
            _warned = True
            bak = path.with_name(path.name + ".bak")
            try:
                bak.unlink()  # a planted `.bak` symlink is removed, never written through
            except OSError:
                pass
            try:
                fd = os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError:
                pass
            print(f"abofles: claims store {path} is damaged — copied to {bak.name}, starting with no claims", file=sys.stderr)
        return []


def beat_of(c):
    """The claim's last heartbeat as a number; a missing or bad value is 0 (stale)."""
    try:
        return float(c.get("beat") or 0)
    except (TypeError, ValueError):
        return 0.0


def live(claims, now):
    return [c for c in claims if now - beat_of(c) <= TTL]


def clean(x):
    """A stored string for printing: control characters (a pasted escape sequence, a newline, C1 controls), line and paragraph
    separators, zero-width characters and bidi marks removed."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff]", "", str(x))


def write(path, claims):
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps({"claims": claims}, ensure_ascii=False, indent=1), encoding="utf-8")
        replace_file(tmp, path)
    except BaseException:
        try:
            tmp.unlink()  # never leave a half-written `.tmp` behind
        except OSError:
            pass
        raise


class locked:
    """Read-modify-write under an exclusive lock on a file next to the store; yields the live claims, saves what the body leaves in `.claims`."""
    def __init__(self, path):
        self.path, self.fh = path, None
    def __enter__(self):
        # no truncate and no symlink follow: a planted `abofles-claims.lock` link must not empty the file it points at
        fd = os.open(self.path.with_name("abofles-claims.lock"), os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        self.fh = os.fdopen(fd, "w")
        lock_file(self.fh)
        self.claims = live(read(self.path), time.time())
        return self
    def __exit__(self, et, ev, tb):
        try:
            if et is None:
                write(self.path, self.claims)
        finally:
            unlock_file(self.fh)
            self.fh.close()


def norm(f):
    f = f.replace("\\", "/")
    while f.startswith("./"):
        f = f[2:]
    return f


def files_clash(a, b):
    a, b = norm(a), norm(b)
    return a == b or (b + "/").startswith(a.rstrip("/") + "/") or (a + "/").startswith(b.rstrip("/") + "/")


def overlaps(c, claims):
    """['branch feat/x with S2', 'file src/a.cs with S3'] — what claim c shares with the other sessions' claims."""
    out = []
    for o in claims:
        if o["session"] == c["session"]:
            continue
        if c.get("branch") and c["branch"] == o.get("branch"):
            out.append(f"branch {clean(c['branch'])} with {clean(o['session'])}")
        for f in c.get("files") or []:
            if any(files_clash(f, g) for g in o.get("files") or []):
                out.append(f"file {clean(f)} with {clean(o['session'])}")
    return out


def ago(ts, now):
    m = max(0, int(now - ts)) // 60
    return f"{m}m ago" if m < 120 else f"{m // 60}h ago"


def line(c, claims, now):
    bits = [clean(c["session"]), f"branch {clean(c.get('branch') or '-')}"]
    if c.get("worktree"):
        bits.append(f"worktree {clean(c['worktree'])}")
    if c.get("files"):
        bits.append("files " + ", ".join(clean(f) for f in c["files"]))
    bits.append(f"beat {ago(beat_of(c), now)}")
    s = " · ".join(bits)
    ov = overlaps(c, claims)
    return s + (" · ⚠ overlap: " + "; ".join(ov) if ov else "")


def opt(args, name):
    """The value after --name, or None."""
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def main():
    args = sys.argv[1:]
    for a in args:
        try:
            a.encode("utf-8")
        except UnicodeEncodeError:  # a non-UTF-8 byte in argv (surrogate-escaped): refused before anything is written
            print("abofles: claims.py arguments must be UTF-8 text")
            sys.exit(2)
    cmd = args[0] if args else ""
    if cmd not in ("list", "claim", "heartbeat", "release"):
        print(__doc__.strip().split("\n\n")[0])
        sys.exit(2)
    path = store_path()
    if not path:
        print("abofles: not in a git repository")
        sys.exit(2)
    sess = opt(args, "--session")
    if cmd != "list" and not sess:
        print(f"abofles: claims.py {cmd} needs --session <id>")
        sys.exit(2)
    now = time.time()
    if cmd == "list":
        claims = live(read(path), now)
        for c in claims:
            print(line(c, claims, now))
        if not claims:
            print("no claims")
        return
    if cmd == "claim":
        branch = opt(args, "--branch")
        if not branch:
            print("abofles: claims.py claim needs --branch <name>")
            sys.exit(2)
        files = []
        if "--files" in args:
            for a in args[args.index("--files") + 1:]:
                if a.startswith("--"):
                    break
                files.append(norm(a))
        c = {"session": sess, "branch": branch, "worktree": opt(args, "--worktree") or "", "files": files, "since": int(now), "beat": int(now)}
        with locked(path) as lk:
            old = next((o for o in lk.claims if o["session"] == sess), None)
            if old:
                c["since"] = old.get("since") or c["since"]
            lk.claims = [o for o in lk.claims if o["session"] != sess] + [c]
            ov = overlaps(c, lk.claims)
        print("claimed: " + line(c, [c], now))
        for o in ov:
            print("abofles: overlap — " + o)
        sys.exit(3 if ov else 0)
    with locked(path) as lk:
        c = next((o for o in lk.claims if o["session"] == sess), None)
        if cmd == "heartbeat" and c:
            c["beat"] = int(now)
        elif cmd == "release" and c:
            lk.claims = [o for o in lk.claims if o["session"] != sess]
    if not c:
        print(f"abofles: no live claim for session {clean(sess)}")
        sys.exit(1)
    print(("beat: " if cmd == "heartbeat" else "released: ") + clean(sess))


if __name__ == "__main__":
    main()
