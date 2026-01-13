"""
Email Utility

Helper functions for sending emails.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

def send_email(
    recipients: List[str],
    subject: str,
    content: str,
    content_type: str = "plain"
) -> bool:
    """
    Send an email using SMTP settings from config.
    
    Args:
        recipients: List of email addresses
        subject: Email subject
        content: Email body
        content_type: "plain" or "html"
        
    Returns:
        True if successful, False otherwise
    """
    if not settings.SMTP_SERVER or not settings.SMTP_EMAIL:
        logger.warning("SMTP settings not configured. Email not sent.")
        print(f"Mock Email: To={recipients}, Subject={subject}, Body={content[:50]}...")
        return False
        
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_EMAIL
        msg["To"] = ", ".join(recipients)
        
        part = MIMEText(content, content_type)
        msg.attach(part)
        
        # Connect to SMTP server
        # Explicitly convert port to int if present, else default
        port = int(settings.SMTP_PORT) if settings.SMTP_PORT else 587
        
        with smtplib.SMTP(settings.SMTP_SERVER, port) as server:
            server.starttls()
            if settings.SMTP_PASSWORD:
                server.login(settings.SMTP_EMAIL, settings.SMTP_PASSWORD)
            server.send_message(msg)
            
        logger.info(f"Email sent to {recipients}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        # In production we might want to re-raise or handle differently
        return False

def send_password_reset_code(email: str, code: str, expires_in_minutes: int = 15):
    """
    Send a password reset code email.
    
    Args:
        email: User email address
        code: 6-digit reset code
        expires_in_minutes: Code expiration time in minutes
    """
    subject = "Password Reset Code - Hena Books"
    
    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2c3e50;">Password Reset Request</h2>
                <p>Hello,</p>
                <p>You have requested to reset your password for your Hena Books account.</p>
                <p>Your password reset code is:</p>
                <div style="background-color: #f4f4f4; border: 2px dashed #3498db; padding: 20px; text-align: center; margin: 20px 0;">
                    <h1 style="color: #3498db; font-size: 32px; letter-spacing: 5px; margin: 0;">{code}</h1>
                </div>
                <p>This code will expire in <strong>{expires_in_minutes} minutes</strong>.</p>
                <p>If you did not request this password reset, please ignore this email. Your account remains secure.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #7f8c8d; font-size: 12px;">
                    This is an automated message. Please do not reply to this email.
                </p>
            </div>
        </body>
    </html>
    """
    
    plain_content = f"""
Password Reset Request

Hello,

You have requested to reset your password for your Hena Books account.

Your password reset code is: {code}

This code will expire in {expires_in_minutes} minutes.

If you did not request this password reset, please ignore this email. Your account remains secure.
    """
    
    # Try HTML first, fallback to plain text
    success = send_email([email], subject, html_content, "html")
    if not success:
        return send_email([email], subject, plain_content, "plain")
    return success
