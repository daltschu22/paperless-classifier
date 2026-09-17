from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "classifier.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, document_id INTEGER NOT NULL,
                    status TEXT NOT NULL, options TEXT NOT NULL,
                    proposal TEXT, approval TEXT, error_code TEXT, error TEXT,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created);
                CREATE TABLE IF NOT EXISTS operations (
                    job_id TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL,
                    result TEXT, complete INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(job_id,name));
                CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS intake_seen (document_id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS definitions (tag_id INTEGER PRIMARY KEY, definition TEXT NOT NULL);
                PRAGMA user_version=1;
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        value = dict(row)
        for key in ("options", "proposal", "approval"):
            value[key] = json.loads(value[key]) if value.get(key) else None
        return value

    def enqueue(self, document_id, options):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM jobs WHERE document_id=? AND status NOT IN ('applied','rejected','abandoned') ORDER BY created DESC LIMIT 1", (document_id,)).fetchone()
            if old:
                return self.decode(old), False
            now, identifier = time.time(), uuid.uuid4().hex
            db.execute("INSERT INTO jobs(id,document_id,status,options,created,updated) VALUES(?,?,'queued',?,?,?)",
                       (identifier, document_id, json.dumps(options), now, now))
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()), True

    def get(self, identifier):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())

    def jobs(self):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM jobs ORDER BY updated DESC LIMIT 200")]

    def pending_count(self):
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running','apply_queued','applying')").fetchone()[0]

    def change(self, identifier, expected, status, **values):
        allowed = {"proposal", "approval", "error", "error_code", "options"}
        assert set(values) <= allowed
        updates = {"status": status, "updated": time.time(), **values}
        updates = {k: json.dumps(v) if k in ("proposal", "approval", "options") and v is not None else v for k,v in updates.items()}
        with self.connect() as db:
            result = db.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in updates) +
                " WHERE id=? AND status IN (" + ",".join("?" for _ in expected) + ")",
                (*updates.values(), identifier, *expected))
            return result.rowcount == 1

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE status IN ('queued','apply_queued') ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            status = "running" if row["status"] == "queued" else "applying"
            db.execute("UPDATE jobs SET status=?, updated=? WHERE id=?", (status, time.time(), row["id"]))
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='error',error_code='interrupted',error='Processing was interrupted. Retry to continue.' WHERE status='running'")
            db.execute("UPDATE jobs SET status='apply_error',error_code='interrupted',error='Application was interrupted. Reconcile before continuing.' WHERE status='applying'")

    def cache_get(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def cache_set(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES(?,?)", (key, json.dumps(value)))

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))

    def definitions(self):
        with self.connect() as db:
            return {row[0]: row[1] for row in db.execute("SELECT tag_id,definition FROM definitions")}

    def define(self, tag_id, definition):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO definitions VALUES(?,?)", (tag_id, definition))

    def operation(self, job_id, name, payload):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO operations(job_id,name,payload) VALUES(?,?,?)", (job_id, name, json.dumps(payload)))
            row = dict(db.execute("SELECT * FROM operations WHERE job_id=? AND name=?", (job_id,name)).fetchone())
            row["payload"] = json.loads(row["payload"])
            row["result"] = json.loads(row["result"]) if row["result"] else None
            return row

    def finish_operation(self, job_id, name, result, complete=True):
        with self.connect() as db:
            db.execute("UPDATE operations SET result=?,complete=? WHERE job_id=? AND name=?", (json.dumps(result), int(complete), job_id, name))

    def seen(self, document_id, fingerprint=None):
        with self.connect() as db:
            if fingerprint is None:
                row = db.execute("SELECT fingerprint FROM intake_seen WHERE document_id=?", (document_id,)).fetchone()
                return row[0] if row else None
            db.execute("INSERT OR REPLACE INTO intake_seen VALUES(?,?)", (document_id, fingerprint))

    def session(self):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time()+43200))
        return token

    def authenticated(self, token):
        with self.connect() as db:
            row = db.execute("SELECT csrf FROM sessions WHERE token_hash=? AND expires>?", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            return row[0] if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
