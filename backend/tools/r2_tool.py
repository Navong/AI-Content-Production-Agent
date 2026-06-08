"""Cloudflare R2 image storage (Pillar 2: tool layer).

R2 is S3-compatible — boto3 talks to it via a custom endpoint URL.
Uploads image bytes and returns a permanent public URL so generated images
survive Replicate's ~24 h signed-URL expiry.

Graceful fallback: if R2 credentials are not set, returns None and the
caller keeps the original Replicate URL. The app works either way.

Required env vars:
  CLOUDFLARE_ACCOUNT_ID
  R2_ACCESS_KEY_ID
  R2_SECRET_ACCESS_KEY
  R2_BUCKET_NAME
  R2_PUBLIC_URL   e.g. https://pub-xxxx.r2.dev  (or your custom domain)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
    return _client


def _r2_configured() -> bool:
    return all(
        os.getenv(k)
        for k in (
            "CLOUDFLARE_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET_NAME",
            "R2_PUBLIC_URL",
        )
    )


def upload_image(image_url: str, thread_id: str, iteration: int) -> str | None:
    """Download `image_url` and upload to R2.

    Returns the permanent public URL on success, or None if R2 is not
    configured (caller should fall back to the original URL).
    """
    if not _r2_configured():
        logger.debug("R2 not configured — skipping upload")
        return None

    # Download image bytes from Replicate delivery URL
    resp = requests.get(image_url, timeout=30)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "image/png").split(";")[0].strip()
    ext = "png" if "png" in content_type else "jpg"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    key = f"content-agent/{thread_id}/iter{iteration}_{ts}.{ext}"

    bucket = os.environ["R2_BUCKET_NAME"]
    try:
        _get_client().put_object(
            Bucket=bucket,
            Key=key,
            Body=resp.content,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as e:
        logger.warning("R2 upload failed: %s", e)
        return None

    public_url = os.environ["R2_PUBLIC_URL"].rstrip("/")
    permanent_url = f"{public_url}/{key}"
    logger.info("R2 upload ok: %s", permanent_url)
    return permanent_url


def upload_bytes(data: bytes, content_type: str, thread_id: str, label: str) -> str | None:
    """Upload raw bytes (e.g. a user-uploaded product photo) to R2.

    Returns the permanent public URL, or None if R2 isn't configured.
    """
    if not _r2_configured():
        return None
    ext = "png" if "png" in content_type else ("webp" if "webp" in content_type else "jpg")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    key = f"content-agent/{thread_id}/{label}_{ts}.{ext}"
    try:
        _get_client().put_object(
            Bucket=os.environ["R2_BUCKET_NAME"],
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as e:
        logger.warning("R2 bytes upload failed: %s", e)
        return None
    return f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/{key}"
