#!/usr/bin/env python3
"""
JV Report Telegram Bot - Automated Photo to PDF Email System
Receives photos via Telegram, creates PDF, and sends email automatically
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from PIL import Image
from pypdf import PdfWriter, PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO
from datetime import datetime
import requests
import time
from flask import Flask, request
import threading

# ==================== CONFIGURATION ====================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YOUR_CHAT_ID = os.getenv("YOUR_CHAT_ID")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "workspaceegd@gmail.com")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

if not TELEGRAM_BOT_TOKEN or not YOUR_CHAT_ID or not SENDER_PASSWORD:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN / YOUR_CHAT_ID / SENDER_PASSWORD in ENV")

RECIPIENTS = ["workspaceegd@gmail.com"] * 7

EMAIL_SUBJECT = "Submission of Joint Visit (JV) Documents – Indus ID: {site_id}"
EMAIL_BODY = """Dear Sir,

Please find attached the Joint Visit (JV) documents for your reference. The site details and photographs are attached as a single PDF.

Indus ID: {site_id}

Best regards,
Satendra Kumar Dubey
Mobile: +91 98931 00138
Email: workspaceegd@gmail.com
"""

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

DOWNLOAD_DIR = "./telegram_photos"
PDF_OUTPUT_DIR = "./pdfs"
ARCHIVE_DIR = "./archive"
LOG_FILE = "./submissions_log.txt"

MAX_IMAGE_SIZE_MB = 2
COMPRESSION_QUALITY = 85
MAX_IMAGE_DIMENSION = 2048

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('bot.log'), logging.StreamHandler()]
)

# ==================== TELEGRAM BOT ====================

class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"

    def send_message(self, chat_id, text):
        return requests.post(f"{self.api_url}/sendMessage", data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).json()

    def send_document(self, chat_id, file_path, caption=""):
        with open(file_path, 'rb') as f:
            return requests.post(f"{self.api_url}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}).json()

    def download_photo(self, file_id, save_path):
        info = requests.get(f"{self.api_url}/getFile?file_id={file_id}").json()
        if not info.get("ok"):
            return False
        path = info["result"]["file_path"]
        content = requests.get(f"https://api.telegram.org/file/bot{self.token}/{path}").content
        with open(save_path, "wb") as f:
            f.write(content)
        return True

# ==================== HELPERS ====================

def compress_image(image_path):
    try:
        img = Image.open(image_path)
        w, h = img.size
        if w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION:
            scale = min(MAX_IMAGE_DIMENSION / w, MAX_IMAGE_DIMENSION / h)
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        img.save(image_path, "JPEG", quality=COMPRESSION_QUALITY, optimize=True)
    except Exception as e:
        logging.error(e)

def create_pdf_from_images(images, out_path):
    writer = PdfWriter()
    for img_path in images:
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=A4)
        can.drawImage(img_path, 20, 20, 550, 800, preserveAspectRatio=True)
        can.save()
        packet.seek(0)
        writer.add_page(PdfReader(packet).pages[0])
    with open(out_path, "wb") as f:
        writer.write(f)

def send_email_with_attachment(subject, body, attachment_path):
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(RECIPIENTS)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with open(attachment_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(attachment_path)}"')
    msg.attach(part)
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())
    server.quit()

def process_site(bot, chat_id, site_id, photos):
    pdf_path = os.path.join(PDF_OUTPUT_DIR, f"{site_id}.pdf")
    for p in photos:
        compress_image(p)
    create_pdf_from_images(photos, pdf_path)
    send_email_with_attachment(EMAIL_SUBJECT.format(site_id=site_id), EMAIL_BODY.format(site_id=site_id), pdf_path)
    bot.send_document(chat_id, pdf_path, f"PDF for Site {site_id}")

# ==================== FLASK APP ====================

app = Flask(__name__)
pending_photos = []

@app.route("/")
def home():
    return "JV Telegram Bot is Live"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    if not update or "message" not in update:
        return "ok"

    bot = TelegramBot(TELEGRAM_BOT_TOKEN)
    message = update["message"]
    chat_id = message["chat"]["id"]

    if str(chat_id) != str(YOUR_CHAT_ID):
        bot.send_message(chat_id, "⛔ Unauthorized")
        return "ok"

    if "photo" in message:
        photo = message["photo"][-1]
        fname = f"photo_{int(time.time())}.jpg"
        path = os.path.join(DOWNLOAD_DIR, fname)
        if bot.download_photo(photo["file_id"], path):
            pending_photos.append(path)
            bot.send_message(chat_id, f"📸 Photo received. Total: {len(pending_photos)}")

    if "text" in message and message["text"].startswith("/siteid"):
        parts = message["text"].split()
        if len(parts) < 2:
            bot.send_message(chat_id, "❌ Usage: /siteid 12345")
        else:
            site_id = parts[1]
            if not pending_photos:
                bot.send_message(chat_id, "❌ No photos received yet!")
            else:
                process_site(bot, chat_id, site_id, pending_photos.copy())
                pending_photos.clear()

    return "ok"

# ==================== START ====================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
