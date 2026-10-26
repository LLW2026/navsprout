"""Consistent SQLite backup; restore only while the application is stopped."""
import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def check(db):
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('数据库完整性检查未通过')
    if db.execute('PRAGMA user_version').fetchone()[0] not in (1, 2):
        raise ValueError('数据库版本不匹配')
    required = {'categories', 'links', 'sessions'}
    if db.execute('PRAGMA user_version').fetchone()[0] == 2:
        required |= {'link_groups', 'group_members'}
    if not required <= {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        raise ValueError('不是导航数据库')


def copy_database(source, destination, restore=False):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file() or source == destination:
        raise ValueError('请指定有效且不同的源数据库和目标路径')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not restore and destination.exists():
        raise ValueError('备份文件已存在，请更换文件名')
    fd, tmp = tempfile.mkstemp(prefix='.nav-', suffix='.db', dir=destination.parent)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(tmp)) as dst:
            check(src)
            src.backup(dst)
            # The backup inherits WAL mode. Consolidate it before renaming one file.
            dst.execute('PRAGMA journal_mode=DELETE')
            if restore:
                dst.execute('DELETE FROM sessions')
                dst.execute('DELETE FROM login_attempts')
                dst.commit()
            check(dst)
        os.chmod(tmp, 0o600)
        if restore:
            for suffix in ('-wal', '-shm'):
                Path(str(destination) + suffix).unlink(missing_ok=True)
        os.replace(tmp, destination)
    finally:
        for suffix in ('', '-wal', '-shm'):
            Path(tmp + suffix).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='导航数据库备份与恢复')
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('source')
    parser.add_argument('destination')
    parser.add_argument('--app-stopped', action='store_true')
    args = parser.parse_args()
    if args.action == 'restore' and not args.app_stopped:
        parser.error('恢复前停止应用，并传入 --app-stopped')
    try:
        copy_database(args.source, args.destination, args.action == 'restore')
    except (ValueError, sqlite3.Error, OSError) as exc:
        raise SystemExit(f'操作失败：{exc}')
    print('备份完成' if args.action == 'backup' else '恢复完成，原会话已清除')
