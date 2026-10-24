#!/usr/bin/env python3
"""Abo Fles overrides: read and write the `## abofles overrides` block (the Abo Fles pane's editor runs this).

    overrides.py get --json [--session S] [--cwd D]
        prints the pane's overrides payload: {files, keys: [{key, kind, options, value, source, default}], raw: [{line, source}]}
    overrides.py set --scope project|user [--session S] [--cwd D]      stdin: {"set": {"Key": "value" | ""}, "raw": ["Topic: X = T3", …]}
        edits the block in place (a new key is appended, "" removes the key), `raw` replaces only the complex-form lines of the block;
        everything outside the block, unknown keys and prose stay byte for byte. Prints the new `get` JSON.

Project scope = the project's CLAUDE.md or .claude/CLAUDE.md, whichever already holds the block (else CLAUDE.md); user scope =
~/.claude/CLAUDE.md. Bad input: one line on stderr, exit 2. Acts on the session you type in (see agents.py).
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import abofles_hook as H  # noqa: E402

_KEY_LINE = lambda key: re.compile(r"^(\s*-\s*" + re.escape(key) + r"\s*=\s*)(.+?)(\s*)$", re.I)
_EXTRA = {"Break": ("off",)}  # a number key that also takes a word
MAX_VALUE = 500  # characters per value or line: an override is one short line
BOM = b"\xef\xbb\xbf"


class Bad(Exception):
    """Input the writer refuses: one line, exit 2."""


def clean_value(key, spec, value):
    """The value as it is written, or Bad. Select: an option (Agents also a number, Receipt also `savings N`); number: an integer; list: integers (comma-separated)."""
    v = " ".join(str(value).split())
    if "\n" in str(value).strip() or "\r" in str(value).strip():
        raise Bad(f"{key}: one line only")
    if len(v) > MAX_VALUE:
        raise Bad(f"{key}: longer than {MAX_VALUE} characters")
    kind, opts = spec["kind"], spec["options"]
    if kind == "select":
        low = v.lower()
        if low in opts:
            return low
        if key == "Agents" and re.fullmatch(r"\d+", v):
            return str(int(v))
        if key == "Receipt" and re.fullmatch(r"savings\s+\d+", low):
            return "savings " + str(int(low.split()[1]))
        raise Bad(f"{key}: '{v}' is not one of {', '.join(opts)}" + (" or a number N" if key == "Agents" else " or 'savings N'" if key == "Receipt" else ""))
    if kind == "number":
        if re.fullmatch(r"\d+", v):
            return str(int(v))
        if v.lower() in _EXTRA.get(key, ()):
            return v.lower()
        raise Bad(f"{key}: '{v}' is not a whole number" + (" or off" if key in _EXTRA else ""))
    if kind == "list":
        parts = [p.strip() for p in v.split(",")]
        if not all(re.fullmatch(r"\d+", p) for p in parts) or (key == "Agent budgets" and len(parts) != 4):
            raise Bad(f"{key}: '{v}' is not " + ("four whole numbers a, b, c, d" if key == "Agent budgets" else "whole numbers, comma-separated"))
        return ", ".join(str(int(p)) for p in parts)
    if not v:
        raise Bad(f"{key}: empty value (use \"\" to remove the key)")
    return v


def bullet(line):
    m = re.match(r"^\s*-\s*(.+?)\s*$", line.rstrip("\r\n"))
    return m.group(1) if m else None


def is_complex(content):
    return any(r.match(content) for r in H.COMPLEX_FORMS)


def edit_text(txt, sets, raw):
    """The new file text: `sets` {key: value | ""} edited in place, appended (first block) or removed; `raw` (None: untouched) replaces the
    complex-form lines of the blocks — a line already there and still wanted stays where it is. No block yet and something to add: a new one."""
    nl = "\r\n" if "\r\n" in txt else "\n"
    lines = txt.splitlines(True)
    spans = lambda: H.override_spans([l.rstrip("\r\n") for l in lines])
    inside = lambda: [i for a, b in spans() for i in range(a, b)]
    adds = []
    for key, val in sets.items():
        rx = _KEY_LINE(key)
        hits = [i for i in inside() if rx.match(lines[i].rstrip("\r\n"))]
        if val == "":
            for i in reversed(hits):
                del lines[i]
        elif hits:
            body = lines[hits[0]].rstrip("\r\n")
            lines[hits[0]] = rx.match(body).group(1) + val + lines[hits[0]][len(body):]
        else:
            adds.append(f"- {key} = {val}")
    if raw is not None:
        old = [(i, bullet(lines[i])) for i in inside() if bullet(lines[i]) is not None and is_complex(bullet(lines[i]))]
        want, drop = list(raw), []
        for i, c in old:
            if c in want:
                want.remove(c)
            else:
                drop.append(i)
        if old and want:  # next to the complex lines already there
            at = max(i for i, _ in old) + 1
            for i in reversed(drop):
                del lines[i]
            at -= len(drop)
            if not lines[at - 1].endswith(("\n", "\r")):
                lines[at - 1] += nl
            lines[at:at] = [f"- {c}{nl}" for c in want]
        else:
            for i in reversed(drop):
                del lines[i]
            adds = [f"- {c}" for c in want] + adds
    if adds:
        sp = spans()
        if sp:
            a, b = sp[0]
            last = max([i for i in range(a, b) if bullet(lines[i]) is not None] or [i for i in range(a, b) if lines[i].strip()] or [a - 1])  # after the last bullet, else the last text
            if last >= 0 and not lines[last].endswith(("\n", "\r")):
                lines[last] += nl
            lines[last + 1:last + 1] = [x + nl for x in adds]
        else:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += nl
            lines += ([nl] if lines else []) + ["## abofles overrides" + nl, nl] + [x + nl for x in adds]
    return "".join(lines)


class Changed(Exception):
    """The target changed between our read and our write: nothing is written, exit 3."""


def write_atomic(path, data, expect=None, inside=None):
    """Write `data` over `path` via a temp file. `expect` = the bytes read before editing (None = the file was missing); if the target
    holds anything else right before the replace, raise Changed instead. `inside`: a folder the real file (symlinks followed) must be in,
    else Bad — a project's CLAUDE.md that links out of the project is not written. The temp file is a fresh one (mkstemp: never a name a
    repo could plant a link at) in the target's folder, so the replace stays on one disk."""
    real = Path(os.path.realpath(path))
    if inside is not None:
        base = Path(os.path.realpath(inside))
        if real != base and base not in real.parents:
            raise Bad(f"{path.name} points outside the project ({real}) — edit it by hand")
    real.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=str(real.parent), prefix=f".{real.name}.", suffix=".abofles-tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            now = real.read_bytes()
        except FileNotFoundError:
            now = None
        if now != expect:
            raise Changed()
        if real.exists():
            shutil.copymode(real, tmp)
        else:  # mkstemp makes 0600: a new CLAUDE.md gets the usual mode
            mask = os.umask(0)
            os.umask(mask)
            os.chmod(tmp, 0o666 & ~mask)
        os.replace(tmp, real)
    finally:
        tmp.unlink(missing_ok=True)


