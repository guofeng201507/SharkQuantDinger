"""Per-locale product documentation (in-app user guide and friends).

Rows are keyed by ``(slug, locale)`` so a document can exist in several
languages; readers pick by the caller's UI language (``X-App-Lang``) and fall
back to any edition rather than failing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Generous ceiling: the user guide is ~70 KB; this blocks accidental blobs.
MAX_CONTENT_BYTES = 1024 * 1024


class DocError(Exception):
    """Validation failure while writing a document."""

    def __init__(self, message: str, *, http: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.http = http


def _normalize_locale(locale: Optional[str]) -> str:
    from app.utils.language import _normalize_lang

    return _normalize_lang(locale) or "en-US"


def get_doc(slug: str, locale: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the document for ``locale``, else any available edition."""
    s = str(slug or "").strip()
    if not s:
        return None
    want = _normalize_locale(locale)
    with get_db_connection() as db:
        cur = db.cursor()
        try:
            cur.execute(
                """
                SELECT slug, locale, title, content_md, updated_by, updated_at
                FROM qd_docs
                WHERE slug = %s AND locale = %s
                """,
                (s, want),
            )
            row = cur.fetchone()
            if not row:
                # Any edition beats a 404: an untranslated doc still renders.
                cur.execute(
                    """
                    SELECT slug, locale, title, content_md, updated_by, updated_at
                    FROM qd_docs
                    WHERE slug = %s
                    ORDER BY (locale = 'en-US') DESC, updated_at DESC
                    LIMIT 1
                    """,
                    (s,),
                )
                row = cur.fetchone()
        finally:
            cur.close()
    return dict(row) if row else None


def upsert_doc(
    slug: str,
    locale: Optional[str],
    content_md: str,
    *,
    title: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Create or replace one edition of a document."""
    s = str(slug or "").strip()
    if not s or not s.replace("-", "").replace("_", "").isalnum():
        raise DocError("slug must be alphanumeric (dashes/underscores allowed)")
    body = content_md if isinstance(content_md, str) else ""
    if not body.strip():
        raise DocError("content_md must not be empty")
    if len(body.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise DocError(f"content_md exceeds {MAX_CONTENT_BYTES} bytes")

    loc = _normalize_locale(locale)
    with get_db_connection() as db:
        cur = db.cursor()
        try:
            cur.execute(
                """
                INSERT INTO qd_docs (slug, locale, title, content_md, updated_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (slug, locale) DO UPDATE
                SET content_md = EXCLUDED.content_md,
                    title = EXCLUDED.title,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = now()
                RETURNING slug, locale, title, updated_at
                """,
                (s, loc, (title or None), body, user_id),
            )
            row = cur.fetchone()
            db.commit()
        finally:
            cur.close()
    logger.info("doc upserted slug=%s locale=%s user_id=%s", s, loc, user_id)
    return dict(row) if row else {"slug": s, "locale": loc}


def list_docs() -> List[Dict[str, Any]]:
    """Inventory of stored editions (no bodies) for admin views."""
    with get_db_connection() as db:
        cur = db.cursor()
        try:
            cur.execute(
                """
                SELECT slug, locale, title,
                       length(content_md) AS content_length,
                       updated_by, updated_at
                FROM qd_docs
                ORDER BY slug, locale
                """
            )
            rows = cur.fetchall() or []
        finally:
            cur.close()
    return [dict(r) for r in rows]
