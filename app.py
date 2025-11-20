import os
import sys
import threading
import webbrowser
import json
from flask import Flask, render_template, request, jsonify
import yt_dlp
import google.generativeai as genai
import re
import uuid
import hashlib
import requests
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURATION ---
CONFIG_FILE = "config.json"
API_KEYS_FILE = "api_keys.txt"
LINKS_FILE = "links.txt"
FFMPEG_FOLDER = os.path.join(os.getcwd(), "ffmpeg")

# ⚠️ IMPORTANT: PASTE YOUR GITHUB RAW LINK HERE
USERS_DB_URL = (
    "https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/users.txt"
)

# Admin Profile
ADMIN_INFO = {
    "name": "Shamim Vaiya",
    "bio": "Exploiting Reality, One Line of Code at a Time.",
    "socials": {
        "facebook": "https://www.facebook.com/AnonymousCyberTeamOfficial",
        "whatsapp": "https://wa.me/+8801540580575",
        "telegram": "https://t.me/shamim_vaiya",
        "github": "https://github.com/Anonymous-Cyber-Team",
    },
}

# Global Status
CURRENT_STATUS = "System Ready..."
AI_STATUS = False
ACTIVE_MODEL = "Unknown"

# --- HELPERS ---


def load_config():
    default_conf = {"save_path": os.path.join(os.getcwd(), "Downloads")}
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_conf, f)
        return default_conf
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)


def load_api_keys():
    if not os.path.exists(API_KEYS_FILE):
        return []
    with open(API_KEYS_FILE, "r") as f:
        return [line.strip() for line in f if line.strip()]


def check_ai():
    global AI_STATUS, ACTIVE_MODEL
    keys = load_api_keys()
    if not keys:
        AI_STATUS = False
        return

    models = ["gemma-3-27b-it", "gemini-1.5-flash"]
    for key in keys:
        for model_name in models:
            try:
                genai.configure(api_key=key)
                model = genai.GenerativeModel(model_name)
                model.generate_content("Hi", generation_config={"max_output_tokens": 5})
                AI_STATUS = True
                ACTIVE_MODEL = model_name
                return
            except:
                continue
    AI_STATUS = False


def get_ai_filename(title):
    if not AI_STATUS:
        return None
    keys = load_api_keys()
    prompt = (
        f"Rename for Windows filename (Short, No Emojis, No Special Chars): '{title}'"
    )

    for key in keys:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(ACTIVE_MODEL)
            res = model.generate_content(prompt)
            if res.text:
                return re.sub(r'[<>:"/\\|?*]', "", res.text.strip())
        except:
            continue
    return None


# --- SECURITY ROUTES (ONLINE CHECK) ---


@app.route("/get_device_id", methods=["GET"])
def get_device_id():
    device_id = str(uuid.getnode())
    return jsonify({"device_id": device_id})


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data["username"]
    password = data["password"]
    device_id = str(uuid.getnode())

    try:
        # Fetch Database from GitHub (Online)
        response = requests.get(USERS_DB_URL)
        if response.status_code != 200:
            return jsonify(
                {"status": "error", "message": "Server Offline. Contact Admin."}
            )

        user_db = response.text.strip().split("\n")

        input_hash = hashlib.sha256(password.encode()).hexdigest()

        for line in user_db:
            parts = line.strip().split(",")
            if len(parts) < 4:
                continue

            db_device, db_user, db_pass, db_expiry = parts

            if db_user == username and db_pass == input_hash:
                # Device Lock Check
                if db_device != device_id:
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Access Denied! Device Mismatch.",
                        }
                    )

                # Expiry Check (Date & Time)
                if db_expiry != "LIFETIME":
                    try:
                        # Format: YYYY-MM-DD HH:MM:SS
                        expiry_date = datetime.strptime(db_expiry, "%Y-%m-%d %H:%M:%S")
                        if datetime.now() > expiry_date:
                            return jsonify(
                                {
                                    "status": "error",
                                    "message": "Subscription Expired! Contact Admin.",
                                }
                            )
                    except ValueError:
                        # Fallback for date only
                        try:
                            expiry_date = datetime.strptime(db_expiry, "%Y-%m-%d")
                            if datetime.now() > expiry_date:
                                return jsonify(
                                    {
                                        "status": "error",
                                        "message": "Subscription Expired!",
                                    }
                                )
                        except:
                            pass

                return jsonify({"status": "success", "expiry": db_expiry})

        return jsonify({"status": "error", "message": "Invalid Username or Password!"})

    except Exception as e:
        return jsonify({"status": "error", "message": f"Connection Error: {str(e)}"})


# --- APP ROUTES ---


