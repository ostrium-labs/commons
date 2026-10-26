#!/usr/bin/env python3
"""Checks the commons registry. Standard library plus `git` and `gpg` only.

    check.py                      static checks of the working tree
    check.py --base B --head H    static checks plus every commit in B..H

Static checks: track files parse and validate, maintainers have keys, and each
key file holds one primary key whose fingerprint is its file name.

Commit checks:
- every commit carries a valid signature by a primary key in keys/ at H;
- a commit changing a track that exists at B is signed by one of that track's
  maintainers at B;
- a commit changing or deleting a key file that exists at B is signed by that
  key.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,46})[a-z0-9]$")
FPR = re.compile(r"^(?:[0-9A-F]{40}|[0-9A-F]{64})$")
TRACK_FIELDS = {"slug", "name", "scope", "maintainers"}

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def run(*args: str, env: dict | None = None, input: bytes | None = None, check: bool = True) -> str:
    res = subprocess.run(args, cwd=ROOT, env=env, input=input, capture_output=True)
    if check and res.returncode != 0:
        raise SystemExit(f"{' '.join(args)} failed: {res.stderr.decode(errors='replace')}")
    return res.stdout.decode(errors="replace") + res.stderr.decode(errors="replace")


def key_fingerprints(armored: bytes) -> list[str]:
    """Primary-key fingerprints in an armoured key, without importing it."""
    with tempfile.TemporaryDirectory() as home:
        env = {**os.environ, "GNUPGHOME": home}
        out = run("gpg", "--batch", "--with-colons", "--import-options", "show-only", "--import", env=env, input=armored, check=False)
    fprs, after_pub = [], False
    for line in out.splitlines():
        kind = line.split(":")[0]
        if kind == "pub":
            after_pub = True
        elif kind == "fpr" and after_pub:
            fprs.append(line.split(":")[9])
            after_pub = False
        elif kind in ("sub", "uid"):
            after_pub = False
    return fprs


def check_track(name: str, data: bytes, keys: set[str]) -> dict | None:
    try:
        track = tomllib.loads(data.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        fail(f"{name}: not valid TOML: {e}")
        return None
    unknown = set(track) - TRACK_FIELDS
    missing = TRACK_FIELDS - set(track)
    if unknown:
        fail(f"{name}: unknown fields {sorted(unknown)}")
    if missing:
        fail(f"{name}: missing fields {sorted(missing)}")
        return None
    slug = track["slug"]
    if not isinstance(slug, str) or not SLUG.match(slug):
        fail(f"{name}: slug must be 3–48 of a-z, 0-9 and '-', not starting or ending with '-'")
    elif name != f"tracks/{slug}.toml":
        fail(f"{name}: file name must be tracks/{slug}.toml")
    if not isinstance(track["name"], str) or not 3 <= len(track["name"].strip()) <= 80:
        fail(f"{name}: name must be 3–80 characters")
    if not isinstance(track["scope"], str) or not 1 <= len(track["scope"].strip()) <= 1000:
        fail(f"{name}: scope must be 1–1000 characters")
    m = track["maintainers"]
    if not isinstance(m, list) or not 1 <= len(m) <= 10 or len(set(map(str, m))) != len(m):
        fail(f"{name}: maintainers must list 1–10 distinct fingerprints")
        return track
    for fpr in m:
        if not isinstance(fpr, str) or not FPR.match(fpr):
            fail(f"{name}: {fpr!r} is not a full upper-case hex fingerprint")
        elif fpr not in keys:
            fail(f"{name}: maintainer {fpr} has no keys/{fpr}.asc")
    return track


def static_checks() -> set[str]:
    keys: set[str] = set()
    for path in sorted((ROOT / "keys").glob("*")):
        if path.name == "README.md":
            continue
        name = f"keys/{path.name}"
        if path.suffix != ".asc":
            fail(f"{name}: key files must end in .asc")
            continue
        fprs = key_fingerprints(path.read_bytes())
        if len(fprs) != 1:
            fail(f"{name}: must hold exactly one primary public key, found {len(fprs)}")
        elif fprs[0] != path.stem:
            fail(f"{name}: holds {fprs[0]}; rename it keys/{fprs[0]}.asc")
        else:
            keys.add(fprs[0])
    for path in sorted((ROOT / "tracks").glob("*")):
        if path.name == "README.md":
            continue
        if path.suffix != ".toml":
            fail(f"tracks/{path.name}: track files must end in .toml")
            continue
        check_track(f"tracks/{path.name}", path.read_bytes(), keys)
    return keys


def show(rev: str, path: str) -> bytes | None:
    res = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True)
    return res.stdout if res.returncode == 0 else None


def commit_checks(base: str, head: str, keys: set[str]) -> None:
    with tempfile.TemporaryDirectory() as home:
        env = {**os.environ, "GNUPGHOME": home}
        for fpr in keys:
            run("gpg", "--batch", "--import", str(ROOT / "keys" / f"{fpr}.asc"), env=env)
        commits = run("git", "rev-list", "--reverse", f"{base}..{head}").split()
        if not commits:
            fail("no commits between base and head")
        for c in commits:
            short = c[:12]
            status = run("git", "verify-commit", "--raw", c, env=env, check=False)
            signer = None
            for line in status.splitlines():
                parts = line.split()
                if len(parts) >= 12 and parts[:2] == ["[GNUPG:]", "VALIDSIG"]:
                    signer = parts[11]  # the primary key's fingerprint
            if signer is None or signer not in keys:
                fail(f"commit {short}: not signed by a key in keys/ (sign with `git commit -S`)")
                continue
            changed = run("git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", c).split()
            for path in changed:
                if path.startswith("tracks/") and path.endswith(".toml"):
                    before = show(base, path)
                    if before is None:
                        continue
                    try:
                        maintainers = tomllib.loads(before.decode()).get("maintainers", [])
                    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
                        maintainers = []
                    if signer not in maintainers:
                        fail(f"commit {short}: changes {path}, but its signer {signer} is not one of that track's maintainers")
                elif path.startswith("keys/") and path.endswith(".asc"):
                    if show(base, path) is not None and Path(path).stem != signer:
                        fail(f"commit {short}: changes {path}, which only its own key may sign")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base")
    parser.add_argument("--head")
    args = parser.parse_args()
    keys = static_checks()
    if args.base and args.head:
        commit_checks(args.base, args.head, keys)
    for e in errors:
        print(f"error: {e}")
    print(f"{len(keys)} keys, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
