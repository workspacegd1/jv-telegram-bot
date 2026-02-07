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
from pypdf import PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO
from datetime import datetime
import requests
import time
import json

# ==================== CONFIGURATION ====================

# Telegram Bot Configuration (from ENV)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YOUR_CHAT_ID = os.getenv("YOUR_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not YOUR_CHAT_ID:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN or YOUR_CHAT_ID in ENV")

# Email Configuration (from ENV)
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "workspaceegd@gmail.com")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

if not SENDER_PASSWORD:
    raise ValueError("Missing SENDER_PASSWORD in ENV")

# Recipients (all 7 same)
RECIPIENTS = [
    "workspaceegd@gmail.com",
    "workspaceegd@gmail.com",
    "workspaceegd@gmail.com",
    "workspaceegd@gmail.com",
    "workspaceegd@gmail.com",
    "workspaceegd@gmail.com",
    "workspaceegd@gmail.com"
]

# Email Template
EMAIL_SUBJECT = "Submission of Joint Visit (JV) Documents – Indus ID: {site_id}"
EMAIL_BODY = """Dear Sir,

Please find attached the Joint Visit (JV) documents for your reference. The site details and photographs are attached as a single PDF.

Indus ID: {site_id}

Best regards,
Satendra Kumar Dubey
Mobile: +91 98931 00138
Email: workspaceegd@gmail.com
"""

# SMTP Configuration (Gmail)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Directories
DOWNLOAD_DIR = "./telegram_photos"
PDF_OUTPUT_DIR = "./pdfs"
ARCHIVE_DIR = "./archive"
LOG_FILE = "./submissions_log.txt"

# Photo limits (removed - accept any quantity)
# MIN_PHOTOS = 50
# MAX_PHOTOS = 150

# Image compression settings
MAX_IMAGE_SIZE_MB = 2  # Compress images larger than 2MB
COMPRESSION_QUALITY = 85  # Quality: 1-100 (85 is good balance)
MAX_IMAGE_DIMENSION = 2048  # Max width/height in pixels

# ==================== SETUP ====================

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('bot.log'), logging.StreamHandler()]
)

# ==================== TELEGRAM BOT FUNCTIONS ====================

class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        self.pending_photos = []
        self.waiting_for_siteid = False
        
    def send_message(self, chat_id, text):
        url = f"{self.api_url}/sendMessage"
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        return requests.post(url, data=data).json()
    
    def send_document(self, chat_id, file_path, caption=""):
        url = f"{self.api_url}/sendDocument"
        with open(file_path, 'rb') as file:
            files = {'document': file}
            data = {"chat_id": chat_id, "caption": caption}
            return requests.post(url, data=data, files=files).json()
    
    def edit_message(self, chat_id, message_id, text):
        url = f"{self.api_url}/editMessageText"
        data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
        try:
            return requests.post(url, data=data).json()
        except:
            return None
    
    def download_photo(self, file_id, save_path):
        file_info_url = f"{self.api_url}/getFile?file_id={file_id}"
        file_info = requests.get(file_info_url).json()
        if not file_info.get('ok'):
            return False
        file_path = file_info['result']['file_path']
        download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        response = requests.get(download_url)
        with open(save_path, 'wb') as f:
            f.write(response.content)
        return True
    
    def get_updates(self, offset=None):
        url = f"{self.api_url}/getUpdates"
        params = {"timeout": 30, "offset": offset}
        return requests.get(url, params=params).json()

# ==================== IMAGE PROCESSING ====================

def compress_image(image_path, max_size_mb=2, quality=85, max_dimension=2048):
    try:
        file_size_mb = os.path.getsize(image_path) / (1024 * 1024)
        img = Image.open(image_path)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        width, height = img.size
        if width > max_dimension or height > max_dimension:
            if width > height:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        if file_size_mb > max_size_mb or width > max_dimension or height > max_dimension:
            img.save(image_path, 'JPEG', quality=quality, optimize=True)
            return True
        return False
    except Exception as e:
        logging.error(f"Error compressing {image_path}: {str(e)}")
        return False

# ==================== PDF CREATION ====================

