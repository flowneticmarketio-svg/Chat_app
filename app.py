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

ADMIN_USER = "Ryuk"
ADMIN_PASS = "Thad226010"
MAX_MESSAGE_AGE_HOURS = 24

# ----- PostgreSQL Connection -----
DB_URL = os.getenv("DATABASE_URL", "postgresql://chat_site_4fon_user:kfBshweJq9ofZB9sN8YyadA2bL4gYU8X@dpg-d2kisk75r7bs73clfla0-a.oregon-postgres.render.com/chat_site_4fon")

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
    # Banned IPs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS banned_ips (
            id SERIAL PRIMARY KEY,
            ip TEXT UNIQUE,
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

def is_banned(ip):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM banned_ips WHERE ip=%s", (ip,))
    banned = cur.fetchone() is not None
    cur.close()
    conn.close()
    return banned

# ----- Routes -----

@app.route("/api/signup", methods=["POST"])
def signup():
    ip = request.remote_addr
    if is_banned(ip):
        return jsonify({"error": "You are banned"}), 403
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    profile_image = data.get("profile_image", "")
    about = data.get("about", "")
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    user_id = generate_user_id()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username, password, ip, profile_image, about) VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, username, password, ip, profile_image, about))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True, "user_id": user_id})

@app.route("/api/login", methods=["POST"])
def login():
    ip = request.remote_addr
    if is_banned(ip):
        return jsonify({"error": "You are banned"}), 403
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, profile_image, about FROM users WHERE username=%s AND password=%s", (username, password))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return jsonify({"success": True, "user_id": row[0], "profile_image": row[1], "about": row[2]})
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/update_profile", methods=["POST"])
def update_profile():
    data = request.get_json()
    user_id = data.get("user_id")
    profile_image = data.get("profile_image")
    about = data.get("about")
    if not user_id:
        return jsonify({"error": "User ID required"}), 400
    conn = get_conn()
    cur = conn.cursor()
    if profile_image:
        cur.execute("UPDATE users SET profile_image=%s WHERE user_id=%s", (profile_image, user_id))
    if about:
        cur.execute("UPDATE users SET about=%s WHERE user_id=%s", (about, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/add_friend", methods=["POST"])
def add_friend():
    data = request.get_json()
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
    data = request.get_json()
    sender_id = data.get("sender_id")
    receiver_id = data.get("receiver_id")
    message = data.get("message")
    if not sender_id or not receiver_id or not message:
        return jsonify({"error": "Missing data"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM friends WHERE user_id=%s AND friend_id=%s", (sender_id, receiver_id))
    if not cur.fetchone():
        return jsonify({"error": "Not friends"}), 403
    cur.execute("INSERT INTO messages (sender_id, receiver_id, message) VALUES (%s, %s, %s)", (sender_id, receiver_id, message))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/messages", methods=["POST"])
def get_messages():
    cleanup_old_messages()
    data = request.get_json()
    user_id = data.get("user_id")
    friend_id = data.get("friend_id")
    if not user_id or not friend_id:
        return jsonify({"error": "Missing data"}), 400
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cutoff = datetime.now() - timedelta(hours=MAX_MESSAGE_AGE_HOURS)
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
    messages = [{"sender_id": r["sender_id"], "sender_username": r["sender_username"], "receiver_id": r["receiver_id"], "message": r["message"], "timestamp": r["timestamp"]} for r in rows]
    return jsonify(messages)

# ----- Admin -----
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json()
    if data.get("username") == ADMIN_USER and data.get("password") == ADMIN_PASS:
        return jsonify({"success": True})
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/admin/users", methods=["GET"])
def admin_users():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT user_id, username, ip, profile_image, about, created FROM users")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    users = [dict(r) for r in rows]
    return jsonify(users)

@app.route("/api/admin/all_messages", methods=["GET"])
def admin_all_messages():
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
    return jsonify(messages)

@app.route("/api/admin/ban_ip", methods=["POST"])
def admin_ban_ip():
    data = request.get_json()
    ip = data.get("ip")
    reason = data.get("reason", "")
    if not ip:
        return jsonify({"error": "IP required"}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO banned_ips (ip, reason) VALUES (%s, %s) ON CONFLICT (ip) DO NOTHING", (ip, reason))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"success": True})

# ----- Run -----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
