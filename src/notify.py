"""
Send the digest email via the Resend REST API — one authenticated POST.

Environment (set as GitHub Actions secrets, passed in as env vars):
    RESEND_API_KEY   Resend API key
    EMAIL_TO         recipient address (comma-separate for several)
    EMAIL_FROM       verified sender address
"""

import base64
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


def send_email(
    subject: str,
    html: str,
    text: str,
    inline_images: list[tuple[Path, str]] | None = None,
) -> str:
    """
    Send one email. inline_images is a list of (png_path, content_id)
    pairs referenced from the HTML as <img src="cid:content_id">.
    Returns the Resend message id. Raises on any failure.
    """
    api_key = os.environ["RESEND_API_KEY"]
    email_to = [e.strip() for e in os.environ["EMAIL_TO"].split(",") if e.strip()]
    email_from = os.environ["EMAIL_FROM"]

    payload = {
        "from": email_from,
        "to": email_to,
        "subject": subject,
        "html": html,
        "text": text,
    }

    if inline_images:
        payload["attachments"] = [
            {
                "filename": path.name,
                "content": base64.b64encode(path.read_bytes()).decode(),
                "content_id": content_id,
            }
            for path, content_id in inline_images
        ]

    resp = requests.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    message_id = resp.json().get("id", "?")
    logger.info("Email sent: %s", message_id)
    return message_id
