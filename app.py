import os
import sqlite3
import secrets
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta

# ----- Config -----
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "chatapp.db")

app = Flask(__name__)
CORS(app)

ADMIN_USER = "Ryuk"
ADMIN_PASS = "Thad226010"
MAX_MESSAGE_AGE_HOURS = 24

# ----- DB Setup -----
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Users with login info, profile image, about
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS friends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            friend_id TEXT
        )
    """)
    # Messages
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT,
            receiver_id TEXT,
            message TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Banned IPs
    c.execute("""
        CREATE TABLE IF NOT EXISTS banned_ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT UNIQUE,
            reason TEXT,
            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ----- Helpers -----
def generate_user_id():
    return secrets.token_hex(4)  # 8-char hex

def cleanup_old_messages():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=MAX_MESSAGE_AGE_HOURS)
    c.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()

def is_banned(ip):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM banned_ips WHERE ip=?", (ip,))
    banned = c.fetchone() is not None
    conn.close()
    return banned

# ----- Routes -----

# Signup
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, username, password, ip, profile_image, about) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, username, password, ip, profile_image, about))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "user_id": user_id})

# Login
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, profile_image, about FROM users WHERE username=? AND password=?", (username, password))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({"success": True, "user_id": row[0], "profile_image": row[1], "about": row[2]})
    return jsonify({"error": "Invalid credentials"}), 401

# Update profile image or about
@app.route("/api/update_profile", methods=["POST"])
def update_profile():
    data = request.get_json()
    user_id = data.get("user_id")
    profile_image = data.get("profile_image")
    about = data.get("about")
    if not user_id:
        return jsonify({"error": "User ID required"}), 400
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if profile_image:
        c.execute("UPDATE users SET profile_image=? WHERE user_id=?", (profile_image, user_id))
    if about:
        c.execute("UPDATE users SET about=? WHERE user_id=?", (about, user_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# Add friend
@app.route("/api/add_friend", methods=["POST"])
def add_friend():
    data = request.get_json()
    user_id = data.get("user_id")
    friend_id = data.get("friend_id")
    if not user_id or not friend_id:
        return jsonify({"error": "Missing IDs"}), 400
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Check if already friends
    c.execute("SELECT id FROM friends WHERE user_id=? AND friend_id=?", (user_id, friend_id))
    if not c.fetchone():
        c.execute("INSERT INTO friends (user_id, friend_id) VALUES (?, ?)", (user_id, friend_id))
        c.execute("INSERT INTO friends (user_id, friend_id) VALUES (?, ?)", (friend_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# Send message
@app.route("/api/send_message", methods=["POST"])
def send_message():
    cleanup_old_messages()
    data = request.get_json()
    sender_id = data.get("sender_id")
    receiver_id = data.get("receiver_id")
    message = data.get("message")
    if not sender_id or not receiver_id or not message:
        return jsonify({"error": "Missing data"}), 400
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Check if receiver is friend
    c.execute("SELECT id FROM friends WHERE user_id=? AND friend_id=?", (sender_id, receiver_id))
    if not c.fetchone():
        return jsonify({"error": "Not friends"}), 403
    c.execute("INSERT INTO messages (sender_id, receiver_id, message) VALUES (?, ?, ?)", (sender_id, receiver_id, message))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# Get messages between two users (for today)
@app.route("/api/messages", methods=["POST"])
def get_messages():
    cleanup_old_messages()
    data = request.get_json()
    user_id = data.get("user_id")
    friend_id = data.get("friend_id")
    if not user_id or not friend_id:
        return jsonify({"error": "Missing data"}), 400
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=MAX_MESSAGE_AGE_HOURS)
    c.execute("""
        SELECT sender_id, receiver_id, message, timestamp FROM messages
        WHERE ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))
        AND timestamp >= ?
        ORDER BY timestamp ASC
    """, (user_id, friend_id, friend_id, user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    messages = [{"sender": r[0], "receiver": r[1], "message": r[2], "timestamp": r[3]} for r in rows]
    return jsonify(messages)

# ----- Admin Routes -----
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    if username == ADMIN_USER and password == ADMIN_PASS:
        return jsonify({"success": True})
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/admin/users", methods=["GET"])
def admin_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, ip, profile_image, about, created FROM users")
    rows = c.fetchall()
    conn.close()
    users = [{"user_id": r[0], "username": r[1], "ip": r[2], "profile_image": r[3], "about": r[4], "created": r[5]} for r in rows]
    return jsonify(users)

@app.route("/api/admin/all_messages", methods=["GET"])
def admin_all_messages():
    cleanup_old_messages()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT sender_id, receiver_id, message, timestamp FROM messages ORDER BY timestamp ASC")
    rows = c.fetchall()
    conn.close()
    messages = [{"sender": r[0], "receiver": r[1], "message": r[2], "timestamp": r[3]} for r in rows]
    return jsonify(messages)

@app.route("/api/admin/ban_ip", methods=["POST"])
def admin_ban_ip():
    data = request.get_json()
    ip = data.get("ip")
    reason = data.get("reason", "")
    if not ip:
        return jsonify({"error": "IP required"}), 400
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO banned_ips (ip, reason) VALUES (?, ?)", (ip, reason))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ----- Run -----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
