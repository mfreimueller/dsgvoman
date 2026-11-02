"""dsgvoman -- obfuscate and restore student folder names.

    dsgvoman up [--dir PATH]     rename student folders to random names,
                                 write mapping.json (originals Base64-encoded)
    dsgvoman down [--dir PATH]   restore the original names from mapping.json,
                                 delete it once every rename succeeded

Stdlib only. See README.md for details.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import secrets
import sys
from pathlib import Path

MAPPING_FILE = "mapping.json"
ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
NAME_LENGTH = 8


def is_safe_name(name: str) -> bool:
    """A usable single path component: non-empty, not '.'/'..', no separators."""
    return bool(name) and name not in (os.curdir, os.pardir) and not any(
        sep in name for sep in (os.sep, os.altsep, "\0") if sep
    )


def random_name(used: set[str]) -> str:
    """An 8-char lowercase alphanumeric name not present in `used` (adds it)."""
    while True:
        name = "".join(secrets.choice(ALPHABET) for _ in range(NAME_LENGTH))
        if name not in used:
            used.add(name)
            return name


def student_dirs(directory: Path) -> list[Path]:
    """Immediate subdirectories of `directory`, sorted by name."""
    return sorted(
        (p for p in directory.iterdir() if p.is_dir()), key=lambda p: p.name
    )


def cmd_up(directory: Path) -> int:
    mapping_path = directory / MAPPING_FILE
    if mapping_path.exists():
        print(
            f"error: {mapping_path} already exists -- refusing to overwrite "
            f"(run 'dsgvoman down' first)",
            file=sys.stderr,
        )
        return 1

    dirs = student_dirs(directory)
    if not dirs:
        print(
            f"warning: no subdirectories in {directory} -- nothing to do",
            file=sys.stderr,
        )
        return 0

    used = {p.name for p in directory.iterdir()}
    mapping: list[dict[str, str]] = []
    renamed: list[tuple[str, str]] = []  # (original, replacement) so far

    for d in dirs:
        new_name = random_name(used)
        try:
            d.rename(directory / new_name)
        except OSError as exc:
            print(f"error: could not rename {d.name!r} -> {new_name!r}: {exc}", file=sys.stderr)
            for old, new in reversed(renamed):
                try:
                    (directory / new).rename(directory / old)
                    print(f"rolled back {new!r} -> {old!r}", file=sys.stderr)
                except OSError as roll_exc:
                    print(
                        f"error: rollback of {new!r} -> {old!r} failed: {roll_exc}; "
                        f"finish it manually",
                        file=sys.stderr,
                    )
            return 1
        renamed.append((d.name, new_name))
        mapping.append(
            {
                "original": base64.b64encode(d.name.encode("utf-8")).decode("ascii"),
                "replacement": new_name,
            }
        )
        print(f"renamed {d.name!r} -> {new_name!r}")

    mapping_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {mapping_path} ({len(mapping)} entries)")
    return 0


def cmd_down(directory: Path) -> int:
    mapping_path = directory / MAPPING_FILE
    if not mapping_path.exists():
        print(f"error: no {MAPPING_FILE} found in {directory}", file=sys.stderr)
        return 1

    try:
        data = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {mapping_path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, list):
        print(f"error: {mapping_path} must contain a JSON list", file=sys.stderr)
        return 1

    problems: list[str] = []
    plan: list[tuple[str, str]] = []
    seen_originals: set[str] = set()

    for i, entry in enumerate(data):
        if not isinstance(entry, dict) or set(entry) != {"original", "replacement"}:
            problems.append(f"entry {i}: expected an object with 'original' and 'replacement'")
            continue
        replacement = entry["replacement"]
        if not isinstance(replacement, str) or not is_safe_name(replacement):
            problems.append(f"entry {i}: invalid replacement name {replacement!r}")
            continue
        try:
            original = base64.b64decode(entry["original"], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, TypeError, ValueError):
            problems.append(f"entry {i}: 'original' is not valid Base64 text")
            continue
        if not is_safe_name(original):
            problems.append(f"entry {i}: decoded name {original!r} is not a valid folder name")
            continue
        if original in seen_originals:
            problems.append(f"entry {i}: duplicate original name {original!r}")
            continue
        seen_originals.add(original)
        plan.append((original, replacement))

    for original, replacement in plan:
        src = directory / replacement
        if not src.is_dir():
            problems.append(f"missing folder {replacement!r} (would restore it to {original!r})")
        elif original != replacement and (directory / original).exists():
            problems.append(f"destination {original!r} already exists (would come from {replacement!r})")

    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        print(f"aborted, no renames done -- keeping {MAPPING_FILE}", file=sys.stderr)
        return 1

    for original, replacement in plan:
        if original == replacement:
            continue
        try:
            (directory / replacement).rename(directory / original)
        except OSError as exc:
            print(
                f"error: could not rename {replacement!r} -> {original!r}: {exc}; "
                f"keeping {MAPPING_FILE}",
                file=sys.stderr,
            )
            return 1
        print(f"restored {replacement!r} -> {original!r}")

    mapping_path.unlink()
    print(f"removed {mapping_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dsgvoman",
        description="Obfuscate ('up') and restore ('down') student folder names.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    commands = {}
    for name, help_text in (
        ("up", "rename student folders to random names and create mapping.json"),
        ("down", "restore original names using mapping.json, then delete it"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument(
            "--dir",
            metavar="PATH",
            default=".",
            help="folder containing the student subfolders (default: current directory)",
        )
        commands[name] = p

    args = parser.parse_args(argv)
    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"error: {directory} is not a directory", file=sys.stderr)
        return 1

    return cmd_up(directory) if args.command == "up" else cmd_down(directory)


if __name__ == "__main__":
    sys.exit(main())