@app.route("/")
def home():
    check_ai()
    conf = load_config()
    return render_template(
        "index.html",
        ai_status=AI_STATUS,
        model=ACTIVE_MODEL,
        path=conf["save_path"],
        admin=ADMIN_INFO,
    )


@app.route("/save_api", methods=["POST"])
def save_api():
    data = request.json
    with open(API_KEYS_FILE, "w") as f:
        f.write(data["keys"])
    check_ai()
    return jsonify({"status": "success", "ai_active": AI_STATUS})


@app.route("/save_links", methods=["POST"])
def save_links():
    data = request.json
    with open(LINKS_FILE, "w") as f:
        f.write(data["links"])
    return jsonify({"status": "success"})


@app.route("/save_path", methods=["POST"])
def save_path():
    data = request.json
    conf = load_config()
    conf["save_path"] = data["path"]
    save_config(conf)
    return jsonify({"status": "success"})


@app.route("/start_download", methods=["POST"])
def start_download():
    data = request.json
    mode = data["mode"]
    quality = data["quality"]
    manual_fmt = data.get("manual_fmt", None)

    threading.Thread(
        target=run_download_process, args=(mode, quality, manual_fmt)
    ).start()
    return jsonify({"status": "started"})


@app.route("/get_status")
def get_status():
    return jsonify({"log": CURRENT_STATUS})


# --- DOWNLOAD ENGINE ---


def run_download_process(mode, quality_code, manual_fmt=None):
    global CURRENT_STATUS
    conf = load_config()

    if not os.path.exists(LINKS_FILE):
        CURRENT_STATUS = "Error: No Links Found!"
        return

    with open(LINKS_FILE, "r") as f:
        urls = [line.strip() for line in f if line.strip()]

    if not urls:
        CURRENT_STATUS = "Error: Link list is empty!"
        return

    CURRENT_STATUS = f"Starting {len(urls)} downloads..."

    # Quality Map
    q_map = {
        # Video
        "best": "bestvideo+bestaudio/best",
        "8k": "bestvideo[height<=4320]+bestaudio/best",
        "4k": "bestvideo[height<=2160]+bestaudio/best",
        "2k": "bestvideo[height<=1440]+bestaudio/best",
        "1080p": "bestvideo[height<=1080]+bestaudio/best",
        "720p": "bestvideo[height<=720]+bestaudio/best",
        "480p": "bestvideo[height<=480]+bestaudio/best",
        "360p": "bestvideo[height<=360]+bestaudio/best",
        "lowest": "worstvideo+bestaudio/worst",
        # Audio
        "best_audio": "bestaudio/best",
        "320k": "bestaudio",
        "256k": "bestaudio",
        "192k": "bestaudio",
        "128k": "bestaudio[abr<=128]",
        "64k": "bestaudio[abr<=64]",
    }

    if quality_code == "manual" and manual_fmt:
        fmt = manual_fmt
    else:
        fmt = q_map.get(quality_code, "bestvideo+bestaudio/best")

    if mode == "audio":
        if "bestvideo" in fmt:
            fmt = "bestaudio/best"

    opts = {
        "format": fmt,
        "ffmpeg_location": FFMPEG_FOLDER,
        "nocheckcertificate": True,
        "quiet": True,
        "restrictfilenames": True,
    }

    if mode == "audio":
        q_val = "192"
        if quality_code == "320k":
            q_val = "320"
        if quality_code == "128k":
            q_val = "128"
        if quality_code == "64k":
            q_val = "64"

        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": q_val,
            }
        ]

    for i, url in enumerate(urls, 1):
        try:
            CURRENT_STATUS = f"Processing ({i}/{len(urls)}): Getting Info..."
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "Video")

                CURRENT_STATUS = f"Processing ({i}/{len(urls)}): AI Renaming..."
                new_name = get_ai_filename(title)
                if not new_name:
                    new_name = re.sub(r'[<>:"/\\|?*]', "", title)
                    new_name = new_name.encode("ascii", "ignore").decode("ascii")
                    new_name = new_name[:50].strip()

                final_name = f"{new_name} [{i}]"

                CURRENT_STATUS = f"Downloading: {final_name}..."
                opts["outtmpl"] = os.path.join(
                    conf["save_path"], f"{final_name}.%(ext)s"
                )

                with yt_dlp.YoutubeDL(opts) as ydl_run:
                    ydl_run.download([url])

        except Exception as e:
            CURRENT_STATUS = f"Error on {i}: {str(e)}"
            continue

    CURRENT_STATUS = "ALL TASKS COMPLETED SUCCESSFULLY!"


if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(port=5000, debug=False)
