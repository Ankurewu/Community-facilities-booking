"""DCF-BAS booking service. Run with Flask or the documented Gunicorn command."""
import argparse
import getpass
import hashlib
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo
import os

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

ROOT = Path(__file__).resolve().parent
VENUES = [
    dict(id="nightcliff", name="Nightcliff Community Centre", capacity=120,
         features=["stepfree", "parking"], labels=["Step-free entry", "Accessible parking", "Kitchen access"]),
    dict(id="malak", name="Malak Community Centre", capacity=80,
         features=["stepfree", "hearing"], labels=["Step-free entry", "Hearing support", "Meeting layout"]),
    dict(id="lyons", name="Lyons Community Centre", capacity=60,
         features=["stepfree"], labels=["Step-free entry", "Quiet room option", "Small-group layout"]),
]
SLOTS = ["09:00–12:00", "13:00–17:00", "18:00–22:00"]
EVENT_TYPES = ["Community meeting", "Workshop or class", "Private celebration", "Not-for-profit activity"]
HELD = ("pending", "needs_info", "approved")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('customer','staff')),
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id),
 csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bookings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 venue_id TEXT NOT NULL, event_date TEXT NOT NULL, slot TEXT NOT NULL,
 event_name TEXT NOT NULL, event_type TEXT NOT NULL, attendance INTEGER NOT NULL,
 setup_time TEXT NOT NULL, cleanup_time TEXT NOT NULL, alcohol TEXT NOT NULL,
 notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending'
 CHECK(status IN ('pending','needs_info','approved','rejected','cancelled')),
 created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS booking_calendar ON bookings(venue_id,event_date,status);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, booking_id INTEGER NOT NULL REFERENCES bookings(id),
 actor_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
 note TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts (
 user_id INTEGER PRIMARY KEY REFERENCES users(id), content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (address TEXT NOT NULL, created REAL NOT NULL);
"""

def now():
    return datetime.now(timezone.utc).isoformat()

def today():
    return datetime.now(ZoneInfo("Australia/Darwin")).date()

class ApiError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status

def db():
    if "db" not in g:
        g.db = sqlite3.connect(g.app_database, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

def data():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ApiError("Send a JSON object.")
    return value

def text(value, label, limit=200, required=True):
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise ApiError(f"Enter a valid {label} (maximum {limit} characters).")
    return value.strip()

def password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 128:
        raise ApiError("Use a password with 12–128 characters.")
    return value

def identity(value):
    email = text(value, "email address", 254).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ApiError("Enter a valid email address.")
    return email

def require_user(staff=False):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not g.user:
                raise ApiError("Please sign in to continue.", 401)
            if staff and g.user["role"] != "staff":
                raise ApiError("Staff access is required.", 403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def booking_row(booking_id):
    row = db().execute("SELECT b.*,u.name AS customer_name,u.email AS customer_email FROM bookings b JOIN users u ON u.id=b.user_id WHERE b.id=?", (booking_id,)).fetchone()
    if not row or (g.user["role"] != "staff" and row["user_id"] != g.user["id"]):
        raise ApiError("Booking not found.", 404)
    return row

def serialize(row):
    result = dict(row)
    result["reference"] = f"DCF-{row['id']:06d}"
    result["venue_name"] = next(v["name"] for v in VENUES if v["id"] == row["venue_id"])
    result["history"] = [dict(r) for r in db().execute("SELECT a.action,a.note,a.created_at,u.name AS actor_name,u.role AS actor_role FROM audit a JOIN users u ON u.id=a.actor_id WHERE booking_id=? ORDER BY a.id", (row["id"],))]
    return result

def audit(booking_id, action, note):
    db().execute("INSERT INTO audit(booking_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)", (booking_id, g.user["id"], action, note, now()))

def validate_date(value):
    try:
        event_date = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ApiError("Choose a valid date.")
    if not today() < event_date <= today() + timedelta(days=365):
        raise ApiError("Choose a date from tomorrow through the next 365 days.")
    return event_date.isoformat()

def conflicts(venue, event_date, start, end):
    return db().execute("SELECT id FROM bookings WHERE venue_id=? AND event_date=? AND status IN ('pending','needs_info','approved') AND setup_time < ? AND cleanup_time > ? LIMIT 1", (venue, event_date, end, start)).fetchone() is not None

def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(DATABASE=os.environ.get("DATABASE_PATH", str(ROOT / "instance" / "bookings.sqlite3")), COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1", MAX_CONTENT_LENGTH=32*1024)
    if config:
        app.config.update(config)
    if os.environ.get("TRUST_PROXY") == "1":
        # Enable only behind one trusted reverse proxy that overwrites this header.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(app.config["DATABASE"]) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)

    @app.teardown_appcontext
    def close_db(_):
        if "db" in g:
            g.db.close()

    @app.before_request
    def load_session():
        g.app_database = app.config["DATABASE"]
        g.user = None
        g.session = None
        g.new_cookie = None
        if not request.path.startswith("/api/"):
            return
        token = request.cookies.get("dcf_session", "")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        session = db().execute("SELECT * FROM sessions WHERE token_hash=? AND expires>?", (token_hash, datetime.now().timestamp())).fetchone()
        if session:
            g.session = session
            if session["user_id"]:
                g.user = db().execute("SELECT id,name,email,role FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not session or not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
                raise ApiError("Your session expired. Refresh the page and try again.", 403)
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                raise ApiError("Request origin is not allowed.", 403)

    def new_session(user_id=None):
        if g.session:
            db().execute("DELETE FROM sessions WHERE token_hash=?", (g.session["token_hash"],))
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        db().execute("DELETE FROM sessions WHERE expires < ?", (datetime.now().timestamp(),))
        db().execute("INSERT INTO sessions VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, datetime.now().timestamp() + 8*3600))
        db().commit()
        g.new_cookie = token
        return csrf

    @app.after_request
    def headers(response):
        if getattr(g, "new_cookie", None):
            response.set_cookie("dcf_session", g.new_cookie, max_age=8*3600, httponly=True, secure=app.config["COOKIE_SECURE"], samesite="Lax")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ApiError)
    def api_error(error):
        return jsonify(error=error.message), error.status

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="Request is too large."), 413

    @app.get("/")
    def index():
        return send_from_directory(ROOT / "dist", "index.html")

    @app.get("/<path:filename>")
    def assets(filename):
        if filename not in ("app.js", "styles.css"):
            return jsonify(error="Not found."), 404
        return send_from_directory(ROOT / "dist", filename)

    @app.get("/api/session")
    def session_info():
        csrf = g.session["csrf"] if g.session else new_session()
        return jsonify(user=dict(g.user) if g.user else None, csrf=csrf)

    def rate_limit():
        address = request.remote_addr or "unknown"
        stamp = datetime.now().timestamp()
        db().execute("DELETE FROM attempts WHERE created<?", (stamp-900,))
        count = db().execute("SELECT COUNT(*) FROM attempts WHERE address=?", (address,)).fetchone()[0]
        if count >= 20:
            raise ApiError("Too many sign-in attempts. Try again in 15 minutes.", 429)
        db().execute("INSERT INTO attempts VALUES(?,?)", (address, stamp))
        db().commit()

    @app.post("/api/auth/register")
    def register():
        rate_limit()
        body = data()
        name = text(body.get("name"), "name", 100)
        email = identity(body.get("email"))
        hashed = generate_password_hash(password(body.get("password")))
        try:
            cur = db().execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,'customer',?)", (name, email, hashed, now()))
            db().commit()
        except sqlite3.IntegrityError:
            raise ApiError("An account already uses this email. Please sign in.", 409)
        csrf = new_session(cur.lastrowid)
        return jsonify(user=dict(db().execute("SELECT id,name,email,role FROM users WHERE id=?", (cur.lastrowid,)).fetchone()), csrf=csrf), 201

    @app.post("/api/auth/login")
    def login():
        rate_limit()
        body = data()
        email = identity(body.get("email"))
        supplied = body.get("password")
        if not isinstance(supplied, str) or len(supplied) > 128:
            raise ApiError("Invalid email or password.", 401)
        user = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        # Always run password hashing, including unknown accounts.
        valid = check_password_hash(user["password_hash"] if user else app.config["DUMMY_HASH"], supplied)
        if not user or not valid:
            raise ApiError("Invalid email or password.", 401)
        return jsonify(user={k: user[k] for k in ("id", "name", "email", "role")}, csrf=new_session(user["id"]))

    app.config["DUMMY_HASH"] = generate_password_hash(secrets.token_urlsafe(32))

    @app.post("/api/auth/logout")
    def logout():
        return jsonify(csrf=new_session(), user=None)

    @app.post("/api/auth/password")
    @require_user()
    def change_password():
        rate_limit()
        body = data()
        current = body.get("current_password")
        user = db().execute("SELECT password_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
        if not isinstance(current, str) or not check_password_hash(user[0], current):
            raise ApiError("Your current password is incorrect.", 400)
        hashed = generate_password_hash(password(body.get("new_password")))
        db().execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, g.user["id"]))
        db().execute("DELETE FROM sessions WHERE user_id=?", (g.user["id"],))
        return jsonify(csrf=new_session(g.user["id"]))

    @app.get("/api/venues")
    def venues():
        return jsonify(venues=VENUES, today=today().isoformat(), max_date=(today()+timedelta(days=365)).isoformat())

    @app.get("/api/availability")
    def availability():
        venue = request.args.get("venue")
        if venue not in {v["id"] for v in VENUES}:
            raise ApiError("Choose a facility.")
        event_date = validate_date(request.args.get("date"))
        return jsonify(slots=[dict(value=slot, available=not conflicts(venue, event_date, *slot.split("–"))) for slot in SLOTS])

    @app.route("/api/draft", methods=["GET", "PUT", "DELETE"])
    @require_user()
    def draft():
        import json
        if request.method == "GET":
            row = db().execute("SELECT content FROM drafts WHERE user_id=?", (g.user["id"],)).fetchone()
            return jsonify(draft=json.loads(row[0]) if row else None)
        if request.method == "PUT":
            value = data()
            allowed = {"eventName", "eventType", "attendance", "setupTime", "cleanupTime", "venue", "eventDate", "slot", "alcohol", "notes"}
            if set(value)-allowed or any(not isinstance(v, str) or len(v)>2000 for v in value.values()):
                raise ApiError("Invalid draft fields.")
            db().execute("INSERT INTO drafts VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET content=excluded.content", (g.user["id"], json.dumps(value)))
        else:
            db().execute("DELETE FROM drafts WHERE user_id=?", (g.user["id"],))
        db().commit()
        return jsonify(ok=True)

    @app.get("/api/bookings")
    @require_user()
    def bookings():
        query = "SELECT b.*,u.name AS customer_name,u.email AS customer_email FROM bookings b JOIN users u ON u.id=b.user_id"
        args = ()
        if g.user["role"] != "staff":
            query += " WHERE b.user_id=?"
            args = (g.user["id"],)
        rows = db().execute(query + " ORDER BY b.id DESC", args).fetchall()
        return jsonify(bookings=[serialize(row) for row in rows])

    @app.post("/api/bookings")
    @require_user()
    def book():
        body = data()
        venue = next((v for v in VENUES if v["id"] == body.get("venue")), None)
        if not venue:
            raise ApiError("Choose a facility.")
        event_date = validate_date(body.get("eventDate"))
        slot = body.get("slot")
        if slot not in SLOTS:
            raise ApiError("Choose an available time.")
        attendance = body.get("attendance")
        if isinstance(attendance, bool) or not isinstance(attendance, int) or not 1 <= attendance <= venue["capacity"]:
            raise ApiError(f"Attendance must be between 1 and {venue['capacity']}.")
        event_name = text(body.get("eventName"), "event name", 120)
        event_type = body.get("eventType")
        if event_type not in EVENT_TYPES:
            raise ApiError("Choose an event type.")
        start, end = body.get("setupTime"), body.get("cleanupTime")
        if any(not isinstance(t, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in (start, end)):
            raise ApiError("Enter valid setup and cleanup times.")
        slot_start, slot_end = slot.split("–")
        if not "06:00" <= start <= slot_start < slot_end <= end <= "23:59":
            raise ApiError("Setup must start before the event, cleanup must finish after it, and access must be within 6 am–11:59 pm.")
        alcohol = body.get("alcohol")
        if alcohol not in ("Yes", "No") or body.get("declaration") is not True:
            raise ApiError("Confirm the details and declaration.")
        notes = text(body.get("notes", ""), "notes", 2000, required=False)
        # Serialize conflict-check + insert to prevent simultaneous overlapping bookings.
        db().execute("BEGIN IMMEDIATE")
        if conflicts(venue["id"], event_date, start, end):
            raise ApiError("This period has just been reserved. Choose another time or date.", 409)
        cur = db().execute("INSERT INTO bookings(user_id,venue_id,event_date,slot,event_name,event_type,attendance,setup_time,cleanup_time,alcohol,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (g.user["id"], venue["id"], event_date, slot, event_name, event_type, attendance, start, end, alcohol, notes, now()))
        audit(cur.lastrowid, "pending", "Request submitted.")
        db().execute("DELETE FROM drafts WHERE user_id=?", (g.user["id"],))
        db().commit()
        return jsonify(booking=serialize(booking_row(cur.lastrowid))), 201

    @app.post("/api/bookings/<int:booking_id>/cancel")
    @require_user()
    def cancel(booking_id):
        db().execute("BEGIN IMMEDIATE")
        row = booking_row(booking_id)
        if row["user_id"] != g.user["id"]:
            raise ApiError("Only the applicant can cancel this booking.", 403)
        if row["status"] not in HELD or row["event_date"] <= today().isoformat():
            raise ApiError("This booking can no longer be cancelled.", 409)
        db().execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
        audit(booking_id, "cancelled", "Cancelled by applicant.")
        db().commit()
        return jsonify(booking=serialize(booking_row(booking_id)))

    @app.post("/api/bookings/<int:booking_id>/reply")
    @require_user()
    def reply(booking_id):
        message = text(data().get("note"), "reply", 2000)
        db().execute("BEGIN IMMEDIATE")
        row = booking_row(booking_id)
        if row["user_id"] != g.user["id"] or row["status"] != "needs_info":
            raise ApiError("This request is not awaiting your reply.", 409)
        db().execute("UPDATE bookings SET status='pending' WHERE id=?", (booking_id,))
        audit(booking_id, "pending", message)
        db().commit()
        return jsonify(booking=serialize(booking_row(booking_id)))

    @app.post("/api/bookings/<int:booking_id>/decision")
    @require_user(staff=True)
    def decision(booking_id):
        body = data()
        status = body.get("status")
        if status not in ("approved", "rejected", "needs_info"):
            raise ApiError("Choose a valid decision.")
        note = text(body.get("note"), "decision note", 2000)
        db().execute("BEGIN IMMEDIATE")
        row = booking_row(booking_id)
        if row["status"] not in ("pending", "needs_info") or row["event_date"] <= today().isoformat():
            raise ApiError("This request is no longer awaiting a decision.", 409)
        if row["user_id"] == g.user["id"]:
            raise ApiError("A different staff member must review your request.", 403)
        db().execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
        audit(booking_id, status, note)
        db().commit()
        return jsonify(booking=serialize(booking_row(booking_id)))

    return app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "create-staff"])
    parser.add_argument("--email")
    parser.add_argument("--name", default="Facility coordinator")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    app = create_app()
    if args.command == "run":
        app.run(host="127.0.0.1", port=args.port, debug=False)
    else:
        email = identity(args.email)
        supplied = getpass.getpass("Staff password (12+ characters): ")
        if supplied != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
        with sqlite3.connect(app.config["DATABASE"]) as connection:
            if connection.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
                raise SystemExit("Account already exists; no role was changed.")
            connection.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,'staff',?)", (text(args.name, "name", 100), email, generate_password_hash(password(supplied)), now()))
        print("Staff account created.")
