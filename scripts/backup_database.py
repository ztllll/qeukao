#!/usr/bin/env python3
import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Back up the Qeukao SQLite database.")
    parser.add_argument("--source", required=True, help="Source SQLite database path.")
    parser.add_argument("--target-dir", required=True, help="Backup output directory.")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=90,
        help="Delete backups older than this many days.",
    )
    return parser.parse_args()


def backup_database(source, target_dir):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"qeukao-db-{timestamp}.sqlite3"
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    return target


def cleanup_old_backups(target_dir, retention_days):
    cutoff = datetime.now() - timedelta(days=retention_days)
    deleted = []
    for path in target_dir.glob("qeukao-db-*.sqlite3"):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime)
        except FileNotFoundError:
            continue
        if modified < cutoff:
            path.unlink()
            deleted.append(path)
    return deleted


def main():
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    target_dir = Path(args.target_dir).expanduser()
    if not source.exists():
        raise SystemExit(f"database not found: {source}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = backup_database(source, target_dir)
    deleted = cleanup_old_backups(target_dir, args.retention_days)
    print(f"backup created: {target}")
    print(f"old backups deleted: {len(deleted)}")


if __name__ == "__main__":
    main()