def create_pdf_from_images(image_files, output_pdf_path, bot, chat_id, site_id, page_size=A4):
    writer = PdfWriter()
    total_images = len(image_files)
    progress_msg = bot.send_message(chat_id, 
        f"📊 <b>Progress for Site {site_id}</b>\n\n"
        f"🔄 Compressing images...\n"
        f"Progress: 0/{total_images}")
    message_id = progress_msg['result']['message_id']

    for i, img_path in enumerate(image_files, 1):
        compress_image(img_path, MAX_IMAGE_SIZE_MB, COMPRESSION_QUALITY, MAX_IMAGE_DIMENSION)
        if i % 5 == 0 or i == total_images:
            bot.edit_message(chat_id, message_id,
                f"📊 <b>Progress for Site {site_id}</b>\n\n"
                f"🔄 Creating PDF pages...\n"
                f"Progress: {i}/{total_images}")

    for i, img_path in enumerate(image_files, 1):
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=page_size)
        page_width, page_height = page_size
        img = Image.open(img_path)
        img_width, img_height = img.size
        scale_ratio = min((page_width - 40) / img_width, (page_height - 40) / img_height)
        new_width = img_width * scale_ratio
        new_height = img_height * scale_ratio
        x_offset = (page_width - new_width) / 2
        y_offset = (page_height - new_height) / 2
        can.drawImage(img_path, x_offset, y_offset, new_width, new_height)
        can.save()
        packet.seek(0)
        from pypdf import PdfReader
        temp_pdf = PdfReader(packet)
        writer.add_page(temp_pdf.pages[0])

    with open(output_pdf_path, "wb") as f:
        writer.write(f)

    pdf_size_mb = os.path.getsize(output_pdf_path) / (1024 * 1024)
    return True, message_id, pdf_size_mb

# ==================== EMAIL SENDING ====================

def send_email_with_attachment(recipients, subject, body, attachment_path):
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = ", ".join(recipients)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        with open(attachment_path, "rb") as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f"attachment; filename= {os.path.basename(attachment_path)}")
        msg.attach(part)
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, recipients, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logging.error(f"Email error: {str(e)}")
        return False

# ==================== LOGGING ====================

def log_submission(site_id, photo_count, status):
    timestamp = datetime.now().strftime("%d-%b-%Y %H:%M")
    with open(LOG_FILE, 'a') as f:
        f.write(f"{timestamp} | Site ID: {site_id} | Photos: {photo_count} | Status: {status}\n")

# ==================== MAIN BOT LOGIC ====================

def process_site(bot, chat_id, site_id, photo_files):
    photo_count = len(photo_files)
    bot.send_message(chat_id, f"🚀 <b>Starting Processing</b>\n\n📋 Site ID: {site_id}\n📸 Total Photos: {photo_count}\n\nPlease wait...")
    pdf_path = os.path.join(PDF_OUTPUT_DIR, f"{site_id}.pdf")
    success, progress_msg_id, pdf_size_mb = create_pdf_from_images(photo_files, pdf_path, bot, chat_id, site_id)
    subject = EMAIL_SUBJECT.format(site_id=site_id)
    body = EMAIL_BODY.format(site_id=site_id)

    if send_email_with_attachment(RECIPIENTS, subject, body, pdf_path):
        bot.edit_message(chat_id, progress_msg_id,
            f"📊 <b>Progress for Site {site_id}</b>\n\n"
            f"✅ PDF Created: {photo_count} pages ({pdf_size_mb:.2f}MB)\n"
            f"✅ Email Sent: {len(RECIPIENTS)} recipients\n\n<b>COMPLETED!</b>")
        bot.send_document(chat_id, pdf_path, f"PDF for Site {site_id}")
        log_submission(site_id, photo_count, "Success")
        archive_path = os.path.join(ARCHIVE_DIR, site_id)
        os.makedirs(archive_path, exist_ok=True)
        for photo in photo_files:
            if os.path.exists(photo):
                os.rename(photo, os.path.join(archive_path, os.path.basename(photo)))
        return True
    else:
        bot.send_message(chat_id, "❌ Error sending email. Check bot.log for details.")
        log_submission(site_id, photo_count, "Email Error")
        return False

def main():
    bot = TelegramBot(TELEGRAM_BOT_TOKEN)
    bot.send_message(YOUR_CHAT_ID, "🤖 <b>JV Report Bot Started!</b>\n\nSend photos and use:\n/siteid 1333453")
    pending_photos = []

    while True:
        try:
            updates = bot.get_updates(offset=bot.last_update_id + 1)
            if not updates.get('ok'):
                time.sleep(1)
                continue
            for update in updates.get('result', []):
                bot.last_update_id = update['update_id']
                if 'message' not in update:
                    continue
                message = update['message']
                chat_id = message['chat']['id']
                if str(chat_id) != str(YOUR_CHAT_ID):
                    bot.send_message(chat_id, "⛔ Unauthorized access.")
                    continue
                if 'photo' in message:
                    photo = message['photo'][-1]
                    filename = f"photo_{int(time.time())}_{len(pending_photos)}.jpg"
                    filepath = os.path.join(DOWNLOAD_DIR, filename)
                    if bot.download_photo(photo['file_id'], filepath):
                        pending_photos.append(filepath)
                    continue
                if 'text' in message and message['text'].startswith('/siteid'):
                    site_id = message['text'].split()[1]
                    if not pending_photos:
                        bot.send_message(chat_id, "❌ No photos received yet!")
                        continue
                    process_site(bot, chat_id, site_id, pending_photos.copy())
                    pending_photos.clear()
        except Exception as e:
            logging.error(f"Bot error: {str(e)}")
            time.sleep(5)

if __name__ == "__main__":
    main()
