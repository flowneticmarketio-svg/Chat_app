import os
import secrets
import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta

# ----- Config -----
app = Flask(__name__)
CORS(app)

# Admins: list of (username -> password)
ADMINS = {
    "Ryuk": "Thad226010",
    "Führer": "Thad226010",
    "Vanguard": "Thad226010"
}

MAX_MESSAGE_AGE_HOURS = 24

# ----- PostgreSQL Connection -----
# Use provided external DB URL by default (you can override with DATABASE_URL env var)
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://chat_site_oy6p_user:12NqkSqjEkwS0b5vrzCqcY4MbCKG0Ldg@dpg-d2kjkkn5r7bs73cm6dgg-a.oregon-postgres.render.com/chat_site_oy6p"
)


def get_conn():
    # simple connection helper; set sslmode=require if needed by provider
    return psycopg2.connect(DB_URL, sslmode="require")


# ----- DB Setup -----
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # Users: now includes device_id
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        user_id TEXT UNIQUE,
        username TEXT,
        password TEXT,
        device_id TEXT,
        ip TEXT,
        profile_image TEXT,
        about TEXT,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # Friends
    cur.execute("""
    CREATE TABLE IF NOT EXISTS friends (
        id SERIAL PRIMARY KEY,
        user_id TEXT,
        friend_id TEXT
    )
    """)
    # Messages
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        sender_id TEXT,
        receiver_id TEXT,
        message TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # Banned devices (replaces banned_ips)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS banned_devices (
        id SERIAL PRIMARY KEY,
        device_id TEXT UNIQUE,
        reason TEXT,
        banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    cur.close()
    conn.close()


init_db()


# ----- Helpers -----
def generate_user_id():
    return secrets.token_hex(8)


def cleanup_old_messages():
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.utcnow() - timedelta(hours=MAX_MESSAGE_AGE_HOURS)
    cur.execute("DELETE FROM messages WHERE timestamp < %s", (cutoff,))
    conn.commit()
    cur.close()
    conn.close()


def is_device_banned(device_id: str):
    """Return tuple (banned_bool, row_dict_or_None)."""
    if not device_id:
        return False, None
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT device_id, reason, banned_at FROM banned_devices WHERE device_id = %s", (device_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return True, dict(row)
    return False, None


def check_admin_credentials(data: dict):
    """Expect JSON with admin_username and admin_password (or keys 'username','password')."""
    if not data:
        return False
    username = data.get("admin_username") or data.get("username")
    password = data.get("admin_password") or data.get("password")
    if not username or not password:
        return False
    expected = ADMINS.get(username)
    return expected is not None and expected == password


# ----- Routes -----

@app.route("/api/signup", methods=["POST"])
def signup():
    # device_id may be in JSON or header 'X-Device-ID'
    data = request.get_json(force=True, silent=True) or {}
    device_id = data.get("device_id") or request.headers.get("X-Device-ID")
    # Check device ban first
    banned, info = is_device_banned(device_id)
    if banned:
        return jsonify({
            "error": "Device banned",
            "reason": info.get("reason"),
            "banned_at": info.get("banned_at")
        }), 403

    username = data.get("username")
    password = data.get("password")
    profile_image = data.get("profile_image", "")
    about = data.get("about", "")
    ip = request.remote_addr

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    user_id = generate_user_id()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, username, password, device_id, ip, profile_image, about) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (user_id, username, password, device_id, ip, profile_image, about)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True, "user_id": user_id})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True, silent=True) or {}
    device_id = data.get("device_id") or request.headers.get("X-Device-ID")

    banned, info = is_device_banned(device_id)
    if banned:
        return jsonify({
            "error": "Device banned",
            "reason": info.get("reason"),
            "banned_at": info.get("banned_at")
        }), 403

    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    conn = get_conn()
    cur = conn.cursor()
    # If user logs in, record device_id for that user (so a user account can be associated with the device)
    cur.execute("SELECT user_id, profile_image, about FROM users WHERE username=%s AND password=%s", (username, password))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({"error": "Invalid credentials"}), 401

    user_id = row[0]
    profile_image = row[1]
    about = row[2]
    # Update device_id for this user if provided
    if device_id:
        cur.execute("UPDATE users SET device_id=%s WHERE user_id=%s", (device_id, user_id))
        conn.commit()

    cur.close()
    conn.close()
    return jsonify({"success": True, "user_id": user_id, "profile_image": profile_image, "about": about})


