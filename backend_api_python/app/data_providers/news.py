"""Financial news and economic calendar data providers."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from app.data_providers.economic_calendar import (
    get_economic_calendar,
    get_economic_calendar_payload,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# The search layer walks several engines per query (GDELT alone was seen taking
# ~16s from Singapore, plus 429 retries), so twelve sequential queries used to
# exceed the 60s proxy default and surfaced as a 504. Run the queries in
# parallel under one wall-clock budget instead: a slow engine now delays its own
# query only, and whatever arrived before the deadline is returned.
_NEWS_DEADLINE_SECONDS = 25


def fetch_financial_news(lang: str = "all") -> Dict[str, List[Dict[str, Any]]]:
    """Fetch financial news using search service — separated by language."""
    result: Dict[str, List[Dict[str, Any]]] = {"cn": [], "en": []}

    try:
        from app.services.search import SearchService
        search = SearchService()

        cn_queries = [
            "加密货币新闻", "美联储利率", "美股市场最新消息",
            "外汇市场分析", "全球经济数据", "期货市场动态",
        ]
        en_queries = [
            "stock market news today", "cryptocurrency bitcoin news",
            "forex market analysis", "federal reserve interest rate",
            "global economic outlook", "S&P 500 market update",
        ]

        jobs: List[tuple[str, str]] = []
        if lang in ("all", "cn"):
            jobs.extend(("cn", q) for q in cn_queries)
        if lang in ("all", "en"):
            jobs.extend(("en", q) for q in en_queries)

        def _run(lang_key: str, query: str) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            results = search.search(query, num_results=5, date_restrict="d1")
            for r in results:
                out.append({
                    "title": r.get("title", ""), "link": r.get("link", ""),
                    "snippet": r.get("snippet", ""), "source": r.get("source", ""),
                    "published": r.get("published", ""), "category": query, "lang": lang_key,
                })
            return out

        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(jobs)))) as pool:
            futures = {pool.submit(_run, lang_key, query): lang_key for lang_key, query in jobs}
            try:
                for fut in as_completed(futures, timeout=_NEWS_DEADLINE_SECONDS):
                    lang_key = futures[fut]
                    try:
                        result[lang_key].extend(fut.result())
                    except Exception:
                        pass
            except TimeoutError:
                logger.warning(
                    "news aggregation hit the %ss budget; returning partial results",
                    _NEWS_DEADLINE_SECONDS,
                )
                for fut in futures:
                    fut.cancel()
        logger.info(
            "news aggregation finished in %.1fs (cn=%d en=%d)",
            time.monotonic() - started, len(result["cn"]), len(result["en"]),
        )

        for lang_key in ["cn", "en"]:
            seen: set = set()
            unique = []
            for news in result[lang_key]:
                link = news.get("link", "")
                if link and link not in seen:
                    seen.add(link)
                    unique.append(news)
            result[lang_key] = unique[:15]

    except Exception as e:
        logger.error("Failed to fetch financial news: %s", e)

    return result


__all__ = ["fetch_financial_news", "get_economic_calendar", "get_economic_calendar_payload"]
