"""
SBAB Rate Notifier
Sends email notifications based on analysis results
"""
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# Configuration (from environment variables)
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASS = os.getenv('SMTP_PASS')
TO_EMAIL_RAW = os.getenv('TO_EMAIL', '')
# Support comma-separated email addresses
TO_EMAIL = [email.strip() for email in TO_EMAIL_RAW.split(',') if email.strip()]


def send_email(subject, body, attachments=None):
    """Send email via SMTP.

    Args:
        subject: Email subject
        body: Email body text
        attachments: List of file paths to attach
    """
    if not all([SMTP_USER, SMTP_PASS]) or not TO_EMAIL:
        print("ERROR: Email credentials not configured")
        print("  Set environment variables: SMTP_USER, SMTP_PASS, TO_EMAIL")
        return False

    # Create message
    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = ', '.join(TO_EMAIL)  # Join multiple recipients
    msg['Subject'] = subject

    # Add body
    msg.attach(MIMEText(body, 'plain'))

    # Add file attachments
    if attachments:
        for filepath in attachments:
            if not filepath.exists():
                print(f"Warning: Attachment not found: {filepath}")
                continue

            with open(filepath, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())

            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename={filepath.name}'
            )
            msg.attach(part)

    # Send
    try:
        print(f"Connecting to {SMTP_HOST}:{SMTP_PORT}...")
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        
        print("Logging in...")
        server.login(SMTP_USER, SMTP_PASS)
        
        print(f"Sending email to {TO_EMAIL}...")
        server.send_message(msg)
        server.quit()
        
        print(f"✓ Email sent successfully")
        return True
        
    except Exception as e:
        # Re-raise: the pipeline reports a failed send (non-zero exit) instead of
        # printing "PIPELINE COMPLETE". Unconfigured credentials still return False above.
        print(f"ERROR sending email: {e}")
        raise
