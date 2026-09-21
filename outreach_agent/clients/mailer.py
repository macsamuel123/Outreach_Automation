import imaplib
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.parser import BytesParser
from typing import Optional

from .http_base import RetriableAPIError


@dataclass
class ParsedMessage:
    """Parsed inbound email."""

    from_addr: str
    subject: str
    body_text: str
    in_reply_to: Optional[str]
    message_id: str
    date: datetime
    uid: int


def send_email(
    smtp_host: str,
    smtp_port: int,
    sender: str,
    password: str,
    to_addr: str,
    subject: str,
    body: str,
    headers: Optional[dict] = None,
    custom_headers: Optional[dict] = None,
) -> None:
    """Send an email via SMTP.

    Args:
        smtp_host: SMTP server hostname
        smtp_port: SMTP port (usually 465 for SSL, 587 for STARTTLS)
        sender: Sender email address
        password: App password or account password
        to_addr: Recipient email address
        subject: Email subject
        body: Email body (plain text)
        custom_headers: Additional headers to include (e.g., X-Curate-Lead-Id)

    Raises:
        RetriableAPIError on SMTP failures
    """
    try:
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)

        if custom_headers:
            for key, value in custom_headers.items():
                msg[key] = value

        # Generate a Message-ID for tracking
        msg["Message-ID"] = f"<{datetime.utcnow().isoformat()}@curateanalytics.ca>"

        # Send via SMTP
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                server.login(sender, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.starttls()
                server.login(sender, password)
                server.send_message(msg)

    except smtplib.SMTPAuthenticationError as e:
        raise RetriableAPIError(f"SMTP auth failed: {e}")
    except smtplib.SMTPException as e:
        raise RetriableAPIError(f"SMTP error: {e}")
    except Exception as e:
        raise RetriableAPIError(f"Email send failed: {e}")


def poll_inbox(
    imap_host: str,
    email_address: str,
    password: str,
    since_uid: int = 0,
    timeout_s: int = 30,
) -> list[ParsedMessage]:
    """Poll inbox for new messages using IMAP UID-based approach.

    UID-based polling is idempotent: a human checking the inbox in a browser
    won't silently mark messages as read and break our deduplication.

    Args:
        imap_host: IMAP server hostname
        email_address: Email address
        password: App password
        since_uid: Start from this UID (exclusive), 0 for all

    Returns:
        List of ParsedMessage objects

    Raises:
        RetriableAPIError on IMAP failures
    """
    messages = []

    try:
        with imaplib.IMAP4_SSL(imap_host, 993, timeout=timeout_s) as imap:
            imap.login(email_address, password)
            imap.select("INBOX")

            # Search for UIDs greater than since_uid
            if since_uid > 0:
                search_query = f"UID {since_uid + 1}:*"
            else:
                search_query = "ALL"

            status, uids_bytes = imap.uid("search", None, search_query)
            if status != "OK":
                raise RetriableAPIError(f"IMAP search failed: {status}")

            uids = uids_bytes[0].split() if uids_bytes[0] else []

            for uid in uids:
                try:
                    status, msg_bytes = imap.uid("fetch", uid, "(RFC822)")
                    if status != "OK":
                        continue

                    msg_data = msg_bytes[0][1]
                    parser = BytesParser()
                    email_msg = parser.parsebytes(msg_data)

                    # Extract fields
                    from_addr = email_msg.get("From", "").split("<")[-1].rstrip(">")
                    subject = email_msg.get("Subject", "")
                    in_reply_to = email_msg.get("In-Reply-To")
                    message_id = email_msg.get("Message-ID", "")

                    # Parse date
                    date_str = email_msg.get("Date", "")
                    try:
                        from email.utils import parsedate_to_datetime

                        date = parsedate_to_datetime(date_str)
                    except Exception:
                        date = datetime.utcnow()

                    # Extract body (prefer plain text)
                    body_text = ""
                    if email_msg.is_multipart():
                        for part in email_msg.walk():
                            if part.get_content_type() == "text/plain":
                                body_text = part.get_payload(decode=True).decode(
                                    "utf-8", errors="ignore"
                                )
                                break
                    else:
                        body_text = email_msg.get_payload(decode=True).decode(
                            "utf-8", errors="ignore"
                        )

                    uid_int = int(uid)
                    messages.append(
                        ParsedMessage(
                            from_addr=from_addr,
                            subject=subject or "",
                            body_text=body_text,
                            in_reply_to=in_reply_to,
                            message_id=message_id,
                            date=date,
                            uid=uid_int,
                        )
                    )
                except Exception as e:
                    # Skip malformed messages
                    continue

    except imaplib.IMAP4.error as e:
        raise RetriableAPIError(f"IMAP error: {e}")
    except Exception as e:
        raise RetriableAPIError(f"IMAP poll failed: {e}")

    return messages
