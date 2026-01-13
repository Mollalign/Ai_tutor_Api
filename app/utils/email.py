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
        
    Returns:
        True if email sent successfully, False otherwise
    """
    subject = f"Password Reset Code - {settings.PROJECT_NAME}"
    
    html_content = f"""
    <html>
        <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; background-color: #f9fafb;">
            <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
                <div style="background-color: #ffffff; border-radius: 12px; padding: 40px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                    <!-- Header -->
                    <div style="text-align: center; margin-bottom: 30px;">
                        <h1 style="color: #4f46e5; font-size: 24px; margin: 0;">{settings.PROJECT_NAME}</h1>
                    </div>
                    
                    <!-- Title -->
                    <h2 style="color: #1f2937; font-size: 20px; margin-bottom: 20px;">Password Reset Request</h2>
                    
                    <p style="color: #4b5563; margin-bottom: 15px;">Hello,</p>
                    <p style="color: #4b5563; margin-bottom: 25px;">
                        You have requested to reset your password for your {settings.PROJECT_NAME} account.
                    </p>
                    
                    <p style="color: #4b5563; margin-bottom: 15px;">Your password reset code is:</p>
                    
                    <!-- Code Box -->
                    <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); border-radius: 8px; padding: 25px; text-align: center; margin: 25px 0;">
                        <h1 style="color: #ffffff; font-size: 36px; letter-spacing: 8px; margin: 0; font-family: 'Courier New', monospace;">{code}</h1>
                    </div>
                    
                    <!-- Expiration Warning -->
                    <div style="background-color: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px 16px; margin: 25px 0; border-radius: 0 8px 8px 0;">
                        <p style="color: #92400e; margin: 0; font-size: 14px;">
                            ⏱️ This code will expire in <strong>{expires_in_minutes} minutes</strong>.
                        </p>
                    </div>
                    
                    <p style="color: #6b7280; font-size: 14px; margin-top: 25px;">
                        If you did not request this password reset, please ignore this email. Your account remains secure.
                    </p>
                    
                    <!-- Footer -->
                    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
                    <p style="color: #9ca3af; font-size: 12px; text-align: center; margin: 0;">
                        This is an automated message from {settings.PROJECT_NAME}. Please do not reply to this email.
                    </p>
                </div>
            </div>
        </body>
    </html>
    """
    
    plain_content = f"""
{settings.PROJECT_NAME} - Password Reset Request

Hello,

You have requested to reset your password for your {settings.PROJECT_NAME} account.

Your password reset code is: {code}

⏱️ This code will expire in {expires_in_minutes} minutes.

If you did not request this password reset, please ignore this email. Your account remains secure.

---
This is an automated message from {settings.PROJECT_NAME}. Please do not reply to this email.
    """
    
    # Try HTML first, fallback to plain text
    success = send_email([email], subject, html_content, "html")
    if not success:
        return send_email([email], subject, plain_content, "plain")
    return success