def read_request():
    try:
        req = json.loads(sys.stdin.read())
    except ValueError:
        raise Bad("stdin is not JSON")
    if not isinstance(req, dict) or not isinstance(req.get("set", {}), dict) or not (req.get("raw") is None or isinstance(req["raw"], list)):
        raise Bad('stdin must be {"set": {Key: value}, "raw": [lines]}')
    sets = {}
    for k, v in (req.get("set") or {}).items():
        key = next((n for n in H.OVERRIDE_KEYS if n.lower() == str(k).strip().lower()), None)
        if key is None:
            raise Bad(f"unknown key '{k}'")
        if not isinstance(v, (str, int)):
            raise Bad(f"{key}: value must be text")
        sets[key] = "" if str(v).strip() == "" else clean_value(key, H.OVERRIDE_KEYS[key], v)
    raw = None
    if req.get("raw") is not None:
        raw = []
        for l in req["raw"]:
            c = re.sub(r"^\s*-\s*", "", " ".join(str(l).split()))
            if not c:
                continue
            if c.endswith("…"):
                raise Bad(f"'{c[:40]}…' was clipped in the pane; edit that line in the file")
            if H.simple_key(c) is not None:
                raise Bad(f"'{c[:40]}' is a simple key; use its row")
            raw.append(c)
    return sets, raw


