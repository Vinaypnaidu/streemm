import smtplib
from email.message import EmailMessage
from typing import Optional
from config import settings

def send_email(to: str, subject: str, text: str) -> None:
    if not settings.email_enabled:
        return

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)

    if settings.smtp_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port) as s:
            if settings.smtp_username and settings.smtp_password:
                s.login(settings.smtp_username, settings.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
            s.ehlo()
            if settings.smtp_starttls:
                s.starttls()
                s.ehlo()
            if settings.smtp_username and settings.smtp_password:
                s.login(settings.smtp_username, settings.smtp_password)
            s.send_message(msg)