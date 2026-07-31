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


def _required_env(*names: str) -> list[str]:
    """
    Fetch required environment variables, failing with a message that names
    what's missing. GitHub Actions passes unset secrets through as empty
    strings rather than omitting them, so blank counts as missing - without
    this check a missing secret surfaces as a bare KeyError, or worse, an
    empty Authorization header and a confusing 401 from the API.
    """
    values, missing = [], []
    for name in names:
        value = os.environ.get(name, "").strip()
        if not value:
            missing.append(name)
        values.append(value)

    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Set them as repository secrets under "
            "Settings > Secrets and variables > Actions."
        )
    return values


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
    api_key, email_to_raw, email_from = _required_env(
        "RESEND_API_KEY", "EMAIL_TO", "EMAIL_FROM"
    )
    email_to = [e.strip() for e in email_to_raw.split(",") if e.strip()]

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
