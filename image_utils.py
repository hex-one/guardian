"""
image_utils.py

Tiny shared helper: fetch an image's raw bytes through the authenticated
VRChat session. Kept Qt-free on purpose (same separation as vrchat_api.py
vs the dialogs) -- callers decide whether to turn the bytes into a QPixmap
(for delegate-painted icons) or a base64 data: URI (for inline <img> tags
in QLabel rich text). One clean job, done well, handed off to whoever
needs it next.
"""

from typing import Optional


def fetch_image_bytes(client, url: str, timeout: int = 5) -> Optional[tuple]:
    """
    Returns (content_bytes, content_type) on success, or None on any
    failure (missing URL, network error, non-200 response). A broken/
    missing image is always cosmetic here -- callers should treat None as
    "just don't show an icon," never as something worth failing over.
    """
    if not url:
        return None
    try:
        response = client.session.get(url, timeout=timeout)
        if response.status_code != 200:
            return None
        content_type = response.headers.get("Content-Type", "image/png")
        return response.content, content_type
    except Exception:
        return None
