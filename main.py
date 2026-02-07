#!/usr/bin/env python3
import os
import time
import logging
import smtplib
from flask import Flask, request
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

# ==================== CONFIG (ENV ONLY) ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUR_CHAT_ID = os.getenv("YOUR_CHAT_ID")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

if not TELEGRAM_BOT_TOKEN or not YOUR_CHAT_ID:
    raise ValueError("Missing ENV variables")

SMTP_SERVER = "smtp.mail.yahoo.com"
SMTP_PORT = 587

RECIPIENTS = ["workspaceegd@gmail.com"]

EMAIL_SUBJECT = "Submission of Joint Visit (JV) Documents – Indus ID: {site_id}"
EMAIL_BODY = """Dear Sir,

Please find attached the Joint Visit (JV) documents.

Indus ID: {site_id}

Best regards,
Satendra Kumar Dubey
Mobile: +91 98931 00138
"""

DOWNLOAD_DIR = "./telegram_photos"
PDF_OUTPUT_DIR = "./pdfs"
ARCHIVE_DIR = "./archive"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)

# ==================== TELEGRAM BOT ====================
class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"

    def send_message(self, chat_id, text):
        return requests.post(f"{self.api_url}/sendMessage", data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).json()

    def download_photo(self, file_id, save_path):
        file_info = requests.get(f"{self.api_url}/getFile?file_id={file_id}").json()
        file_path = file_info["result"]["file_path"]
        content = requests.get(f"https://api.telegram.org/file/bot{self.token}/{file_path}").content
        with open(save_path, "wb") as f:
            f.write(content)

bot = TelegramBot(TELEGRAM_BOT_TOKEN)
pending_photos = []

# ==================== PDF ====================
def create_pdf(images, output_path):
    writer = PdfWriter()
    for img_path in images:
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=A4)
        can.drawImage(img_path, 20, 20, 550, 800, preserveAspectRatio=True)
        can.save()
        packet.seek(0)
        writer.add_page(PdfReader(packet).pages[0])

    with open(output_path, "wb") as f:
        writer.write(f)

# ==================== EMAIL ====================
def send_email(subject, body, attachment):
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(RECIPIENTS)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with open(attachment, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(attachment)}"')
    msg.attach(part)

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(SENDER_EMAIL, SENDER_PASSWORD)
    server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())
    server.quit()

# ==================== FLASK APP ====================
app = Flask(__name__)

@app.route("/")
def home():
    return "JV Bot is Live"

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    if not update or "message" not in update:
        return "ok"

    message = update["message"]
    chat_id = message["chat"]["id"]

    if str(chat_id) != str(YOUR_CHAT_ID):
        bot.send_message(chat_id, "⛔ Unauthorized")
        return "ok"

    if "photo" in message:
        photo = message["photo"][-1]
        filename = f"photo_{int(time.time())}.jpg"
        path = os.path.join(DOWNLOAD_DIR, filename)
        bot.download_photo(photo["file_id"], path)
        pending_photos.append(path)
        bot.send_message(chat_id, f"📸 Photo received. Total: {len(pending_photos)}")

    if "text" in message and message["text"].startswith("/siteid"):
        site_id = message["text"].split()[1]
        pdf_path = os.path.join(PDF_OUTPUT_DIR, f"{site_id}.pdf")
        create_pdf(pending_photos, pdf_path)
        send_email(EMAIL_SUBJECT.format(site_id=site_id), EMAIL_BODY.format(site_id=site_id), pdf_path)
        bot.send_message(chat_id, f"✅ PDF created & emailed for Site {site_id}")
        pending_photos.clear()

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
