"""Report-aligned coursework workflows. External gateways and delivery are explicit simulators."""

import base64
import csv
import hashlib
import hmac
import io
import json
import math
import secrets
import sqlite3
import struct
import tempfile
import time
import zipfile
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from cryptography.fernet import Fernet
from PIL import Image, UnidentifiedImageError
from flask import current_app, g, jsonify, request, send_file, render_template_string
from werkzeug.security import check_password_hash, generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS venue_config(id TEXT PRIMARY KEY, content TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS config_history(venue_id TEXT NOT NULL,version INTEGER NOT NULL,content TEXT NOT NULL,actor_id INTEGER REFERENCES users(id),reason TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(venue_id,version));
CREATE TRIGGER IF NOT EXISTS immutable_config_update BEFORE UPDATE ON config_history BEGIN SELECT RAISE(ABORT,'Configuration history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_config_delete BEFORE DELETE ON config_history BEGIN SELECT RAISE(ABORT,'Configuration history is append-only'); END;
CREATE TABLE IF NOT EXISTS occurrences(booking_id INTEGER NOT NULL REFERENCES bookings(id), event_date TEXT NOT NULL, PRIMARY KEY(booking_id,event_date));
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), booking_id INTEGER REFERENCES bookings(id), kind TEXT NOT NULL, filename TEXT NOT NULL, mime TEXT NOT NULL, encrypted BLOB NOT NULL, digest TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), booking_id INTEGER REFERENCES bookings(id), title TEXT NOT NULL, body TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), booking_id INTEGER, channel TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY, booking_id INTEGER NOT NULL REFERENCES bookings(id), amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'requested', provider_reference TEXT, created_at TEXT NOT NULL, UNIQUE(booking_id));
CREATE TABLE IF NOT EXISTS gateway_ledger(payment_id TEXT PRIMARY KEY REFERENCES payments(id), amount INTEGER NOT NULL, reference TEXT NOT NULL UNIQUE, signature TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS refunds(id INTEGER PRIMARY KEY, booking_id INTEGER NOT NULL REFERENCES bookings(id), amount INTEGER NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'requested', reference TEXT, decision_reason TEXT, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_refund_request ON refunds(booking_id) WHERE status IN ('requested','approved');
CREATE TABLE IF NOT EXISTS amendments(id INTEGER PRIMARY KEY, booking_id INTEGER NOT NULL REFERENCES bookings(id), proposed TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'requested', created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_amendment ON amendments(booking_id) WHERE status='requested';
CREATE TABLE IF NOT EXISTS closures(id INTEGER PRIMARY KEY, venue_id TEXT NOT NULL, event_date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_log(id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL, entity TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL, previous_hash TEXT NOT NULL, metadata_hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON event_log BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON event_log BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
CREATE TABLE IF NOT EXISTS feedback(booking_id INTEGER PRIMARY KEY REFERENCES bookings(id), rating INTEGER NOT NULL, comment TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mfa_challenges(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), session_hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS resets(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS profiles(user_id INTEGER PRIMARY KEY REFERENCES users(id), phone TEXT NOT NULL DEFAULT '', organisation TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY, booking_id INTEGER NOT NULL REFERENCES bookings(id), content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_audit_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'Booking history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_audit_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'Booking history is append-only'); END;
"""
PERMISSIONS = {
    "admin": [
        "assess",
        "assist",
        "calendar",
        "finance",
        "reports",
        "audit",
        "admin",
        "messages",
    ],
    "coordinator": ["assess", "calendar", "reports"],
    "service": ["assist", "messages"],
    "finance": ["finance", "reports"],
    "auditor": ["reports", "audit"],
}
DEMO_PASSWORD = "DemoBooking2026!"
DEMO_ACCOUNTS = [
    ("customer", "Community Hirer", "customer@demo.example"),
    ("coordinator", "Facility Coordinator", "coordinator@demo.example"),
    ("service", "Customer Service Officer", "service@demo.example"),
    ("finance", "Finance Officer", "finance@demo.example"),
    ("admin", "System Administrator", "admin@demo.example"),
    ("auditor", "Audit Reviewer", "auditor@demo.example"),
]


# Late imports avoid circular import while server.py creates its app.
def core():
    import server

    return server


def db():
    return core().db()


def fail(message, status=400):
    raise core().ApiError(message, status)


def body():
    return core().data()


def now():
    return core().now()


def txt(value, label, limit=200, required=True):
    return core().text(value, label, limit, required)


def json_dump(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def cipher():
    return current_app.extensions["cipher"]


def perms(user=None):
    user = user if user is not None else g.user
    return (
        PERMISSIONS.get(user["staff_role"], [])
        if user and user["role"] == "staff"
        else []
    )


def public_user(row):
    return (
        dict(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            role=row["role"],
            staff_role=row["staff_role"],
            permissions=perms(row),
        )
        if row
        else None
    )


def permit(permission):
    def decorator(fn):
        @wraps(fn)
        @core().require_user(staff=True)
        def wrapped(*args, **kwargs):
            if permission not in perms():
                fail("Your role cannot perform this action.", 403)
            return fn(*args, **kwargs)

        return wrapped

    return decorator


def log(action, entity="", detail=""):
    previous = (
        db()
        .execute("SELECT metadata_hash FROM event_log ORDER BY id DESC LIMIT 1")
        .fetchone()
    )
    prev = previous[0] if previous else "0" * 64
    actor = g.user["id"] if getattr(g, "user", None) else None
    stamp = now()
    payload = json_dump([actor, action, str(entity), str(detail), stamp, prev])
    digest = hmac.new(
        current_app.extensions["audit_key"], payload.encode(), hashlib.sha256
    ).hexdigest()
    db().execute(
        "INSERT INTO event_log(actor_id,action,entity,detail,created_at,previous_hash,metadata_hash) VALUES(?,?,?,?,?,?,?)",
        (actor, action, str(entity), str(detail), stamp, prev, digest),
    )


def notify(user_id, booking_id, title, message):
    db().execute(
        "INSERT INTO notifications(user_id,booking_id,title,body,created_at) VALUES(?,?,?,?,?)",
        (user_id, booking_id, title, message, now()),
    )
    email = db().execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()[0]
    db().execute(
        "INSERT INTO outbox(user_id,booking_id,channel,recipient,subject,body,created_at) VALUES(?,?,'email',?,?,?,?)",
        (user_id, booking_id, email, title, message, now()),
    )
    profile = (
        db()
        .execute("SELECT phone FROM profiles WHERE user_id=?", (user_id,))
        .fetchone()
    )
    if profile and profile[0]:
        db().execute(
            "INSERT INTO outbox(user_id,booking_id,channel,recipient,subject,body,created_at) VALUES(?,?,'sms',?,?,?,?)",
            (user_id, booking_id, profile[0], title, message, now()),
        )


def audit(booking_id, action, note):
    core().audit(booking_id, action, note)
    log(action, f"booking:{booking_id}", note)
    row = (
        db()
        .execute("SELECT user_id FROM bookings WHERE id=?", (booking_id,))
        .fetchone()
    )
    notify(
        row[0], booking_id, f'DCF-{booking_id:06d} · {action.replace("_"," ")}', note
    )


def venues(active=False):
    rows = [
        json.loads(row[0])
        for row in db().execute("SELECT content FROM venue_config ORDER BY rowid")
    ]
    return [v for v in rows if v.get("active", True)] if active else rows


def venue_for(venue_id):
    return next((v for v in venues() if v["id"] == venue_id), None)


def conflicts(venue_id, event_date, start, end, exclude=None):
    row = (
        db()
        .execute(
            "SELECT b.id FROM bookings b JOIN occurrences o ON o.booking_id=b.id WHERE b.venue_id=? AND o.event_date=? AND b.status IN ('pending','needs_info','approved') AND b.setup_time<? AND b.cleanup_time>? AND b.id<>? LIMIT 1",
            (venue_id, event_date, end, start, exclude or -1),
        )
        .fetchone()
    )
    closed = (
        db()
        .execute(
            "SELECT id FROM closures WHERE venue_id=? AND event_date=? AND start_time<? AND end_time>? LIMIT 1",
            (venue_id, event_date, end, start),
        )
        .fetchone()
    )
    return bool(row or closed)


def minute(value):
    if not isinstance(value, str) or not __import__("re").fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", value
    ):
        fail("Use a valid time in HH:MM format.")
    return int(value[:2]) * 60 + int(value[3:])


def validate(b, owner, exclude=None, require_evidence=True):
    v = venue_for(b.get("venue"))
    if not v or not v.get("active", True):
        fail("Choose an active facility.")
    first = core().validate_date(b.get("eventDate"))
    slot = b.get("slot")
    if slot not in core().SLOTS:
        fail("Choose an available time.")
    count = b.get("repeatCount", 1)
    if type(count) != int or not 1 <= count <= 12:
        fail("Choose between 1 and 12 weekly occurrences.")
    dates = [
        core().validate_date(
            (date.fromisoformat(first) + timedelta(weeks=i)).isoformat()
        )
        for i in range(count)
    ]
    attendance = b.get("attendance")
    if type(attendance) != int or not 1 <= attendance <= v["capacity"]:
        fail(f"Attendance must be between 1 and {v['capacity']}.")
    start, end = b.get("setupTime"), b.get("cleanupTime")
    sm, em = minute(start), minute(end)
    ss, se = map(minute, slot.split("–"))
    if not minute(v["opens"]) <= sm <= ss < se <= em <= minute(v["closes"]):
        fail(
            f"Setup and cleanup must cover {slot} and stay within {v['opens']}–{v['closes']}."
        )
    name = txt(b.get("eventName"), "event name", 120)
    et = b.get("eventType")
    if et not in core().EVENT_TYPES:
        fail("Choose an event type.")
    alcohol = b.get("alcohol")
    if alcohol not in ("Yes", "No"):
        fail("Answer the alcohol question.")
    if b.get("adult") is not True:
        fail("The responsible hirer must confirm they are at least 18.")
    if b.get("privacy") is not True or b.get("declaration") is not True:
        fail("Accept the privacy notice and booking conditions before submitting.")
    docs = b.get("documentIds", [])
    if (
        not isinstance(docs, list)
        or len(docs) > 10
        or any(not isinstance(d, str) for d in docs)
    ):
        fail("Invalid document selection.")
    found = []
    for doc_id in docs:
        row = (
            db()
            .execute(
                "SELECT * FROM documents WHERE id=? AND user_id=?", (doc_id, owner)
            )
            .fetchone()
        )
        if not row or (row["booking_id"] and row["booking_id"] != exclude):
            fail("A selected document is unavailable.", 403)
        found.append(row)
    required = []
    if (
        v.get("insurance_required")
        or et in ("Private celebration", "Workshop or class")
        or attendance >= v.get("insurance_threshold", 80)
    ):
        required.append("insurance")
    if alcohol == "Yes":
        required.append("permit")
    if require_evidence:
        missing = set(required) - {d["kind"] for d in found}
        if missing:
            fail("Upload the required evidence: " + ", ".join(sorted(missing)) + ".")
    for d in dates:
        if conflicts(v["id"], d, start, end, exclude):
            fail(
                f"{d}: the setup-to-cleanup period conflicts with a booking or closure. Choose another date or time.",
                409,
            )
    return dict(
        venue=v,
        dates=dates,
        slot=slot,
        event_name=name,
        event_type=et,
        attendance=attendance,
        setup_time=start,
        cleanup_time=end,
        alcohol=alcohol,
        notes=txt(b.get("notes", ""), "notes", 2000, False),
        documents=docs,
        required=required,
        amount=math.ceil((em - sm) * v["rate_cents"] / 60) * count,
        channel="assisted" if owner != g.user["id"] else "online",
    )


def owner_id(value=None):
    if value is None:
        return g.user["id"]
    if "assist" not in perms():
        fail("Assisted application access is required.", 403)
    if type(value) != int:
        fail("Choose an applicant.")
    user = (
        db()
        .execute("SELECT id FROM users WHERE id=? AND role='customer'", (value,))
        .fetchone()
    )
    if not user:
        fail("Applicant not found.", 404)
    return value


def save_version(booking_id):
    row = dict(
        db().execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    )
    row["occurrences"] = [
        r[0]
        for r in db().execute(
            "SELECT event_date FROM occurrences WHERE booking_id=? ORDER BY event_date",
            (booking_id,),
        )
    ]
    db().execute(
        "INSERT INTO versions(booking_id,content,created_at) VALUES(?,?,?)",
        (booking_id, json_dump(row), now()),
    )


def insert_booking(owner, b):
    cur = db().execute(
        "INSERT INTO bookings(user_id,venue_id,event_date,slot,event_name,event_type,attendance,setup_time,cleanup_time,alcohol,notes,created_at,amount_cents,channel,required_docs,venue_version,rate_cents_snapshot,conditions,phase) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'','submitted')",
        (
            owner,
            b["venue"]["id"],
            b["dates"][0],
            b["slot"],
            b["event_name"],
            b["event_type"],
            b["attendance"],
            b["setup_time"],
            b["cleanup_time"],
            b["alcohol"],
            b["notes"],
            now(),
            b["amount"],
            b["channel"],
            json_dump(b["required"]),
            b["venue"]["version"],
            b["venue"]["rate_cents"],
        ),
    )
    booking_id = cur.lastrowid
    db().executemany(
        "INSERT INTO occurrences VALUES(?,?)", [(booking_id, d) for d in b["dates"]]
    )
    for d in b["documents"]:
        db().execute("UPDATE documents SET booking_id=? WHERE id=?", (booking_id, d))
    save_version(booking_id)
    audit(
        booking_id,
        "pending",
        f"Application submitted via {b['channel']}; {len(b['dates'])} occurrence(s).",
    )
    db().execute("DELETE FROM drafts WHERE user_id=?", (owner,))
    return booking_id


def enrich(result):
    booking_id = result["id"]
    result["venue_name"] = (
        venue_for(result["venue_id"]) or {"name": result["venue_id"]}
    )["name"]
    result["occurrences"] = [
        r[0]
        for r in db().execute(
            "SELECT event_date FROM occurrences WHERE booking_id=? ORDER BY event_date",
            (booking_id,),
        )
    ]
    result["required_docs"] = json.loads(result["required_docs"])
    result["documents"] = [
        dict(r)
        for r in db().execute(
            "SELECT id,kind,filename,verified,created_at FROM documents WHERE booking_id=?",
            (booking_id,),
        )
    ]
    payment = (
        db()
        .execute("SELECT * FROM payments WHERE booking_id=?", (booking_id,))
        .fetchone()
    )
    result["payment"] = dict(payment) if payment else None
    result["refunds"] = [
        dict(r)
        for r in db().execute(
            "SELECT * FROM refunds WHERE booking_id=? ORDER BY id DESC", (booking_id,)
        )
    ]
    result["amendments"] = [
        dict(r)
        for r in db().execute(
            "SELECT * FROM amendments WHERE booking_id=? ORDER BY id DESC",
            (booking_id,),
        )
    ]
    for amendment in result["amendments"]:
        amendment["proposed"] = json.loads(amendment["proposed"])
    result["version_count"] = (
        db()
        .execute("SELECT COUNT(*) FROM versions WHERE booking_id=?", (booking_id,))
        .fetchone()[0]
    )
    result["feedback"] = (
        dict(r)
        if (
            r := db()
            .execute("SELECT * FROM feedback WHERE booking_id=?", (booking_id,))
            .fetchone()
        )
        else None
    )
    result["phase"] = (
        "confirmed"
        if result["status"] == "approved" and payment and payment["status"] == "paid"
        else result["phase"]
    )
    if result["completed"]:
        result["phase"] = "completed"
    if (
        g.user
        and g.user["role"] == "staff"
        and g.user["staff_role"] in ("finance", "auditor")
        and result["user_id"] != g.user["id"]
    ):
        result["notes"] = ""
        result["documents"] = []
        result["required_docs"] = []
        result["amendments"] = []
        result["history"] = [
            h
            for h in result["history"]
            if h["action"]
            in (
                "approved",
                "cancelled",
                "payment_received",
                "payment_reconciled",
                "payment_processing",
                "payment_declined",
                "waiver_applied",
                "refund_requested",
                "refund_decided",
            )
        ]
    return result


def totp(secret, stamp=None):
    stamp = time.time() if stamp is None else stamp
    key = base64.b32decode(secret)
    raw = hmac.new(key, struct.pack(">Q", int(stamp) // 30), hashlib.sha1).digest()
    offset = raw[-1] & 15
    return str(
        (struct.unpack(">I", raw[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000
    ).zfill(6)


def create_challenge(user):
    setup = not bool(user["totp_secret"])
    secret = base64.b32encode(secrets.token_bytes(20)).decode()
    if setup:
        db().execute(
            "UPDATE users SET totp_secret=? WHERE id=?",
            (cipher().encrypt(secret.encode()).decode(), user["id"]),
        )
    else:
        secret = cipher().decrypt(user["totp_secret"].encode()).decode()
    challenge = secrets.token_urlsafe(32)
    db().execute(
        "DELETE FROM mfa_challenges WHERE expires<? OR user_id=?",
        (time.time(), user["id"]),
    )
    db().execute(
        "INSERT INTO mfa_challenges(id,user_id,session_hash,expires) VALUES(?,?,?,?)",
        (challenge, user["id"], g.session["token_hash"], time.time() + 300),
    )
    db().commit()
    result = dict(
        mfa_required=True,
        challenge=challenge,
        enrollment_secret=secret if setup else None,
    )
    if current_app.config["DEMO_MODE"]:
        result["demo_code"] = totp(secret)
    return result


def initialize(app, seed_venues):
    with sqlite3.connect(app.config["DATABASE"], timeout=30) as c:
        c.executescript(SCHEMA)
        c.execute("BEGIN IMMEDIATE")
        migrations = {
            "users": {
                "staff_role": "TEXT NOT NULL DEFAULT 'coordinator'",
                "totp_secret": "TEXT NOT NULL DEFAULT ''",
                "totp_counter": "INTEGER NOT NULL DEFAULT -1",
            },
            "bookings": {
                "amount_cents": "INTEGER NOT NULL DEFAULT 0",
                "channel": "TEXT NOT NULL DEFAULT 'online'",
                "required_docs": "TEXT NOT NULL DEFAULT '[]'",
                "conditions": "TEXT NOT NULL DEFAULT ''",
                "phase": "TEXT NOT NULL DEFAULT 'submitted'",
                "completed": "INTEGER NOT NULL DEFAULT 0",
                "venue_version": "INTEGER NOT NULL DEFAULT 1",
                "rate_cents_snapshot": "INTEGER NOT NULL DEFAULT 0",
            },
        }
        for table, columns in migrations.items():
            existing = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in existing:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        for index, v in enumerate(seed_venues):
            item = dict(
                v,
                rate_cents=[4500, 3500, 2500][index],
                equipment=(
                    ["Tables and chairs", "Kitchenette", "Projector"]
                    if index == 0
                    else ["Tables and chairs", "Whiteboard"]
                ),
                description="A flexible space for local groups, classes and celebrations.",
                opens="06:00",
                closes="23:59",
                active=True,
                insurance_required=False,
                insurance_threshold=80,
                conditions="Hirer must be 18+. Include setup and cleaning. Keep exits clear. Staff review insurance and alcohol permits when required.",
                version=1,
            )
            c.execute(
                "INSERT OR IGNORE INTO venue_config(id,content) VALUES(?,?)",
                (v["id"], json_dump(item)),
            )
        c.execute(
            "INSERT OR IGNORE INTO occurrences SELECT id,event_date FROM bookings"
        )
        c.execute(
            "INSERT OR IGNORE INTO config_history SELECT id,version,content,NULL,'Initial configuration snapshot',? FROM venue_config",
            (now(),),
        )
        key_path = Path(
            app.config.get("KEY_PATH")
            or str(Path(app.config["DATABASE"]).with_suffix(".key"))
        )
        if not key_path.exists():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            with key_path.open("xb") as f:
                f.write(Fernet.generate_key())
            key_path.chmod(0o600)
        key = key_path.read_bytes()
        app.extensions["cipher"] = Fernet(key)
        app.extensions["audit_key"] = hashlib.sha256(key + b"audit-integrity").digest()
        app.config["KEY_PATH"] = str(key_path)
        c.commit()


def create_payment(booking_id, amount):
    if (
        not db()
        .execute("SELECT id FROM payments WHERE booking_id=?", (booking_id,))
        .fetchone()
    ):
        db().execute(
            "INSERT INTO payments(id,booking_id,amount,created_at) VALUES(?,?,?,?)",
            (secrets.token_urlsafe(24), booking_id, amount, now()),
        )


def register(app):
    initialize(app, core().VENUES)
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
    app.config.setdefault("DEMO_MODE", False)

    def log_auth_endpoint(endpoint, action):
        original = app.view_functions[endpoint]

        @wraps(original)
        def wrapped(*args, **kwargs):
            response = original(*args, **kwargs)
            if endpoint == "register":
                payload = (
                    response[0].get_json()
                    if isinstance(response, tuple)
                    else response.get_json()
                )
                g.user = (
                    db()
                    .execute("SELECT * FROM users WHERE id=?", (payload["user"]["id"],))
                    .fetchone()
                )
            log(action, "account", "Authentication state changed")
            db().commit()
            return response

        app.view_functions[endpoint] = wrapped

    log_auth_endpoint("register", "account_registered")
    log_auth_endpoint("logout", "logout")
    log_auth_endpoint("change_password", "password_changed")

    @app.errorhandler(core().ApiError)
    def error(err):
        if err.status in (401, 403, 409, 429) or request.path.startswith(
            "/api/documents"
        ):
            db().rollback()
            log("request_denied", request.path, err.message)
            db().commit()
        return jsonify(error=err.message), err.status

    def session_info():
        csrf = g.session["csrf"] if g.session else app.new_session()
        return jsonify(
            user=public_user(g.user),
            csrf=csrf,
            demo_mode=app.config["DEMO_MODE"],
            payment_mode="simulated",
        )

    app.add_url_rule("/api/session", "session_info", session_info, methods=["GET"])

    def login():
        app.rate_limit()
        b = body()
        email = core().identity(b.get("email"))
        supplied = b.get("password")
        if not isinstance(supplied, str) or len(supplied) > 128:
            fail("Invalid email or password.", 401)
        user = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        valid = check_password_hash(
            user["password_hash"] if user else app.config["DUMMY_HASH"], supplied
        )
        if not user or not valid:
            fail("Invalid email or password.", 401)
        portal = b.get("portal")
        if portal is not None and portal not in ("customer", "admin"):
            fail("Choose the customer or admin portal.")
        if portal == "admin" and user["role"] != "staff":
            fail(
                "This is a customer account. Sign in through the Customer portal.", 403
            )
        if portal == "customer" and user["role"] != "customer":
            fail("This is a staff account. Sign in through the Admin portal.", 403)
        if user["role"] == "staff":
            return jsonify(create_challenge(user))
        g.user = user
        log("login", "account", "Password authentication")
        db().commit()
        return jsonify(user=public_user(user), csrf=app.new_session(user["id"]))

    app.add_url_rule("/api/auth/login", "login", login, methods=["POST"])

    @app.post("/api/auth/mfa")
    def verify_mfa():
        b = body()
        challenge = txt(b.get("challenge"), "challenge", 100)
        db().execute("BEGIN IMMEDIATE")
        row = (
            db()
            .execute(
                "SELECT * FROM mfa_challenges WHERE id=? AND expires>? AND session_hash=?",
                (challenge, time.time(), g.session["token_hash"]),
            )
            .fetchone()
        )
        if not row or row["attempts"] >= 5:
            fail("Verification expired. Sign in again.", 401)
        user = (
            db().execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
        )
        secret = cipher().decrypt(user["totp_secret"].encode()).decode()
        code = str(b.get("code", ""))
        counter = int(time.time()) // 30
        valid = next(
            (
                c
                for c in (counter - 1, counter, counter + 1)
                if c > user["totp_counter"]
                and hmac.compare_digest(totp(secret, c * 30), code)
            ),
            None,
        )
        if valid is None:
            db().execute(
                "UPDATE mfa_challenges SET attempts=attempts+1 WHERE id=?", (challenge,)
            )
            db().commit()
            fail("Invalid or already-used verification code.", 401)
        db().execute("UPDATE users SET totp_counter=? WHERE id=?", (valid, user["id"]))
        db().execute("DELETE FROM mfa_challenges WHERE user_id=?", (user["id"],))
        g.user = user
        log("staff_login", "account", "Password and TOTP verified")
        db().commit()
        return jsonify(user=public_user(user), csrf=app.new_session(user["id"]))

    @app.post("/api/auth/reset-request")
    def reset_request():
        app.rate_limit()
        email = core().identity(body().get("email"))
        user = (
            db().execute("SELECT id,role FROM users WHERE email=?", (email,)).fetchone()
        )
        if user:
            token = secrets.token_urlsafe(32)
            db().execute("DELETE FROM resets WHERE user_id=?", (user[0],))
            db().execute(
                "INSERT INTO resets VALUES(?,?,?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    user[0],
                    time.time() + 900,
                ),
            )
            notify(
                user[0],
                None,
                "Password recovery",
                f"Use this one-time link within 15 minutes: /{'admin' if user['role'] == 'staff' else 'customer'}?reset={token}",
            )
            log("password_reset_requested", "account", "Recovery queued")
            db().commit()
        return jsonify(
            message="If this account exists, a recovery message has been queued. In the local demonstration, open Demo mailbox."
        )

    @app.post("/api/auth/reset")
    def reset_password():
        app.rate_limit()
        b = body()
        token = txt(b.get("token"), "recovery token", 100)
        hashed = generate_password_hash(core().password(b.get("password")))
        db().execute("BEGIN IMMEDIATE")
        row = (
            db()
            .execute(
                "SELECT * FROM resets WHERE token_hash=? AND expires>?",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            )
            .fetchone()
        )
        if not row:
            fail("Recovery link is invalid or expired.")
        db().execute(
            "UPDATE users SET password_hash=? WHERE id=?", (hashed, row["user_id"])
        )
        db().execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
        db().execute("DELETE FROM mfa_challenges WHERE user_id=?", (row["user_id"],))
        db().execute("DELETE FROM resets WHERE user_id=?", (row["user_id"],))
        log("password_reset", "account", f"Account {row['user_id']}")
        db().commit()
        return jsonify(ok=True, csrf=app.new_session())

    @app.get("/api/demo")
    def demo_info():
        if not app.config["DEMO_MODE"]:
            fail("Local demonstration mode is disabled.", 404)
        return jsonify(
            accounts=[
                dict(role=role, name=name, email=email)
                for role, name, email in DEMO_ACCOUNTS
            ],
            password=DEMO_PASSWORD,
        )

    @app.get("/api/demo/mailbox")
    def demo_mailbox():
        if not app.config["DEMO_MODE"]:
            fail("Local demonstration mode is disabled.", 404)
        # Only synthetic sample accounts are exposed without authentication.
        return jsonify(
            messages=[
                dict(r)
                for r in db().execute(
                    "SELECT id,recipient,subject,body,status,created_at FROM outbox WHERE recipient IN ("
                    + ",".join("?" for _ in DEMO_ACCOUNTS)
                    + ") ORDER BY id DESC LIMIT 50",
                    tuple(e for _, _, e in DEMO_ACCOUNTS),
                )
            ]
        )

    @app.get("/demo-file/<filename>")
    def sample_file(filename):
        if filename not in ("insurance-demo.pdf", "permit-demo.pdf"):
            fail("Sample not found.", 404)
        return core().send_from_directory(
            core().ROOT / "samples", filename, as_attachment=True
        )

    @app.get("/api/documents")
    @core().require_user()
    def list_documents():
        applicant = request.args.get("applicant")
        owner = (
            owner_id(int(applicant))
            if applicant and applicant.isdigit()
            else g.user["id"]
        )
        return jsonify(
            documents=[
                dict(r)
                for r in db().execute(
                    "SELECT id,filename,kind,verified,booking_id FROM documents WHERE user_id=? ORDER BY created_at DESC",
                    (owner,),
                )
            ]
        )

    @app.route("/api/profile", methods=["GET", "PUT"])
    @core().require_user()
    def profile():
        if request.method == "PUT":
            b = body()
            name = txt(b.get("name"), "name", 100)
            phone = txt(b.get("phone", ""), "phone", 40, False)
            organisation = txt(b.get("organisation", ""), "organisation", 120, False)
            db().execute("UPDATE users SET name=? WHERE id=?", (name, g.user["id"]))
            db().execute(
                "INSERT INTO profiles VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET phone=excluded.phone,organisation=excluded.organisation",
                (g.user["id"], phone, organisation),
            )
            log("profile_updated", "account", "Contact details updated")
            db().commit()
        row = (
            db()
            .execute("SELECT * FROM profiles WHERE user_id=?", (g.user["id"],))
            .fetchone()
        )
        user = (
            db().execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
        )
        return jsonify(
            user=public_user(user),
            profile=dict(row) if row else dict(phone="", organisation=""),
        )

    def venue_list():
        return jsonify(
            venues=venues(active=True),
            today=core().today().isoformat(),
            max_date=(core().today() + timedelta(days=365)).isoformat(),
        )

    app.add_url_rule("/api/venues", "venues", venue_list, methods=["GET"])

    def availability():
        v = venue_for(request.args.get("venue"))
        d = core().validate_date(request.args.get("date"))
        if not v or not v["active"]:
            fail("Choose an active facility.")
        return jsonify(
            slots=[
                dict(
                    value=s,
                    available=not conflicts(v["id"], d, *s.split("–"))
                    and minute(v["opens"]) <= minute(s.split("–")[0])
                    and minute(v["closes"]) >= minute(s.split("–")[1]),
                )
                for s in core().SLOTS
            ],
            closures=[
                dict(r)
                for r in db().execute(
                    "SELECT event_date,start_time,end_time,reason FROM closures WHERE venue_id=? AND event_date=?",
                    (v["id"], d),
                )
            ],
        )

    app.add_url_rule("/api/availability", "availability", availability, methods=["GET"])

    @core().require_user()
    def draft():
        applicant = request.args.get("applicant")
        owner = (
            owner_id(int(applicant))
            if applicant and applicant.isdigit()
            else g.user["id"]
        )
        if request.method == "GET":
            row = (
                db()
                .execute("SELECT content FROM drafts WHERE user_id=?", (owner,))
                .fetchone()
            )
            return jsonify(draft=json.loads(row[0]) if row else None)
        if request.method == "PUT":
            value = body()
            if len(json_dump(value)) > 20000:
                fail("Draft is too large.")
            db().execute(
                "INSERT INTO drafts VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET content=excluded.content",
                (owner, json_dump(value)),
            )
        else:
            db().execute("DELETE FROM drafts WHERE user_id=?", (owner,))
        log("draft_saved", f"customer:{owner}", request.method)
        db().commit()
        return jsonify(ok=True)

    app.add_url_rule("/api/draft", "draft", draft, methods=["GET", "PUT", "DELETE"])

    @core().require_user()
    def book():
        b = body()
        owner = owner_id(b.get("applicantId"))
        db().execute("BEGIN IMMEDIATE")
        validated = validate(b, owner)
        booking_id = insert_booking(owner, validated)
        db().commit()
        return jsonify(booking=core().serialize(core().booking_row(booking_id))), 201

    app.add_url_rule("/api/bookings", "book", book, methods=["POST"])

    @core().require_user()
    def booking_list():
        query = "SELECT b.*,u.name AS customer_name,u.email AS customer_email FROM bookings b JOIN users u ON u.id=b.user_id"
        args = ()
        if g.user["role"] != "staff":
            query += " WHERE b.user_id=?"
            args = (g.user["id"],)
        return jsonify(
            bookings=[
                core().serialize(r)
                for r in db().execute(query + " ORDER BY b.id DESC", args)
            ]
        )

    app.add_url_rule("/api/bookings", "bookings", booking_list, methods=["GET"])

    @app.get("/api/bookings/<int:booking_id>")
    @core().require_user()
    def get_booking(booking_id):
        return jsonify(booking=core().serialize(core().booking_row(booking_id)))

    @app.post("/api/documents")
    @core().require_user()
    def upload():
        owner = (
            owner_id(int(request.form["applicantId"]))
            if request.form.get("applicantId", "").isdigit()
            else g.user["id"]
        )
        kind = request.form.get("kind")
        if kind not in ("insurance", "permit", "other"):
            fail("Choose a document category.")
        f = request.files.get("file")
        if not f:
            fail("Choose a file.")
        content = f.read(5 * 1024 * 1024 + 1)
        if not content or len(content) > 5 * 1024 * 1024:
            fail("Files must be between 1 byte and 5 MB.")
        filename = Path(f.filename or "").name.replace("\\", "_")[:120]
        suffix = Path(filename).suffix.lower()
        if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in content:
            log("unsafe_upload_rejected", "document", "Test malware signature")
            db().commit()
            fail("Unsafe file rejected.")
        mime = None
        if (
            suffix == ".pdf"
            and content.startswith(b"%PDF-")
            and b"%%EOF" in content[-2048:]
        ):
            if any(
                x in content.lower()
                for x in (
                    b"/javascript",
                    b"/js ",
                    b"/launch",
                    b"/embeddedfile",
                    b"/openaction",
                )
            ):
                fail("PDF active content is not accepted. Upload a plain document.")
            mime = "application/pdf"
        elif suffix in (".png", ".jpg", ".jpeg"):
            try:
                with Image.open(io.BytesIO(content)) as image:
                    fmt = image.format
                    if image.width * image.height > 20_000_000:
                        fail("Image dimensions are too large.")
                    image.verify()
                if fmt == "PNG" and suffix == ".png":
                    mime = "image/png"
                if fmt == "JPEG" and suffix in (".jpg", ".jpeg"):
                    mime = "image/jpeg"
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                pass
        if not mime:
            fail(
                "Only valid PDF, PNG and JPEG files are accepted; the extension must match the content."
            )
        booking_id = request.form.get("bookingId")
        if booking_id:
            if not booking_id.isdigit():
                fail("Invalid booking.")
            booking_id = int(booking_id)
            row = core().booking_row(booking_id)
            if row["user_id"] != owner or row["status"] not in (
                "pending",
                "needs_info",
            ):
                fail("Evidence cannot be changed for this request.", 409)
        doc_id = secrets.token_urlsafe(24)
        db().execute(
            "INSERT INTO documents(id,user_id,booking_id,kind,filename,mime,encrypted,digest,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                doc_id,
                owner,
                booking_id,
                kind,
                filename,
                mime,
                cipher().encrypt(content),
                hashlib.sha256(content).hexdigest(),
                now(),
            ),
        )
        log("document_uploaded", f"document:{doc_id}", kind)
        if booking_id:
            audit(booking_id, "evidence_uploaded", f"{kind} evidence added.")
        db().commit()
        return (
            jsonify(document=dict(id=doc_id, filename=filename, kind=kind, verified=0)),
            201,
        )

    @app.get("/api/documents/<doc_id>")
    @core().require_user()
    def download(doc_id):
        doc = db().execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not doc or (
            doc["user_id"] != g.user["id"]
            and not set(perms()) & {"assess", "assist", "admin"}
        ):
            fail("Document not found.", 404)
        decrypted = cipher().decrypt(doc["encrypted"])
        if hashlib.sha256(decrypted).hexdigest() != doc["digest"]:
            fail("Document integrity check failed.", 409)
        log("document_downloaded", f"document:{doc_id}", "Authenticated download")
        db().commit()
        return send_file(
            io.BytesIO(decrypted),
            download_name=doc["filename"],
            mimetype=doc["mime"],
            as_attachment=True,
        )

    @app.post("/api/documents/<doc_id>/verify")
    @permit("assess")
    def verify_document(doc_id):
        doc = db().execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not doc or not doc["booking_id"]:
            fail("Attached evidence not found.", 404)
        row = core().booking_row(doc["booking_id"])
        if row["user_id"] == g.user["id"]:
            fail("You cannot verify your own evidence.", 403)
        note = txt(body().get("note"), "verification reason", 500)
        db().execute("UPDATE documents SET verified=1 WHERE id=?", (doc_id,))
        audit(doc["booking_id"], "evidence_verified", note)
        db().commit()
        return jsonify(ok=True)

    @permit("assess")
    def decision(booking_id):
        b = body()
        status = b.get("status")
        note = txt(b.get("note"), "decision reason", 2000)
        if status not in ("approved", "rejected", "needs_info"):
            fail("Choose a valid decision.")
        conditions = txt(b.get("conditions", ""), "conditions", 2000, False)
        db().execute("BEGIN IMMEDIATE")
        row = core().booking_row(booking_id)
        if (
            row["status"] not in ("pending", "needs_info")
            or row["completed"]
            or row["event_date"] <= core().today().isoformat()
        ):
            fail("This application is not awaiting a decision.", 409)
        if row["user_id"] == g.user["id"]:
            fail("Another coordinator must assess your request.", 403)
        if status == "approved":
            required = set(json.loads(row["required_docs"]))
            verified = {
                r[0]
                for r in db().execute(
                    "SELECT kind FROM documents WHERE booking_id=? AND verified=1",
                    (booking_id,),
                )
            }
            if required - verified:
                fail(
                    "Verify all required evidence before approval: "
                    + ", ".join(sorted(required - verified))
                )
            for d in db().execute(
                "SELECT event_date FROM occurrences WHERE booking_id=?", (booking_id,)
            ):
                if conflicts(
                    row["venue_id"],
                    d[0],
                    row["setup_time"],
                    row["cleanup_time"],
                    booking_id,
                ):
                    fail("The calendar must be reconciled before approval.", 409)
            create_payment(booking_id, row["amount_cents"])
            if row["amount_cents"] == 0:
                db().execute(
                    "UPDATE payments SET status='paid',provider_reference='WAIVED' WHERE booking_id=?",
                    (booking_id,),
                )
        db().execute(
            "UPDATE bookings SET status=?,conditions=?,phase=? WHERE id=?",
            (
                status,
                conditions,
                "payment_pending" if status == "approved" else "submitted",
                booking_id,
            ),
        )
        save_version(booking_id)
        audit(
            booking_id,
            status,
            note + ("\nConditions: " + conditions if conditions else ""),
        )
        db().commit()
        return jsonify(booking=core().serialize(core().booking_row(booking_id)))

    app.add_url_rule(
        "/api/bookings/<int:booking_id>/decision",
        "decision",
        decision,
        methods=["POST"],
    )

    @app.post("/api/bookings/<int:booking_id>/start-review")
    @permit("assess")
    def start_review(booking_id):
        row = core().booking_row(booking_id)
        if row["status"] != "pending":
            fail("Only pending requests can enter review.", 409)
        db().execute(
            "UPDATE bookings SET phase='under_review' WHERE id=?", (booking_id,)
        )
        audit(booking_id, "under_review", "Assessment started.")
        db().commit()
        return jsonify(ok=True)

    @core().require_user()
    def cancel(booking_id):
        db().execute("BEGIN IMMEDIATE")
        row = core().booking_row(booking_id)
        if row["user_id"] != g.user["id"] and "assist" not in perms():
            fail("Only the applicant or an assisted-service officer can cancel.", 403)
        if (
            row["status"] not in core().HELD
            or row["completed"]
            or row["event_date"] <= core().today().isoformat()
        ):
            fail("This booking can no longer be cancelled.", 409)
        db().execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
        save_version(booking_id)
        audit(
            booking_id,
            "cancelled",
            "Cancelled; all occurrences released. Refunds require finance approval.",
        )
        db().commit()
        return jsonify(booking=core().serialize(core().booking_row(booking_id)))

    app.add_url_rule(
        "/api/bookings/<int:booking_id>/cancel", "cancel", cancel, methods=["POST"]
    )

    @core().require_user()
    def reply(booking_id):
        note = txt(body().get("note"), "reply", 2000)
        db().execute("BEGIN IMMEDIATE")
        row = core().booking_row(booking_id)
        if row["user_id"] != g.user["id"] and "assist" not in perms():
            fail("This is not your application.", 403)
        if row["status"] != "needs_info":
            fail("This application is not waiting for information.", 409)
        db().execute(
            "UPDATE bookings SET status='pending',phase='submitted' WHERE id=?",
            (booking_id,),
        )
        audit(booking_id, "pending", note)
        db().commit()
        return jsonify(booking=core().serialize(core().booking_row(booking_id)))

    app.add_url_rule(
        "/api/bookings/<int:booking_id>/reply", "reply", reply, methods=["POST"]
    )

    @app.post("/api/bookings/<int:booking_id>/amend")
    @core().require_user()
    def amend(booking_id):
        b = body()
        note = txt(b.get("reason"), "amendment reason", 1000)
        db().execute("BEGIN IMMEDIATE")
        row = core().booking_row(booking_id)
        if row["user_id"] != g.user["id"] and "assist" not in perms():
            fail("This is not your booking.", 403)
        if row["status"] not in core().HELD or row["completed"]:
            fail("This booking cannot be amended.", 409)
        proposed = b.get("proposed")
        if not isinstance(proposed, dict):
            fail("Enter the proposed booking details.")
        validate(proposed, row["user_id"], booking_id)
        if (
            db()
            .execute(
                "SELECT id FROM amendments WHERE booking_id=? AND status='requested'",
                (booking_id,),
            )
            .fetchone()
        ):
            fail("An amendment is already awaiting review.", 409)
        db().execute(
            "INSERT INTO amendments(booking_id,proposed,reason,created_at) VALUES(?,?,?,?)",
            (booking_id, json_dump(proposed), note, now()),
        )
        audit(booking_id, "amendment_requested", note)
        db().commit()
        return jsonify(ok=True), 201

    @app.post("/api/amendments/<int:amendment_id>/decision")
    @permit("assess")
    def amendment_decision(amendment_id):
        b = body()
        note = txt(b.get("note"), "amendment decision reason", 1000)
        accepted = b.get("approve")
        if type(accepted) != bool:
            fail("Choose approve or reject.")
        db().execute("BEGIN IMMEDIATE")
        a = (
            db()
            .execute("SELECT * FROM amendments WHERE id=?", (amendment_id,))
            .fetchone()
        )
        if not a or a["status"] != "requested":
            fail("Amendment is no longer pending.", 409)
        row = core().booking_row(a["booking_id"])
        if (
            row["status"] not in core().HELD
            or row["user_id"] == g.user["id"]
            or row["completed"]
        ):
            fail("This amendment cannot be decided.", 409)
        if accepted:
            v = validate(json.loads(a["proposed"]), row["user_id"], row["id"])
            payment = (
                db()
                .execute("SELECT * FROM payments WHERE booking_id=?", (row["id"],))
                .fetchone()
            )
            if (
                payment
                and payment["status"] == "paid"
                and v["amount"] != row["amount_cents"]
            ):
                fail(
                    "Paid amendments must keep the same charge. Cancel and request a refund before choosing a differently priced booking.",
                    409,
                )
            db().execute(
                "UPDATE bookings SET venue_id=?,event_date=?,slot=?,event_name=?,event_type=?,attendance=?,setup_time=?,cleanup_time=?,alcohol=?,notes=?,amount_cents=?,required_docs=?,venue_version=?,rate_cents_snapshot=?,status='pending',phase='submitted' WHERE id=?",
                (
                    v["venue"]["id"],
                    v["dates"][0],
                    v["slot"],
                    v["event_name"],
                    v["event_type"],
                    v["attendance"],
                    v["setup_time"],
                    v["cleanup_time"],
                    v["alcohol"],
                    v["notes"],
                    v["amount"],
                    json_dump(v["required"]),
                    v["venue"]["version"],
                    v["venue"]["rate_cents"],
                    row["id"],
                ),
            )
            db().execute("DELETE FROM occurrences WHERE booking_id=?", (row["id"],))
            db().executemany(
                "INSERT INTO occurrences VALUES(?,?)",
                [(row["id"], d) for d in v["dates"]],
            )
            for doc in v["documents"]:
                db().execute(
                    "UPDATE documents SET booking_id=? WHERE id=?", (row["id"], doc)
                )
            if payment and payment["status"] != "paid":
                db().execute(
                    "UPDATE payments SET amount=?,status='requested' WHERE id=?",
                    (v["amount"], payment["id"]),
                )
            save_version(row["id"])
        db().execute(
            "UPDATE amendments SET status=? WHERE id=?",
            ("approved" if accepted else "rejected", amendment_id),
        )
        audit(row["id"], "amendment_decided", note)
        db().commit()
        return jsonify(ok=True)

    @app.post("/api/bookings/<int:booking_id>/complete")
    @permit("assess")
    def complete(booking_id):
        row = core().booking_row(booking_id)
        p = (
            db()
            .execute("SELECT status FROM payments WHERE booking_id=?", (booking_id,))
            .fetchone()
        )
        if row["status"] != "approved" or not p or p[0] != "paid" or row["completed"]:
            fail("Only confirmed, paid bookings can be completed.", 409)
        if row["user_id"] == g.user["id"]:
            fail("Another coordinator must complete this booking.", 403)
        note = txt(body().get("note"), "completion note", 1000)
        if (
            not app.config["DEMO_MODE"]
            and max(
                r[0]
                for r in db().execute(
                    "SELECT event_date FROM occurrences WHERE booking_id=?",
                    (booking_id,),
                )
            )
            >= core().today().isoformat()
        ):
            fail("Wait until all occurrences have finished.")
        db().execute(
            "UPDATE bookings SET completed=1,phase='completed' WHERE id=?",
            (booking_id,),
        )
        audit(booking_id, "completed", note)
        db().commit()
        return jsonify(ok=True)

    @app.post("/api/bookings/<int:booking_id>/feedback")
    @core().require_user()
    def feedback(booking_id):
        row = core().booking_row(booking_id)
        b = body()
        if row["user_id"] != g.user["id"] or row["status"] != "approved":
            fail("Feedback is available to the applicant after approval.", 403)
        if type(b.get("rating")) != int or not 1 <= b["rating"] <= 5:
            fail("Choose a rating from 1 to 5.")
        db().execute(
            "INSERT INTO feedback VALUES(?,?,?,?) ON CONFLICT(booking_id) DO UPDATE SET rating=excluded.rating,comment=excluded.comment,created_at=excluded.created_at",
            (
                booking_id,
                b["rating"],
                txt(b.get("comment", ""), "feedback", 1000, False),
                now(),
            ),
        )
        log("feedback_received", f"booking:{booking_id}", "Rating recorded")
        db().commit()
        return jsonify(ok=True)

    @app.get("/api/notifications")
    @core().require_user()
    def notifications():
        return jsonify(
            notifications=[
                dict(r)
                for r in db().execute(
                    "SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100",
                    (g.user["id"],),
                )
            ]
        )

    @app.post("/api/notifications/<int:notification_id>/read")
    @core().require_user()
    def mark_read(notification_id):
        db().execute(
            "UPDATE notifications SET read=1 WHERE id=? AND user_id=?",
            (notification_id, g.user["id"]),
        )
        db().commit()
        return jsonify(ok=True)

    @app.get("/api/staff/customers")
    @permit("assist")
    def customers():
        return jsonify(
            customers=[
                dict(r)
                for r in db().execute(
                    "SELECT id,name,email FROM users WHERE role='customer' ORDER BY name"
                )
            ]
        )

    @app.post("/api/staff/customers")
    @permit("assist")
    def create_customer():
        b = body()
        email = core().identity(b.get("email"))
        name = txt(b.get("name"), "applicant name", 100)
        try:
            cur = db().execute(
                "INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,'customer',?)",
                (name, email, generate_password_hash(secrets.token_urlsafe(40)), now()),
            )
        except sqlite3.IntegrityError:
            fail("This email already has an account.", 409)
        token = secrets.token_urlsafe(32)
        db().execute(
            "INSERT INTO resets VALUES(?,?,?)",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                cur.lastrowid,
                time.time() + 900,
            ),
        )
        notify(
            cur.lastrowid,
            None,
            "Activate your assisted account",
            f"Set your password within 15 minutes: /?reset={token}",
        )
        log(
            "assisted_customer_created",
            f"customer:{cur.lastrowid}",
            "Account activation queued",
        )
        db().commit()
        return jsonify(customer=dict(id=cur.lastrowid, email=email, name=name)), 201

    @app.get("/api/staff/outbox")
    @permit("messages")
    def outbox():
        return jsonify(
            messages=[
                dict(r)
                for r in db().execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 100")
            ]
        )

    @app.post("/api/staff/outbox/<int:message_id>/retry")
    @permit("messages")
    def retry_message(message_id):
        outcome = body().get("outcome", "delivered")
        if outcome not in ("delivered", "failed"):
            fail("Choose a delivery outcome.")
        db().execute(
            "UPDATE outbox SET status=?,attempts=attempts+1 WHERE id=?",
            (outcome, message_id),
        )
        log("notification_delivery", f"message:{message_id}", f"Simulator: {outcome}")
        db().commit()
        return jsonify(ok=True)

    @app.get("/api/calendar")
    @core().require_user(staff=True)
    def calendar():
        if not set(perms()) & {"calendar", "assist"}:
            fail("Calendar access is required.", 403)
        return jsonify(
            entries=[
                dict(r)
                for r in db().execute(
                    "SELECT b.id,b.venue_id,o.event_date,b.setup_time,b.cleanup_time,b.status,b.event_name FROM bookings b JOIN occurrences o ON o.booking_id=b.id WHERE b.status IN ('pending','needs_info','approved') ORDER BY o.event_date,b.setup_time"
                )
            ],
            closures=[
                dict(r)
                for r in db().execute("SELECT * FROM closures ORDER BY event_date")
            ],
            venues=venues(),
        )

    @app.post("/api/closures")
    @permit("calendar")
    def close_venue():
        b = body()
        v = venue_for(b.get("venue"))
        d = core().validate_date(b.get("date"))
        start, end = b.get("start"), b.get("end")
        if not v or not minute(v["opens"]) <= minute(start) < minute(end) <= minute(
            v["closes"]
        ):
            fail("Choose valid facility access hours.")
        reason = txt(b.get("reason"), "closure reason", 500)
        db().execute("BEGIN IMMEDIATE")
        if conflicts(v["id"], d, start, end):
            fail(
                "Move or cancel conflicting reservations before adding this closure.",
                409,
            )
        db().execute(
            "INSERT INTO closures(venue_id,event_date,start_time,end_time,reason,created_at) VALUES(?,?,?,?,?,?)",
            (v["id"], d, start, end, reason, now()),
        )
        log("closure_created", v["id"], reason)
        db().commit()
        return jsonify(ok=True), 201

    @app.delete("/api/closures/<int:closure_id>")
    @permit("calendar")
    def remove_closure(closure_id):
        note = txt(body().get("note"), "reopening reason", 500)
        db().execute("DELETE FROM closures WHERE id=?", (closure_id,))
        log("closure_removed", f"closure:{closure_id}", note)
        db().commit()
        return jsonify(ok=True)

    @app.get("/api/admin/venues")
    @permit("admin")
    def all_venues():
        return jsonify(venues=venues())

    @app.post("/api/admin/venues")
    @permit("admin")
    def configure_venue():
        b = body()
        v = b.get("venue")
        reason = txt(b.get("reason"), "configuration reason", 500)
        if not isinstance(v, dict):
            fail("Provide venue configuration.")
        vid = txt(v.get("id"), "facility ID", 40)
        if not __import__("re").fullmatch("[a-z][a-z0-9-]*", vid):
            fail("Use a lowercase facility ID.")
        db().execute("BEGIN IMMEDIATE")
        old = venue_for(vid)
        version = (old.get("version", 1) + 1) if old else 1
        if type(v.get("capacity")) != int or not 1 <= v["capacity"] <= 1000:
            fail("Capacity must be between 1 and 1000.")
        if type(v.get("rate_cents")) != int or not 0 <= v["rate_cents"] <= 100000:
            fail("Use a valid rate in cents.")
        if (
            type(v.get("insurance_threshold")) != int
            or not 1 <= v["insurance_threshold"] <= 1000
        ):
            fail("Choose a valid insurance threshold.")
        if type(v.get("active")) != bool or type(v.get("insurance_required")) != bool:
            fail("Choose active and insurance settings.")
        if not minute(v.get("opens")) < minute(v.get("closes")):
            fail("Choose valid opening hours.")
        if old:
            for booking in db().execute(
                "SELECT * FROM bookings WHERE venue_id=? AND status IN ('pending','needs_info','approved') AND completed=0",
                (vid,),
            ):
                if (
                    booking["attendance"] > v["capacity"]
                    or minute(booking["setup_time"]) < minute(v["opens"])
                    or minute(booking["cleanup_time"]) > minute(v["closes"])
                ):
                    fail(
                        "Move or cancel affected reservations before reducing capacity or opening hours.",
                        409,
                    )
        for field in ("equipment", "features", "labels"):
            if (
                not isinstance(v.get(field), list)
                or len(v[field]) > 20
                or any(not isinstance(x, str) or len(x) > 100 for x in v[field])
            ):
                fail("Invalid equipment or accessibility list.")
        value = {
            k: v[k]
            for k in (
                "id",
                "capacity",
                "rate_cents",
                "insurance_threshold",
                "active",
                "insurance_required",
                "opens",
                "closes",
                "equipment",
                "features",
                "labels",
            )
        }
        value.update(
            name=txt(v.get("name"), "facility name", 120),
            description=txt(v.get("description"), "description", 1000),
            conditions=txt(v.get("conditions"), "conditions", 2000),
            version=version,
        )
        db().execute(
            "INSERT INTO venue_config(id,content,version) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content,version=excluded.version",
            (vid, json_dump(value), version),
        )
        db().execute(
            "INSERT INTO config_history VALUES(?,?,?,?,?,?)",
            (vid, version, json_dump(value), g.user["id"], reason, now()),
        )
        log("venue_configured", vid, f"Version {version}: {reason}")
        db().commit()
        return jsonify(venue=value)

    @app.get("/api/admin/venues/<venue_id>/versions")
    @permit("admin")
    def configuration_history(venue_id):
        rows = [
            dict(r)
            for r in db().execute(
                "SELECT h.*,u.name AS actor_name FROM config_history h LEFT JOIN users u ON u.id=h.actor_id WHERE venue_id=? ORDER BY version DESC",
                (venue_id,),
            )
        ]
        for row in rows:
            row["content"] = json.loads(row["content"])
        return jsonify(versions=rows)

    @app.get("/api/admin/users")
    @permit("admin")
    def users():
        return jsonify(
            users=[
                public_user(r) for r in db().execute("SELECT * FROM users ORDER BY id")
            ]
        )

    @app.post("/api/admin/users/<int:user_id>/role")
    @permit("admin")
    def set_role(user_id):
        b = body()
        role = b.get("role")
        note = txt(b.get("note"), "access change reason", 500)
        if role not in PERMISSIONS and role != "customer":
            fail("Choose a valid role.")
        if user_id == g.user["id"]:
            fail("You cannot change your own administrative access.")
        if not db().execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
            fail("Account not found.", 404)
        db().execute(
            "UPDATE users SET role=?,staff_role=? WHERE id=?",
            (
                "customer" if role == "customer" else "staff",
                role if role != "customer" else "coordinator",
                user_id,
            ),
        )
        db().execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        log("access_changed", f"user:{user_id}", role + ": " + note)
        db().commit()
        return jsonify(ok=True)

    @app.post("/api/admin/users/<int:user_id>/reset-mfa")
    @permit("admin")
    def reset_mfa(user_id):
        note = txt(body().get("note"), "MFA reset authorisation", 500)
        if user_id == g.user["id"]:
            fail("Another administrator must reset your MFA.", 403)
        if (
            not db()
            .execute("SELECT id FROM users WHERE id=? AND role='staff'", (user_id,))
            .fetchone()
        ):
            fail("Staff account not found.", 404)
        db().execute(
            "UPDATE users SET totp_secret='',totp_counter=-1 WHERE id=?", (user_id,)
        )
        db().execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        db().execute("DELETE FROM mfa_challenges WHERE user_id=?", (user_id,))
        log("mfa_reset", f"user:{user_id}", note)
        db().commit()
        return jsonify(ok=True)

    def payment_for(payment_id):
        p = db().execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not p:
            fail("Payment request not found.", 404)
        row = core().booking_row(p["booking_id"])
        if row["user_id"] != g.user["id"]:
            fail("Only the applicant can use this checkout.", 403)
        return p, row

    @app.get("/api/payments/<payment_id>")
    @core().require_user()
    def payment_info(payment_id):
        p, row = payment_for(payment_id)
        return jsonify(
            payment=dict(p),
            reference=f"DCF-{row['id']:06d}",
            booking_status=row["status"],
            simulated=True,
        )

    @app.post("/api/payments/<payment_id>/pay")
    @core().require_user()
    def pay(payment_id):
        outcome = body().get("outcome", "success")
        if outcome not in ("success", "declined", "timeout"):
            fail("Choose a valid demonstration outcome.")
        db().execute("BEGIN IMMEDIATE")
        p, row = payment_for(payment_id)
        if row["status"] != "approved" or row["completed"]:
            fail("Only an active approved booking can be paid.", 409)
        ledger = (
            db()
            .execute("SELECT * FROM gateway_ledger WHERE payment_id=?", (payment_id,))
            .fetchone()
        )
        if ledger:
            expected = hmac.new(
                app.extensions["audit_key"],
                f"{payment_id}:{ledger['amount']}:{ledger['reference']}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if ledger["amount"] != p["amount"] or not hmac.compare_digest(
                expected, ledger["signature"]
            ):
                fail("Provider record integrity mismatch.", 409)
            db().execute(
                "UPDATE payments SET status='paid',provider_reference=? WHERE id=?",
                (ledger["reference"], payment_id),
            )
            db().execute(
                "UPDATE bookings SET phase='confirmed' WHERE id=?", (row["id"],)
            )
            db().commit()
            return jsonify(
                payment=dict(
                    db()
                    .execute("SELECT * FROM payments WHERE id=?", (payment_id,))
                    .fetchone()
                ),
                reconciled=True,
            )
        if p["status"] == "paid":
            return jsonify(payment=dict(p), reconciled=True)
        if outcome == "declined":
            db().execute(
                "UPDATE payments SET status='declined' WHERE id=?", (payment_id,)
            )
            audit(
                row["id"],
                "payment_declined",
                "Demo provider declined the transaction. No money charged.",
            )
            db().commit()
            return jsonify(
                payment=dict(
                    db()
                    .execute("SELECT * FROM payments WHERE id=?", (payment_id,))
                    .fetchone()
                )
            )
        reference = "DEMO-PAY-" + secrets.token_hex(8).upper()
        signature = hmac.new(
            app.extensions["audit_key"],
            f"{payment_id}:{p['amount']}:{reference}".encode(),
            hashlib.sha256,
        ).hexdigest()
        db().execute(
            "INSERT INTO gateway_ledger VALUES(?,?,?,?,?)",
            (payment_id, p["amount"], reference, signature, now()),
        )
        if outcome == "timeout":
            db().execute(
                "UPDATE payments SET status='processing' WHERE id=?", (payment_id,)
            )
            audit(
                row["id"],
                "payment_processing",
                "Demo provider authorised; response timed out. Retry reconciles the same reference, without another charge.",
            )
        else:
            db().execute(
                "UPDATE payments SET status='paid',provider_reference=? WHERE id=?",
                (reference, payment_id),
            )
            db().execute(
                "UPDATE bookings SET phase='confirmed' WHERE id=?", (row["id"],)
            )
            audit(
                row["id"],
                "payment_received",
                "Demonstration payment confirmed: " + reference,
            )
        db().commit()
        return jsonify(
            payment=dict(
                db()
                .execute("SELECT * FROM payments WHERE id=?", (payment_id,))
                .fetchone()
            )
        )

    @app.post("/api/bookings/<int:booking_id>/refund")
    @core().require_user()
    def refund_request(booking_id):
        reason = txt(body().get("reason"), "refund reason", 1000)
        db().execute("BEGIN IMMEDIATE")
        row = core().booking_row(booking_id)
        if row["user_id"] != g.user["id"]:
            fail("Only the applicant can request a refund.", 403)
        p = (
            db()
            .execute("SELECT * FROM payments WHERE booking_id=?", (booking_id,))
            .fetchone()
        )
        if (
            row["status"] != "cancelled"
            or not p
            or p["status"] != "paid"
            or p["amount"] == 0
        ):
            fail("Refunds apply to cancelled, paid bookings.", 409)
        if (
            db()
            .execute(
                "SELECT id FROM refunds WHERE booking_id=? AND status IN ('requested','approved')",
                (booking_id,),
            )
            .fetchone()
        ):
            fail("A refund is already pending or completed.", 409)
        db().execute(
            "INSERT INTO refunds(booking_id,amount,reason,created_at) VALUES(?,?,?,?)",
            (booking_id, p["amount"], reason, now()),
        )
        audit(booking_id, "refund_requested", reason)
        db().commit()
        return jsonify(ok=True), 201

    @app.post("/api/refunds/<int:refund_id>/decision")
    @permit("finance")
    def refund_decision(refund_id):
        b = body()
        note = txt(b.get("note"), "refund decision reason", 1000)
        if type(b.get("approve")) != bool:
            fail("Choose approve or reject.")
        db().execute("BEGIN IMMEDIATE")
        r = db().execute("SELECT * FROM refunds WHERE id=?", (refund_id,)).fetchone()
        if not r or r["status"] != "requested":
            fail("Refund already decided or unavailable.", 409)
        row = core().booking_row(r["booking_id"])
        if row["user_id"] == g.user["id"]:
            fail("Another finance officer must decide your refund.", 403)
        reference = "DEMO-REF-" + secrets.token_hex(8).upper() if b["approve"] else None
        db().execute(
            "UPDATE refunds SET status=?,reference=?,decision_reason=? WHERE id=?",
            ("approved" if b["approve"] else "rejected", reference, note, refund_id),
        )
        if b["approve"]:
            db().execute(
                "UPDATE payments SET status='refunded' WHERE booking_id=?", (row["id"],)
            )
        audit(
            row["id"], "refund_decided", note + (f" · {reference}" if reference else "")
        )
        db().commit()
        return jsonify(ok=True)

    @app.post("/api/bookings/<int:booking_id>/waiver")
    @permit("finance")
    def waiver(booking_id):
        b = body()
        note = txt(b.get("note"), "waiver reason", 1000)
        amount = b.get("amount_cents")
        db().execute("BEGIN IMMEDIATE")
        row = core().booking_row(booking_id)
        if type(amount) != int or not 0 <= amount <= row["amount_cents"]:
            fail("Enter a waiver no greater than the booking charge.")
        p = (
            db()
            .execute("SELECT * FROM payments WHERE booking_id=?", (booking_id,))
            .fetchone()
        )
        if (
            row["status"] not in ("pending", "approved")
            or row["user_id"] == g.user["id"]
            or (p and p["status"] not in ("requested", "declined"))
        ):
            fail("This charge cannot be waived.", 409)
        revised = row["amount_cents"] - amount
        db().execute(
            "UPDATE bookings SET amount_cents=? WHERE id=?", (revised, booking_id)
        )
        if p:
            db().execute(
                "UPDATE payments SET amount=?,status=?,provider_reference=? WHERE id=?",
                (
                    revised,
                    "paid" if revised == 0 else "requested",
                    "WAIVED" if revised == 0 else None,
                    p["id"],
                ),
            )
        save_version(booking_id)
        audit(booking_id, "waiver_applied", f"AUD {amount/100:.2f}: {note}")
        db().commit()
        return jsonify(ok=True)

    @app.get("/api/finance")
    @permit("finance")
    def finance():
        rows = [
            dict(r)
            for r in db().execute(
                "SELECT p.*,b.event_name,u.name AS customer_name,b.status AS booking_status,g.reference AS ledger_reference,g.amount AS ledger_amount FROM payments p JOIN bookings b ON b.id=p.booking_id JOIN users u ON u.id=b.user_id LEFT JOIN gateway_ledger g ON g.payment_id=p.id ORDER BY p.created_at DESC"
            )
        ]
        return jsonify(
            payments=rows,
            refunds=[
                dict(r) for r in db().execute("SELECT * FROM refunds ORDER BY id DESC")
            ],
            charges=sum(r["amount"] for r in rows if r["status"] == "paid"),
            refund_total=db()
            .execute(
                "SELECT COALESCE(SUM(amount),0) FROM refunds WHERE status='approved'"
            )
            .fetchone()[0],
        )

    @app.post("/api/finance/reconcile")
    @permit("finance")
    def reconcile():
        db().execute("BEGIN IMMEDIATE")
        corrected = 0
        for r in (
            db()
            .execute(
                "SELECT p.*,g.reference,g.amount AS ledger_amount,g.signature FROM payments p JOIN gateway_ledger g ON g.payment_id=p.id"
            )
            .fetchall()
        ):
            expected = hmac.new(
                app.extensions["audit_key"],
                f"{r['id']}:{r['ledger_amount']}:{r['reference']}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if r["amount"] != r["ledger_amount"] or not hmac.compare_digest(
                expected, r["signature"]
            ):
                fail("Provider ledger integrity mismatch.", 409)
            if r["status"] == "processing":
                db().execute(
                    "UPDATE payments SET status='paid',provider_reference=? WHERE id=?",
                    (r["reference"], r["id"]),
                )
                audit(
                    r["booking_id"],
                    "payment_reconciled",
                    "Demo provider reference matched: " + r["reference"],
                )
                corrected += 1
        log("finance_reconciled", "payments", f"{corrected} corrected")
        db().commit()
        return jsonify(corrected=corrected)

    @app.get("/checkout/<payment_id>")
    def checkout(payment_id):
        return core().send_from_directory(core().ROOT / "dist", "checkout.html")

    @app.get("/checkout.js")
    def checkout_js():
        return core().send_from_directory(core().ROOT / "dist", "checkout.js")

    @app.get("/api/bookings/<int:booking_id>/receipt")
    @core().require_user()
    def receipt(booking_id):
        row = core().booking_row(booking_id)
        p = (
            db()
            .execute("SELECT * FROM payments WHERE booking_id=?", (booking_id,))
            .fetchone()
        )
        if not p or p["status"] not in ("paid", "refunded"):
            fail("A receipt is available after payment.", 409)
        return render_template_string(
            """<!doctype html><html lang="en"><meta charset="utf-8"><title>DCF-BAS receipt</title><link rel="stylesheet" href="/styles.css"><main><p class="eyebrow">Coursework · simulated payment receipt</p><h1>DCF-{{ '%06d'|format(row.id) }}</h1><p>Applicant: {{ row.customer_name }}</p><p>Event: {{ row.event_name }}</p><p>Amount: AUD {{ '%.2f'|format(p.amount/100) }}</p><p>Status: {{ p.status }}</p><p>Provider reference: {{ p.provider_reference }}</p><p>No real money was charged. Print or save this page as PDF using your browser.</p><a href="/">Return to bookings</a></main></html>""",
            row=row,
            p=p,
        )

    @app.get("/api/bookings/<int:booking_id>/calendar.ics")
    @core().require_user()
    def export_calendar(booking_id):
        row = core().booking_row(booking_id)
        if row["status"] != "approved":
            fail("Calendar export is available for approved bookings.", 409)

        def esc(s):
            return (
                s.replace("\\", "\\\\")
                .replace(";", "\\;")
                .replace(",", "\\,")
                .replace("\n", "\\n")
                .replace("\r", "")
            )

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//DCF-BAS//Coursework//EN",
            "CALSCALE:GREGORIAN",
        ]
        for r in db().execute(
            "SELECT event_date FROM occurrences WHERE booking_id=? ORDER BY event_date",
            (booking_id,),
        ):
            dt = date.fromisoformat(r[0])
            start = datetime.combine(
                dt,
                datetime.strptime(row["setup_time"], "%H:%M").time(),
                core().ZoneInfo("Australia/Darwin"),
            ).astimezone(core().timezone.utc)
            end = datetime.combine(
                dt,
                datetime.strptime(row["cleanup_time"], "%H:%M").time(),
                core().ZoneInfo("Australia/Darwin"),
            ).astimezone(core().timezone.utc)
            lines += [
                "BEGIN:VEVENT",
                f"UID:dcf-{booking_id}-{r[0]}@demo.example",
                "DTSTAMP:"
                + datetime.now(core().timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                "DTSTART:" + start.strftime("%Y%m%dT%H%M%SZ"),
                "DTEND:" + end.strftime("%Y%m%dT%H%M%SZ"),
                "SUMMARY:" + esc(row["event_name"]),
                "LOCATION:" + esc(venue_for(row["venue_id"])["name"]),
                "END:VEVENT",
            ]
        lines += ["END:VCALENDAR"]
        return send_file(
            io.BytesIO(("\r\n".join(lines) + "\r\n").encode()),
            mimetype="text/calendar",
            as_attachment=True,
            download_name=f"DCF-{booking_id:06d}.ics",
        )

    @app.get("/api/reports")
    @permit("reports")
    def reports():
        return jsonify(report=report_data())

    @app.get("/api/reports/export")
    @permit("reports")
    def export_reports():
        result = report_data()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Facility",
                "Confirmed access hours",
                "Available hours",
                "Utilisation percent",
            ]
        )
        for item in result["utilisation"]:
            name = item["name"]
            if name.startswith(("=", "+", "-", "@")):
                name = "'" + name
            writer.writerow(
                [name, item["booked_hours"], item["available_hours"], item["percent"]]
            )
        writer.writerow([])
        writer.writerow(["Metric", "Value"])
        for k, v in result["metrics"].items():
            writer.writerow([k, v])
        return send_file(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            mimetype="text/csv",
            as_attachment=True,
            download_name="DCF-BAS-report.csv",
        )

    @app.get("/api/audit")
    @permit("audit")
    def audit_events():
        rows = [
            dict(r)
            for r in db().execute(
                "SELECT e.*,u.name AS actor_name FROM event_log e LEFT JOIN users u ON u.id=e.actor_id ORDER BY e.id DESC LIMIT 200"
            )
        ]
        return jsonify(events=rows, integrity=verify_audit())

    @app.get("/api/admin/backup")
    @permit("admin")
    def backup():
        log(
            "backup_exported",
            "system",
            "Encrypted documents and database included; keep archive private.",
        )
        db().commit()
        return send_file(
            io.BytesIO(backup_bytes(app)),
            as_attachment=True,
            mimetype="application/zip",
            download_name="DCF-BAS-private-backup.zip",
        )


def report_data():
    start = request.args.get("from", (core().today() - timedelta(days=30)).isoformat())
    end = request.args.get("to", (core().today() + timedelta(days=30)).isoformat())
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except (ValueError, TypeError):
        fail("Choose valid report dates.")
    if first > last or (last - first).days > 366:
        fail("Choose a report period of at most 367 days.")
    bookings = [
        dict(r)
        for r in db().execute(
            "SELECT DISTINCT b.* FROM bookings b JOIN occurrences o ON o.booking_id=b.id WHERE o.event_date BETWEEN ? AND ?",
            (start, end),
        )
    ]
    utilisation = []
    for v in venues():
        available = (
            (minute(v["closes"]) - minute(v["opens"])) * ((last - first).days + 1)
            - sum(
                minute(r["end_time"]) - minute(r["start_time"])
                for r in db().execute(
                    "SELECT * FROM closures WHERE venue_id=? AND event_date BETWEEN ? AND ?",
                    (v["id"], start, end),
                )
            )
        ) / 60
        hours = sum(
            (minute(r["cleanup_time"]) - minute(r["setup_time"])) / 60
            for r in db().execute(
                "SELECT b.* FROM bookings b JOIN occurrences o ON o.booking_id=b.id WHERE b.venue_id=? AND b.status='approved' AND o.event_date BETWEEN ? AND ?",
                (v["id"], start, end),
            )
        )
        utilisation.append(
            dict(
                name=v["name"],
                booked_hours=round(hours, 2),
                available_hours=round(max(available, 0), 2),
                percent=round(hours / available * 100, 2) if available > 0 else 0,
            )
        )
    ids = [b["id"] for b in bookings]
    placeholder = ",".join("?" for _ in ids) or "NULL"
    feedback = [
        r[0]
        for r in db().execute(
            f"SELECT rating FROM feedback WHERE booking_id IN ({placeholder})", ids
        )
    ]
    cycles = []
    for b in bookings:
        decision = (
            db()
            .execute(
                "SELECT created_at FROM audit WHERE booking_id=? AND action IN ('approved','rejected') ORDER BY id LIMIT 1",
                (b["id"],),
            )
            .fetchone()
        )
        if decision:
            cycles.append(
                max(
                    0,
                    (
                        datetime.fromisoformat(decision[0])
                        - datetime.fromisoformat(b["created_at"])
                    ).total_seconds()
                    / 3600,
                )
            )
    metrics = dict(
        applications=len(bookings),
        online=sum(b["channel"] == "online" for b in bookings),
        assisted=sum(b["channel"] == "assisted" for b in bookings),
        approved=sum(b["status"] == "approved" for b in bookings),
        cancelled=sum(b["status"] == "cancelled" for b in bookings),
        returned=db()
        .execute(
            f"SELECT COUNT(DISTINCT booking_id) FROM audit WHERE action='needs_info' AND booking_id IN ({placeholder})",
            ids,
        )
        .fetchone()[0],
        mean_elapsed_decision_hours=(
            round(sum(cycles) / len(cycles), 2) if cycles else None
        ),
        positive_feedback_percent=(
            round(sum(r >= 4 for r in feedback) / len(feedback) * 100, 2)
            if feedback
            else None
        ),
        feedback_responses=len(feedback),
    )
    return dict(
        from_date=start,
        to_date=end,
        metrics=metrics,
        utilisation=utilisation,
        definitions="Applications are unique records with an occurrence in the period. Utilisation counts approved setup-to-cleanup hours; denominator is opening hours less closures. Cycle time is elapsed submission-to-first-decision, not active staff effort. Planning targets from the report are not measured outcomes.",
    )


def verify_audit():
    previous = "0" * 64
    for r in db().execute("SELECT * FROM event_log ORDER BY id"):
        expected = hmac.new(
            current_app.extensions["audit_key"],
            json_dump(
                [
                    r["actor_id"],
                    r["action"],
                    r["entity"],
                    r["detail"],
                    r["created_at"],
                    previous,
                ]
            ).encode(),
            hashlib.sha256,
        ).hexdigest()
        if r["previous_hash"] != previous or not hmac.compare_digest(
            expected, r["metadata_hash"]
        ):
            return dict(valid=False, failed_event=r["id"])
        previous = r["metadata_hash"]
    return dict(
        valid=True,
        head=previous,
        count=db().execute("SELECT COUNT(*) FROM event_log").fetchone()[0],
    )


def backup_bytes(app):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bookings.sqlite3"
        with (
            sqlite3.connect(app.config["DATABASE"]) as source,
            sqlite3.connect(path) as target,
        ):
            source.backup(target)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(path, "bookings.sqlite3")
            archive.write(app.config["KEY_PATH"], "bookings.key")
        return out.getvalue()


def restore_archive(archive_path, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        if set(archive.namelist()) != {"bookings.sqlite3", "bookings.key"}:
            raise ValueError(
                "Backup archive must contain only the database and encryption key."
            )
        key = archive.read("bookings.key")
        Fernet(key)
        database = archive.read("bookings.sqlite3")
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.sqlite3"
            candidate.write_bytes(database)
            with sqlite3.connect(candidate) as c:
                if (
                    c.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or c.execute("PRAGMA foreign_key_check").fetchone()
                ):
                    raise ValueError("Backup integrity validation failed.")
                for encrypted, digest in c.execute(
                    "SELECT encrypted,digest FROM documents"
                ):
                    if (
                        hashlib.sha256(Fernet(key).decrypt(encrypted)).hexdigest()
                        != digest
                    ):
                        raise ValueError("Document backup integrity validation failed.")
                audit_key = hashlib.sha256(key + b"audit-integrity").digest()
                previous = "0" * 64
                for actor, action, entity, detail, created, prev, digest in c.execute(
                    "SELECT actor_id,action,entity,detail,created_at,previous_hash,metadata_hash FROM event_log ORDER BY id"
                ):
                    expected = hmac.new(
                        audit_key,
                        json_dump(
                            [actor, action, entity, detail, created, previous]
                        ).encode(),
                        hashlib.sha256,
                    ).hexdigest()
                    if prev != previous or not hmac.compare_digest(expected, digest):
                        raise ValueError("Audit backup integrity validation failed.")
                    previous = digest
        if destination.exists() or destination.with_suffix(".key").exists():
            raise ValueError(
                "Restore to a new database/key path; stop the server and keep the old database until verification is complete."
            )
        destination.write_bytes(database)
        destination.with_suffix(".key").write_bytes(key)
        destination.chmod(0o600)
        destination.with_suffix(".key").chmod(0o600)


def seed_demo(app):
    with app.app_context():
        g.app_database = app.config["DATABASE"]
        g.user = None
        for role, name, email in DEMO_ACCOUNTS:
            if (
                not db()
                .execute("SELECT id FROM users WHERE email=?", (email,))
                .fetchone()
            ):
                db().execute(
                    "INSERT INTO users(name,email,password_hash,role,staff_role,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        name,
                        email,
                        generate_password_hash(DEMO_PASSWORD),
                        "customer" if role == "customer" else "staff",
                        role if role != "customer" else "coordinator",
                        now(),
                    ),
                )
        db().commit()
        owner = (
            db()
            .execute("SELECT * FROM users WHERE email='customer@demo.example'")
            .fetchone()
        )
        g.user = owner
        if (
            not db()
            .execute("SELECT id FROM bookings WHERE user_id=?", (owner["id"],))
            .fetchone()
        ):
            for days, vid, name in [
                (7, "nightcliff", "Neighbourhood planning meeting"),
                (14, "malak", "Community garden briefing"),
                (21, "lyons", "Local volunteers catch-up"),
            ]:
                b = dict(
                    venue=venue_for(vid),
                    dates=[(core().today() + timedelta(days=days)).isoformat()],
                    slot="13:00–17:00",
                    event_name=name,
                    event_type="Community meeting",
                    attendance=30,
                    setup_time="12:30",
                    cleanup_time="17:30",
                    alcohol="No",
                    notes="Seeded coursework sample. You can create your own applications too.",
                    amount=5 * venue_for(vid)["rate_cents"],
                    channel="online",
                    required=[],
                    documents=[],
                )
                insert_booking(owner["id"], b)
            db().commit()