@app.route("/api/update_profile", methods=["POST"])
def update_profile():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    profile_image = data.get("profile_image")
    about = data.get("about")
    if not user_id:
        return jsonify({"error": "User ID required"}), 400
    conn = get_conn()
    cur = conn.cursor()
    if profile_image is not None:
        cur.execute("UPDATE users SET profile_image=%s WHERE user_id=%s", (profile_image, user_id))
    if about is not None:
        cur.execute("UPDATE users SET about=%s WHERE user_id=%s", (about, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/add_friend", methods=["POST"])
def add_friend():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    friend_id = data.get("friend_id")
    if not user_id or not friend_id:
        return jsonify({"error": "Missing IDs"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM friends WHERE user_id=%s AND friend_id=%s", (user_id, friend_id))
    if not cur.fetchone():
        cur.execute("INSERT INTO friends (user_id, friend_id) VALUES (%s, %s)", (user_id, friend_id))
        cur.execute("INSERT INTO friends (user_id, friend_id) VALUES (%s, %s)", (friend_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/send_message", methods=["POST"])
def send_message():
    cleanup_old_messages()
    data = request.get_json(force=True, silent=True) or {}
    sender_id = data.get("sender_id")
    receiver_id = data.get("receiver_id")
    message = data.get("message")
    if not sender_id or not receiver_id or not message:
        return jsonify({"error": "Missing data"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM friends WHERE user_id=%s AND friend_id=%s", (sender_id, receiver_id))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"error": "Not friends"}), 403
    cur.execute("INSERT INTO messages (sender_id, receiver_id, message) VALUES (%s, %s, %s)", (sender_id, receiver_id, message))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/messages", methods=["POST"])
def get_messages():
    cleanup_old_messages()
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    friend_id = data.get("friend_id")
    if not user_id or not friend_id:
        return jsonify({"error": "Missing data"}), 400
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cutoff = datetime.utcnow() - timedelta(hours=MAX_MESSAGE_AGE_HOURS)
    cur.execute("""
        SELECT m.sender_id, u.username AS sender_username, m.receiver_id, m.message, m.timestamp
        FROM messages m
        JOIN users u ON m.sender_id = u.user_id
        WHERE ((m.sender_id=%s AND m.receiver_id=%s) OR (m.sender_id=%s AND m.receiver_id=%s))
          AND m.timestamp >= %s
        ORDER BY m.timestamp ASC
    """, (user_id, friend_id, friend_id, user_id, cutoff))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    messages = [{
        "sender_id": r["sender_id"],
        "sender_username": r["sender_username"],
        "receiver_id": r["receiver_id"],
        "message": r["message"],
        "timestamp": r["timestamp"].isoformat() if isinstance(r["timestamp"], datetime) else r["timestamp"]
    } for r in rows]
    return jsonify(messages)


# ----- Admin -----

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(force=True, silent=True) or {}
    if check_admin_credentials(data):
        return jsonify({"success": True})
    return jsonify({"error": "Invalid credentials"}), 401


@app.route("/api/admin/users", methods=["GET"])
def admin_users():
    # Check admin credentials via query params or headers (not secure for production; use tokens)
    data = request.get_json(force=True, silent=True) or {}
    if not check_admin_credentials(data):
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT user_id, username, device_id, ip, profile_image, about, created FROM users")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    users = [dict(r) for r in rows]
    # format created timestamps as ISO strings
    for u in users:
        if isinstance(u.get("created"), datetime):
            u["created"] = u["created"].isoformat()
    return jsonify(users)


@app.route("/api/admin/all_messages", methods=["GET"])
def admin_all_messages():
    data = request.get_json(force=True, silent=True) or {}
    if not check_admin_credentials(data):
        return jsonify({"error": "Unauthorized"}), 401
    cleanup_old_messages()
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("""
        SELECT m.sender_id, u.username AS sender_username, m.receiver_id, m.message, m.timestamp
        FROM messages m
        JOIN users u ON m.sender_id = u.user_id
        ORDER BY m.timestamp ASC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    messages = [dict(r) for r in rows]
    for m in messages:
        if isinstance(m.get("timestamp"), datetime):
            m["timestamp"] = m["timestamp"].isoformat()
    return jsonify(messages)


@app.route("/api/admin/ban_device", methods=["POST"])
def admin_ban_device():
    data = request.get_json(force=True, silent=True) or {}
    if not check_admin_credentials(data):
        return jsonify({"error": "Unauthorized"}), 401
    device_id = data.get("device_id")
    reason = data.get("reason", "")
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO banned_devices (device_id, reason) VALUES (%s, %s) ON CONFLICT (device_id) DO UPDATE SET reason = EXCLUDED.reason, banned_at = CURRENT_TIMESTAMP",
        (device_id, reason)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/admin/unban_device", methods=["POST"])
def admin_unban_device():
    data = request.get_json(force=True, silent=True) or {}
    if not check_admin_credentials(data):
        return jsonify({"error": "Unauthorized"}), 401
    device_id = data.get("device_id")
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM banned_devices WHERE device_id = %s", (device_id,))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if deleted:
        return jsonify({"success": True, "unbanned_device": device_id})
    else:
        return jsonify({"error": "Device not found in ban list"}), 404


@app.route("/api/admin/banned_devices", methods=["GET"])
def admin_banned_devices():
    data = request.get_json(force=True, silent=True) or {}
    if not check_admin_credentials(data):
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT device_id, reason, banned_at FROM banned_devices ORDER BY banned_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    banned = [dict(r) for r in rows]
    for b in banned:
        if isinstance(b.get("banned_at"), datetime):
            b["banned_at"] = b["banned_at"].isoformat()
    return jsonify(banned)


# ----- Run -----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Use 0.0.0.0 so it is reachable by other hosts (for container / Render deployment)
    app.run(host="0.0.0.0", port=port, debug=False)