def opt(args, name):
    """Take `name value` out of `args`; the value, or None."""
    if name in args and args.index(name) + 1 < len(args):
        i = args.index(name)
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return None


def session_of(args):
    """(cwd, session id, its state, the project root) for the command: --cwd, --session (ABOFLES_SESSION first), else the newest session of this folder."""
    cwd = opt(args, "--cwd") or os.getcwd()
    if args[-2:] == ["--session", ""]:  # a command whose ${CLAUDE_SESSION_ID} expanded to nothing
        del args[-2:]
    sp = H.newest_state_path(cwd, H.session_arg(args))
    sid = sp.stem if sp else ""
    st = H.load_state(sid) if sid else {}
    return cwd, sid, st, H.project_root({"cwd": cwd}, st)


def payload(root, sid):
    return H.pane_overrides(root, sid)


def main():
    args = sys.argv[1:]
    try:
        cwd, sid, st, root = session_of(args)  # --session / --cwd first or last: the pane runs `overrides.py --session S set --scope …`
        cmd = args.pop(0) if args else ""
        if cmd == "get":
            print(json.dumps(payload(root, sid)))
            return 0
        scope = opt(args, "--scope")
        if cmd != "set" or scope not in ("project", "user"):
            raise Bad("usage: overrides.py get --json | set --scope project|user  (stdin JSON {set, raw})")
        sets, raw = read_request()
        path = H.override_target(scope, root)
        try:
            old_b = path.read_bytes()
        except FileNotFoundError:
            old_b = None
        try:
            old = (old_b or b"").decode("utf-8-sig")  # a BOM is kept on the write
        except UnicodeDecodeError:
            raise Bad(f"{path.name} is not UTF-8 text — edit it by hand")
        if raw is not None:  # a line that is no complex form must already be in the block (an unknown key the pane lists): it stays where it is
            lines = old.splitlines()
            unknown = {bullet(l) for a, b in H.override_spans(lines) for l in lines[a:b] if bullet(l) is not None and H.simple_key(bullet(l)) is None and not is_complex(bullet(l))}
            for c in raw:
                if len(c) > MAX_VALUE:
                    raise Bad(f"'{c[:40]}…' is longer than {MAX_VALUE} characters")
                if not is_complex(c) and c not in unknown:
                    raise Bad(f"'{c[:40]}' is not an override form")
            raw = [c for c in raw if is_complex(c)]
        new = edit_text(old, sets, raw)
        if new != old:
            write_atomic(path, (BOM if (old_b or b"").startswith(BOM) else b"") + new.encode("utf-8"), old_b, inside=root if scope == "project" else None)
        if sid:
            with H.state_lock(sid):
                st = H.load_state(sid)
                try:
                    H.refresh_guide(root, st, sid)  # the guide (Guide = off) and the pane follow
                except Exception:
                    H.refresh_pane(root, st, sid)
                H.save_state(sid, st)
        print(json.dumps(payload(root, sid)))
        return 0
    except Bad as e:
        print(f"abofles overrides: {e}", file=sys.stderr)
        return 2
    except Changed:
        print("abofles: CLAUDE.md changed while saving — reload the pane and save again", file=sys.stderr)
        return 3
    except OSError as e:
        print(f"abofles overrides: cannot write — {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
