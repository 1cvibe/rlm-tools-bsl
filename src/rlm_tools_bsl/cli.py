"""CLI interface for rlm-bsl-index (method index management).

Usage::

    rlm-bsl-index index build <path> [--no-calls]
    rlm-bsl-index index update <path>
    rlm-bsl-index index info <path>
    rlm-bsl-index index drop <path>
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def _resolve_path(raw: str) -> str:
    """Resolve and validate a base path argument."""
    p = Path(raw).resolve()
    if not p.is_dir():
        print(f"Error: directory not found: {p}", file=sys.stderr)
        sys.exit(1)
    return str(p)


def _fmt_size(size_bytes: int) -> str:
    """Format file size in human-readable form."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _fmt_age(seconds: float) -> str:
    """Format age in human-readable form."""
    if seconds < 60:
        return f"{seconds:.0f}s ago"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m ago"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h ago"
    return f"{seconds / 86400:.1f}d ago"


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _cmd_build(args: argparse.Namespace) -> None:
    from rlm_tools_bsl.bsl_index import IndexBuilder, get_index_db_path

    base_path = _resolve_path(args.path)
    build_calls = not args.no_calls

    print(f"Building index for: {base_path}")
    print(f"Call graph: {'yes' if build_calls else 'no'}")

    t0 = time.time()
    builder = IndexBuilder()
    db_path = builder.build(base_path, build_calls=build_calls)
    elapsed = time.time() - t0

    # Read back stats
    from rlm_tools_bsl.bsl_index import IndexReader
    reader = IndexReader(db_path)
    stats = reader.get_statistics()
    reader.close()

    db_size = db_path.stat().st_size if db_path.exists() else 0

    print(f"\nIndex built in {elapsed:.1f}s")
    print(f"  Modules:  {stats['modules']}")
    print(f"  Methods:  {stats['methods']}")
    print(f"  Calls:    {stats['calls']}")
    print(f"  Exports:  {stats['exports']}")
    print(f"  DB size:  {_fmt_size(db_size)}")
    print(f"  DB path:  {db_path}")


def _cmd_update(args: argparse.Namespace) -> None:
    from rlm_tools_bsl.bsl_index import IndexBuilder, get_index_db_path

    base_path = _resolve_path(args.path)
    db_path = get_index_db_path(base_path)

    if not db_path.exists():
        print("Error: index not found. Run 'index build' first.", file=sys.stderr)
        sys.exit(1)

    print(f"Incremental update: {base_path}")

    t0 = time.time()
    builder = IndexBuilder()
    delta = builder.update(base_path)
    elapsed = time.time() - t0

    print(f"\nUpdated in {elapsed:.1f}s")
    print(f"  Added:   {delta['added']}")
    print(f"  Changed: {delta['changed']}")
    print(f"  Removed: {delta['removed']}")


def _cmd_info(args: argparse.Namespace) -> None:
    from rlm_tools_bsl.bsl_index import (
        IndexReader,
        IndexStatus,
        check_index_freshness,
        get_index_db_path,
    )
    from rlm_tools_bsl.cache import _paths_hash

    base_path = _resolve_path(args.path)
    db_path = get_index_db_path(base_path)

    if not db_path.exists():
        print(f"Index not found: {db_path}")
        sys.exit(0)

    reader = IndexReader(db_path)
    stats = reader.get_statistics()
    reader.close()

    db_size = db_path.stat().st_size

    # Freshness check
    base = Path(base_path)
    bsl_files = sorted(base.rglob("*.bsl"))
    rel_paths = [f.relative_to(base).as_posix() for f in bsl_files]
    paths_hash = _paths_hash(rel_paths)

    status = check_index_freshness(db_path, len(bsl_files), paths_hash, base_path)

    status_labels = {
        IndexStatus.FRESH: "fresh",
        IndexStatus.STALE: "stale (structure changed)",
        IndexStatus.STALE_AGE: "stale (age)",
        IndexStatus.STALE_CONTENT: "stale (content)",
        IndexStatus.MISSING: "missing",
    }

    print(f"Index: {db_path}")
    print(f"  Status:   {status_labels.get(status, status.value)}")
    print(f"  Modules:  {stats['modules']}")
    print(f"  Methods:  {stats['methods']}")
    print(f"  Calls:    {stats['calls']}")
    print(f"  Exports:  {stats['exports']}")
    print(f"  DB size:  {_fmt_size(db_size)}")

    if stats["built_at"]:
        age = time.time() - stats["built_at"]
        print(f"  Built:    {_fmt_age(age)}")

    print(f"  BSL files on disk: {len(bsl_files)}")


def _cmd_drop(args: argparse.Namespace) -> None:
    from rlm_tools_bsl.bsl_index import get_index_db_path

    base_path = _resolve_path(args.path)
    db_path = get_index_db_path(base_path)

    if not db_path.exists():
        print("Index not found, nothing to drop.")
        return

    size = db_path.stat().st_size
    db_path.unlink()
    print(f"Index dropped: {db_path} ({_fmt_size(size)})")

    # Remove parent dir if empty
    try:
        db_path.parent.rmdir()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Load .env (same logic as server.py)
    try:
        from dotenv import find_dotenv, load_dotenv
        load_dotenv(find_dotenv(usecwd=True), override=False)
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        prog="rlm-tools-bsl",
        description="1C (BSL) codebase analysis tools",
    )
    sub = parser.add_subparsers(dest="group")

    # --- index group ---
    idx_parser = sub.add_parser("index", help="Method index management")
    idx_sub = idx_parser.add_subparsers(dest="command")

    # build
    build_p = idx_sub.add_parser("build", help="Full index build")
    build_p.add_argument("path", help="Root directory of 1C configuration")
    build_p.add_argument("--no-calls", action="store_true", help="Skip call graph")

    # update
    update_p = idx_sub.add_parser("update", help="Incremental update by mtime+size")
    update_p.add_argument("path", help="Root directory of 1C configuration")

    # info
    info_p = idx_sub.add_parser("info", help="Index status and statistics")
    info_p.add_argument("path", help="Root directory of 1C configuration")

    # drop
    drop_p = idx_sub.add_parser("drop", help="Delete index")
    drop_p.add_argument("path", help="Root directory of 1C configuration")

    args = parser.parse_args()

    if args.group is None:
        parser.print_help()
        sys.exit(0)

    if args.group == "index":
        if args.command is None:
            idx_parser.print_help()
            sys.exit(0)
        handlers = {
            "build": _cmd_build,
            "update": _cmd_update,
            "info": _cmd_info,
            "drop": _cmd_drop,
        }
        handlers[args.command](args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
