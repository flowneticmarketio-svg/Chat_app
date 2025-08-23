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

# Admins
ADMINS = [
    {"username": "Ryuk", "password": "Thad226010"},
    {"username": "Führer", "password": "Thad226010"},
    {"username": "Vanguard", "password": "Thad226010"}
]

MAX_MESSAGE_AGE_HOURS = 24

# ----- PostgreSQL Connection -----
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://chat_site_oy6p_user:12NqkSqjEkwS0b5vrzCqcY4MbCKG0Ldg@dpg-d2kjkkn5r7bs73cm6dgg-a.oregon-postgres.render.com/chat_site_oy6p"
)

def get_conn():
    return psycopg2.connect(DB_URL, sslmode="require")

# ----- DB Setup -----
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # Users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            user_id TEXT UNIQUE,
            username TEXT,
            password TEXT,
            device_id TEXT,
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
    # Banned devices
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
    return secrets.token_hex(4)

def cleanup_old_messages():
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=MAX_MESSAGE_AGE_HOURS)
    cur.execute("DELETE FROM messages WHERE timestamp < %s", (cutoff,))
    conn.commit()
    cur.close()
    conn.close()

def is_banned(device_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM banned_devices WHERE device_id=%s", (device_id,))
    banned = cur.fetchone() is not None
    cur.close()
    conn.close()
    return banned

# ----- Routes -----
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    device_id = data.get("device_id")
    profile_image = data.get("profile_image", "")
    about = data.get("about", "")
    if not username or not password or not device_id:
        return jsonify({"error": "Username, password, and device ID required"}), 400
    if is_banned(device_id):
        return jsonify({"error": "This device is banned"}), 403
    user_id = generate_user_id()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, username, password, device_id, profile_image, about) VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, username, password, device_id, profile_image, about)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True, "user_id": user_id})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    device_id = data.get("device_id")
    if not username or not password or not device_id:
        return jsonify({"error": "Missing username, password, or device ID"}), 400
    if is_banned(device_id):
        return jsonify({"error": "This device is banned"}), 403
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, profile_image, about FROM users WHERE username=%s AND password=%s AND device_id=%s",
        (username, password, device_id)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return jsonify({"success": True, "user_id": row[0], "profile_image": row[1], "about": row[2]})
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json()
    for admin in ADMINS:
        if data.get("username") == admin["username"] and data.get("password") == admin["password"]:
            return jsonify({"success": True})
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/admin/ban_device", methods=["POST"])
def admin_ban_device():
    data = request.get_json()
    device_id = data.get("device_id")
    reason = data.get("reason", "")
    if not device_id:
        return jsonify({"error": "Device ID required"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO banned_devices (device_id, reason) VALUES (%s, %s) ON CONFLICT (device_id) DO NOTHING",
        (device_id, reason)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/admin/unban_device", methods=["POST"])
def admin_unban_device():
    data = request.get_json()
    device_id = data.get("device_id")
    if not device_id:
        return jsonify({"error": "Device ID required"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM banned_devices WHERE device_id=%s", (device_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

# ----- Run -----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
