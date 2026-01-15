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
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>Password Reset</title>
    </head>
    <body style="
    margin: 0;
    padding: 0;
    background-color: #f3f4f6;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    color: #111827;
    ">

    <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
        <td align="center" style="padding: 40px 16px;">
            
            <!-- Card -->
            <table width="100%" cellpadding="0" cellspacing="0" style="
            max-width: 600px;
            background-color: #ffffff;
            border-radius: 14px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.08);
            overflow: hidden;
            ">
            
            <!-- Header -->
            <tr>
                <td style="
                background: linear-gradient(135deg, #4f46e5, #7c3aed);
                padding: 32px;
                text-align: center;
                ">
                <h1 style="
                    margin: 0;
                    font-size: 22px;
                    color: #ffffff;
                    font-weight: 700;
                    letter-spacing: 0.5px;
                ">
                    {settings.PROJECT_NAME}
                </h1>
                </td>
            </tr>

            <!-- Body -->
            <tr>
                <td style="padding: 32px;">
                
                <h2 style="
                    margin-top: 0;
                    font-size: 20px;
                    font-weight: 600;
                    color: #111827;
                ">
                    Reset your password
                </h2>

                <p style="font-size: 15px; color: #374151;">
                    Hi there 👋
                </p>

                <p style="font-size: 15px; color: #374151; line-height: 1.6;">
                    We received a request to reset the password for your
                    <strong>{settings.PROJECT_NAME}</strong> account.
                    Use the code below to continue.
                </p>

                <!-- Code -->
                <div style="
                    margin: 28px 0;
                    padding: 20px;
                    text-align: center;
                    background-color: #f9fafb;
                    border: 2px dashed #6366f1;
                    border-radius: 10px;
                ">
                    <div style="
                    font-size: 36px;
                    font-weight: 700;
                    letter-spacing: 10px;
                    color: #4f46e5;
                    font-family: 'Courier New', Courier, monospace;
                    ">
                    {code}
                    </div>
                </div>

                <!-- Expiration -->
                <div style="
                    background-color: #fffbeb;
                    border-left: 4px solid #f59e0b;
                    padding: 12px 16px;
                    border-radius: 6px;
                    margin-bottom: 24px;
                ">
                    <p style="
                    margin: 0;
                    font-size: 14px;
                    color: #92400e;
                    ">
                    ⏳ This code expires in <strong>{expires_in_minutes} minutes</strong>.
                    </p>
                </div>

                <p style="font-size: 14px; color: #6b7280; line-height: 1.6;">
                    If you didn’t request this, you can safely ignore this email.
                    Your account remains secure.
                </p>

                </td>
            </tr>

            <!-- Footer -->
            <tr>
                <td style="
                padding: 20px;
                text-align: center;
                background-color: #f9fafb;
                border-top: 1px solid #e5e7eb;
                ">
                <p style="
                    margin: 0;
                    font-size: 12px;
                    color: #9ca3af;
                ">
                    © {settings.PROJECT_NAME} · Automated message · Do not reply
                </p>
                </td>
            </tr>

            </table>

        </td>
        </tr>
    </table>

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
