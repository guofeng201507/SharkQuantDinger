"""Social sentiment context for AI analysis.

Combines two optional, fail-open sources:

- Adanos (also used by the market sentiment route): pre-computed US-stock
  sentiment metrics (buzz, bullish/bearish share, mentions, trend).
- twitterapi.io: recent X (Twitter) posts matching the instrument's cashtag,
  trimmed into an engagement-ranked digest for the LLM prompt.

Everything here is supplementary: without keys or on upstream errors callers
get ``enabled=False`` and the analysis proceeds unchanged.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import requests

from app.config import APIKeys
from app.utils.cache import CacheManager
from app.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://api.twitterapi.io"
CACHE_TTL_SEC = 900
NEGATIVE_CACHE_TTL_SEC = 120
MAX_DIGEST_TWEETS = 12
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

_cache = CacheManager()


def social_query_for(market: str, symbol: str) -> Optional[str]:
    """Cashtag query used to search X for this instrument (None = unsupported)."""
    m = str(market or "").strip()
    s = str(symbol or "").strip()
    if m == "Crypto":
        base = s.split("/")[0].split(":")[-1].strip().upper()
        return f"${base}" if base and _TICKER_RE.match(base) else None
    if m == "USStock":
        ticker = s.replace("$", "").upper()
        return f"${ticker}" if _TICKER_RE.match(ticker) else None
    return None


def fetch_social_context(market: str, symbol: str) -> Dict[str, Any]:
    """Adanos metrics + X digest for one instrument, cached and fail-open."""
    cache_key = f"social_context:{market}:{symbol}"
    cached = _cache.get(cache_key)
    if isinstance(cached, dict):
        return cached

    result: Dict[str, Any] = {
        "enabled": False,
        "market": market,
        "symbol": symbol,
        "adanos": None,
        "x": None,
    }

    adanos = _fetch_adanos(symbol) if str(market or "").strip() == "USStock" else None
    if adanos:
        result["adanos"] = adanos
        result["enabled"] = True

    query = social_query_for(market, symbol)
    if query:
        tweets = _search_x(query)
        if tweets:
            result["x"] = {"query": query, "provider": "twitterapi.io", "tweets": tweets}
            result["enabled"] = True

    _cache.set(
        cache_key,
        result,
        CACHE_TTL_SEC if result["enabled"] else NEGATIVE_CACHE_TTL_SEC,
    )
    if result["enabled"]:
        logger.info(
            "social context loaded market=%s symbol=%s adanos=%s x_tweets=%d",
            market,
            symbol,
            bool(adanos),
            len((result.get("x") or {}).get("tweets") or []),
        )
    return result


def _fetch_adanos(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        from app.data_providers.adanos_sentiment import fetch_adanos_market_sentiment

        payload = fetch_adanos_market_sentiment(symbol, days=7)
        stocks = payload.get("stocks") or []
        return stocks[0] if stocks else None
    except Exception as exc:  # noqa: BLE001 - optional enrichment must never raise
        logger.debug("Adanos social block skipped: %s", exc)
        return None


def _base_url() -> str:
    return (os.getenv("TWITTERAPI_IO_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def _timeout() -> int:
    try:
        return max(1, int(os.getenv("TWITTERAPI_IO_TIMEOUT", "8")))
    except ValueError:
        return 8


def _search_x(query: str) -> List[Dict[str, Any]]:
    key = str(APIKeys.TWITTERAPI_IO_KEY or "").strip()
    if not key:
        return []
    try:
        response = requests.get(
            f"{_base_url()}/twitter/tweet/advanced_search",
            params={"query": query, "queryType": "Latest"},
            headers={"X-API-Key": key, "Accept": "application/json"},
            timeout=_timeout(),
        )
    except requests.RequestException as exc:
        logger.warning("X discussion search failed: %s", exc)
        return []
    if response.status_code != 200:
        logger.warning("X discussion search returned HTTP %s", response.status_code)
        return []
    try:
        rows = (response.json() or {}).get("tweets") or []
    except ValueError:
        return []

    digest: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        text = re.sub(r"https?://\S+", "", text).strip()
        if not text:
            continue
        digest.append({
            "text": text,
            "likes": int(row.get("likeCount") or 0),
            "retweets": int(row.get("retweetCount") or 0),
            "replies": int(row.get("replyCount") or 0),
            "created_at": str(row.get("createdAt") or ""),
            "url": str(row.get("url") or ""),
        })
    digest.sort(key=lambda item: item["likes"] + 2 * item["retweets"], reverse=True)
    return digest[:MAX_DIGEST_TWEETS]


__all__ = ["fetch_social_context", "social_query_for"]
