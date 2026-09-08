"""Safely create the isolated synthetic demo data set."""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path

KNOWN_CONTENT = {
    "demo-page.html": ("text", "<h1>Desktop Organizer Demo</h1>\n"),
    "student-budget.csv": ("text", "category,amount,month\nfood,120,2026-09\n"),
    "meeting-notes.md": ("text", "# Demo meeting notes\n"),
    "broken-download.pdf": ("bytes", b"<!DOCTYPE html>\n"),
    "README-demo.txt": ("text", "Safe synthetic demonstration data.\n"),
}


def _matches(path: Path, kind: str, expected) -> bool:
    try:
        if kind == "bytes":
            return path.read_bytes() == expected
        return path.read_text(encoding="utf-8") == expected
    except (OSError, UnicodeError):
        return False


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    try:
        get_attrs = ctypes.windll.kernel32.GetFileAttributesW
        get_attrs.restype = ctypes.c_uint32
        attrs = get_attrs(str(path))
        return attrs != 0xFFFFFFFF and bool(attrs & 0x400)
    except (AttributeError, OSError):
        return False


def _reject_reparse_boundary(path: Path) -> None:
    """Reject a root or existing ancestor that can redirect writes."""
    existing = Path(os.path.abspath(path))
    while not existing.exists():
        if existing.parent == existing:
            return
        existing = existing.parent
    while True:
        if _is_reparse_point(existing):
            raise RuntimeError(f"Refusing reparse-point demo path: {existing}")
        if existing.parent == existing:
            return
        existing = existing.parent


def reset_demo(root: Path) -> tuple[list[str], list[str]]:
    """Create only absent, known files; preserve conflicts and unknown entries."""
    root = Path(root)
    _reject_reparse_boundary(root)
    root.mkdir(parents=True, exist_ok=True)
    _reject_reparse_boundary(root)
    created, preserved = [], []
    for name, (kind, content) in KNOWN_CONTENT.items():
        path = root / name
        if _is_reparse_point(path):
            raise RuntimeError(f"Refusing symlink entry: {path}")
        if path.is_dir():
            preserved.append(f"{name} (non-file conflict)")
            continue
        if path.exists():
            if _matches(path, kind, content):
                continue
            preserved.append(f"{name} (modified file)")
            continue
        try:
            if kind == "bytes":
                with path.open("xb") as handle:
                    handle.write(content)
            else:
                with path.open("x", encoding="utf-8", newline="") as handle:
                    handle.write(content)
        except FileExistsError:
            preserved.append(f"{name} (creation race conflict)")
        else:
            created.append(name)
    return created, preserved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent / "demo-data")
    args = parser.parse_args(argv)
    try:
        created, preserved = reset_demo(args.root)
    except (OSError, RuntimeError) as exc:
        print(f"Demo reset refused: {exc}")
        return 2
    print(f"Demo data reset: {Path(args.root)}")
    if created:
        print("Created: " + ", ".join(created))
    if preserved:
        print("Preserved conflicts: " + ", ".join(preserved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
