import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def connect(path):
    db = sqlite3.connect(path, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=15000')
    return db


@contextmanager
def transaction(path, write=False):
    db = connect(path)
    try:
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def migrate(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = connect(path)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('BEGIN IMMEDIATE')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > 2:
            raise RuntimeError('数据库版本较新，请使用匹配的应用版本')
        if version < 1:
            statements = [
                '''CREATE TABLE categories (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
                '''CREATE TABLE links (
                key TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
                category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
                description TEXT NOT NULL DEFAULT '', icon TEXT NOT NULL DEFAULT '',
                pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1)), sort_order INTEGER NOT NULL DEFAULT 0,
                organization TEXT NOT NULL DEFAULT '其他', network TEXT NOT NULL DEFAULT 'public',
                environment TEXT NOT NULL DEFAULT 'none', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
                'CREATE INDEX links_category ON links(category_id,sort_order)',
                '''CREATE TABLE sessions (id TEXT PRIMARY KEY, csrf TEXT NOT NULL,
                expires REAL NOT NULL, fingerprint TEXT NOT NULL)''',
                'CREATE TABLE login_attempts (client TEXT NOT NULL, at REAL NOT NULL)',
                'CREATE INDEX login_attempt_time ON login_attempts(at)',
            ]
            for statement in statements:
                db.execute(statement)
            db.execute('PRAGMA user_version=1')
        if version < 2:
            db.execute("""CREATE TABLE link_groups (
                key TEXT PRIMARY KEY, name TEXT NOT NULL,
                category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
                icon TEXT NOT NULL DEFAULT '', pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1)),
                sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE group_members (
                link_key TEXT PRIMARY KEY REFERENCES links(key) ON DELETE CASCADE,
                group_key TEXT NOT NULL REFERENCES link_groups(key) ON DELETE CASCADE,
                sort_order INTEGER NOT NULL DEFAULT 0)""")
            db.execute('CREATE INDEX members_group ON group_members(group_key,sort_order)')
            db.execute("""CREATE TRIGGER group_member_category BEFORE INSERT ON group_members
                WHEN (SELECT category_id FROM links WHERE key=NEW.link_key) <>
                     (SELECT category_id FROM link_groups WHERE key=NEW.group_key)
                BEGIN SELECT RAISE(ABORT,'group category mismatch'); END""")
            db.execute("""CREATE TRIGGER detach_moved_link AFTER UPDATE OF category_id ON links
                BEGIN DELETE FROM group_members WHERE link_key=NEW.key AND
                (SELECT category_id FROM link_groups WHERE key=group_members.group_key)<>NEW.category_id; END""")
            db.execute("""CREATE TRIGGER dissolve_empty_group AFTER DELETE ON group_members
                BEGIN DELETE FROM link_groups WHERE key=OLD.group_key AND
                NOT EXISTS(SELECT 1 FROM group_members WHERE group_key=OLD.group_key); END""")
            db.execute("""CREATE TRIGGER move_group_members AFTER UPDATE OF category_id ON link_groups
                WHEN OLD.category_id<>NEW.category_id
                BEGIN UPDATE links SET category_id=NEW.category_id,updated_at=NEW.updated_at
                WHERE key IN(SELECT link_key FROM group_members WHERE group_key=NEW.key); END""")
            db.execute('PRAGMA user_version=2')
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    os.chmod(path, 0o600)
