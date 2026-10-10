"""Trading opportunity scanners across markets."""
from __future__ import annotations

import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests

from app.utils.logger import get_logger
from app.data.symbol_name_en import english_symbol_name
from app.data_providers import get_cached, set_cached, safe_float
from app.data_providers.crypto import fetch_crypto_prices
from app.data_providers.forex import fetch_forex_pairs

logger = get_logger(__name__)


def _is_en(lang: str) -> bool:
    """True for any non-Chinese UI language (see app.utils.language)."""
    return not str(lang or "").lower().startswith("zh")


# Bilingual copy for the generated `reason` text: key -> (zh, en) format string.
_REASONS = {
    "crypto_overbought": ("24h涨幅{pct:.1f}%，7日涨幅{p7:.1f}%，短期超买风险",
                          "24h {pct:+.1f}%, 7d {p7:+.1f}% — short-term overbought risk"),
    "crypto_bullish": ("24h涨幅{pct:.1f}%，上涨动能强劲", "24h {pct:+.1f}% — strong upward momentum"),
    "crypto_oversold": ("24h跌幅{pct:.1f}%，可能超卖反弹", "24h {pct:.1f}% — possibly oversold, watch for a bounce"),
    "crypto_bearish": ("24h跌幅{pct:.1f}%，下跌趋势明显", "24h {pct:.1f}% — clear downtrend"),
    "stock_overbought": ("日涨幅{pct:.1f}%，短期涨幅较大，注意回调风险",
                         "Up {pct:.1f}% today — extended, watch for a pullback"),
    "stock_bullish": ("日涨幅{pct:.1f}%，上涨动能强劲", "Up {pct:.1f}% today — strong momentum"),
    "stock_oversold": ("日跌幅{pct:.1f}%，可能超卖反弹", "Down {pct:.1f}% today — possibly oversold"),
    "stock_bearish": ("日跌幅{pct:.1f}%，下跌趋势明显", "Down {pct:.1f}% today — clear downtrend"),
    "local_overbought": ("{mkt}日涨幅{pct:.1f}%，短期涨幅较大，注意回调风险",
                         "{mkt} up {pct:.1f}% today — extended, watch for a pullback"),
    "local_bullish": ("{mkt}日涨幅{pct:.1f}%，上涨动能较强", "{mkt} up {pct:.1f}% today — solid momentum"),
    "local_bullish_mild": ("{mkt}日涨幅{pct:.1f}%，温和上涨", "{mkt} up {pct:.1f}% today — mild advance"),
    "local_oversold": ("{mkt}日跌幅{pct:.1f}%，可能超卖反弹", "{mkt} down {pct:.1f}% today — possibly oversold"),
    "local_bearish": ("{mkt}日跌幅{pct:.1f}%，下跌趋势明显", "{mkt} down {pct:.1f}% today — clear downtrend"),
    "local_bearish_mild": ("{mkt}日跌幅{pct:.1f}%，温和下跌", "{mkt} down {pct:.1f}% today — mild decline"),
    "local_range": ("{mkt}{name}窄幅震荡({pct:+.1f}%)，等待方向选择",
                    "{mkt} {name} is range-bound ({pct:+.1f}%) — waiting for direction"),
    "forex_overbought": ("日涨幅{pct:.2f}%，汇率波动剧烈，注意回调",
                         "Up {pct:.2f}% today — volatile, watch for a pullback"),
    "forex_bullish": ("日涨幅{pct:.2f}%，上涨动能较强", "Up {pct:.2f}% today — solid momentum"),
    "forex_oversold": ("日跌幅{pct:.2f}%，汇率波动剧烈，可能反弹",
                       "Down {pct:.2f}% today — volatile, possible bounce"),
    "forex_bearish": ("日跌幅{pct:.2f}%，下跌趋势明显", "Down {pct:.2f}% today — clear downtrend"),
}


def _reason(key: str, lang: str, **kw) -> str:
    zh, en = _REASONS[key]
    return (en if _is_en(lang) else zh).format(**kw)


# ---------------------------------------------------------------------------
# Price fetchers for opportunity scanning
# ---------------------------------------------------------------------------

def _fetch_yahoo_chart_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """US spot quote via Yahoo chart API — lighter than yfinance batch calls."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
            params={"interval": "1d", "range": "5d"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; QuantDinger/1.0)"},
            timeout=10,
        )
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        price = safe_float(meta.get("regularMarketPrice") or meta.get("previousClose"))
        prev = safe_float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
        if price <= 0:
            return None
        change_pct = ((price - prev) / prev * 100.0) if prev > 0 else 0.0
        return {
            "last": price,
            "changePercent": round(change_pct, 2),
            "previousClose": prev,
        }
    except Exception as e:
        logger.debug("Yahoo chart quote failed for %s: %s", sym, e)
        return None


def _fetch_stooq_us_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """US spot quote via Stooq (works when Yahoo/yfinance are blocked in Docker)."""
    sym = f"{(symbol or '').strip().lower()}.us"
    if not sym or sym == ".us":
        return None
    try:
        resp = requests.get(
            "https://stooq.com/q/l/",
            params={"s": sym, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; QuantDinger/1.0)"},
            timeout=8,
        )
        resp.raise_for_status()
        lines = [ln for ln in resp.text.strip().splitlines() if ln and not ln.startswith("Symbol")]
        if not lines:
            return None
        parts = lines[-1].split(",")
        if len(parts) < 7:
            return None
        open_px = safe_float(parts[3])
        close_px = safe_float(parts[6])
        if close_px <= 0:
            return None
        base = open_px if open_px > 0 else close_px
        change_pct = ((close_px - open_px) / base * 100.0) if base > 0 else 0.0
        return {"last": close_px, "changePercent": round(change_pct, 2)}
    except Exception as e:
        logger.debug("Stooq quote failed for %s: %s", symbol, e)
        return None


def _fetch_single_local_stock_quote(market: str, item: Dict[str, Any], *, fast: bool = False) -> Optional[Dict[str, Any]]:
    """Fetch one US/CN/HK stock quote row."""
    from app.data.symbol_name_en import english_symbol_name
    from app.data_sources import DataSourceFactory
    from app.services.symbol_name import resolve_symbol_name

    m = str(market or "").strip()
    symbol = str((item or {}).get("symbol") or "").strip()
    if not symbol:
        return None

    last = 0.0
    change_pct = 0.0
    if m == "USStock":
        yahoo = _fetch_yahoo_chart_quote(symbol)
        if yahoo:
            last = safe_float(yahoo.get("last"))
            change_pct = safe_float(yahoo.get("changePercent"))
        if last <= 0:
            stooq = _fetch_stooq_us_quote(symbol)
            if stooq:
                last = safe_float(stooq.get("last"))
                change_pct = safe_float(stooq.get("changePercent"))
        if last <= 0 and not fast:
            try:
                from app.services.kline import KlineService
                row = KlineService().get_realtime_price(m, symbol)
                last = safe_float(row.get("price"))
                change_pct = row.get("changePercent")
                if change_pct is None:
                    prev_close = safe_float(row.get("previousClose"))
                    change_pct = ((last - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0
            except Exception as e:
                logger.debug("Kline realtime price failed for %s:%s: %s", m, symbol, e)
    else:
        source = DataSourceFactory.get_source(m)
        ticker = source.get_ticker(symbol) or {}
        last = safe_float(ticker.get("last") or ticker.get("close") or ticker.get("price"))
        change_pct = ticker.get("changePercent")
        if change_pct is None:
            prev_close = safe_float(ticker.get("previousClose"))
            change_pct = ((last - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0

    if last <= 0:
        return None
    return {
        "symbol": symbol,
        "name": (item.get("name") or resolve_symbol_name(m, symbol) or symbol).strip(),
        "name_en": (item.get("name_en") or english_symbol_name(m, symbol) or "").strip() or None,
        "price": round(last, 4 if m != "USStock" else 2),
        "change": round(safe_float(change_pct), 2),
        "market": m,
    }


def fetch_stock_opportunity_prices() -> List[Dict[str, Any]]:
    """Fetch popular US stock prices for opportunity scanning."""
    return fetch_local_stock_opportunity_prices("USStock", limit=15)


def fetch_local_stock_opportunity_prices(market: str, limit: int = 15, *, fast: bool = False) -> List[Dict[str, Any]]:
    """Fetch US/CN/HK stock prices for opportunity scanning and heatmaps."""
    m = str(market or "").strip()
    if m not in ("CNStock", "HKStock", "USStock"):
        return []

    _FALLBACK_SYMBOLS = {
        "USStock": [
            {"symbol": "AAPL", "name": "Apple"}, {"symbol": "MSFT", "name": "Microsoft"},
            {"symbol": "GOOGL", "name": "Alphabet"}, {"symbol": "AMZN", "name": "Amazon"},
            {"symbol": "TSLA", "name": "Tesla"}, {"symbol": "NVDA", "name": "NVIDIA"},
            {"symbol": "META", "name": "Meta"}, {"symbol": "NFLX", "name": "Netflix"},
            {"symbol": "AMD", "name": "AMD"}, {"symbol": "CRM", "name": "Salesforce"},
            {"symbol": "COIN", "name": "Coinbase"}, {"symbol": "JPM", "name": "JPMorgan"},
            {"symbol": "V", "name": "Visa"}, {"symbol": "INTC", "name": "Intel"},
            {"symbol": "PLTR", "name": "Palantir"}, {"symbol": "ORCL", "name": "Oracle"},
            {"symbol": "QCOM", "name": "Qualcomm"},
        ],
        "CNStock": [
            {"symbol": "600519", "name": "贵州茅台", "name_en": "Kweichow Moutai"}, {"symbol": "000001", "name": "平安银行", "name_en": "Ping An Bank"},
            {"symbol": "300750", "name": "宁德时代", "name_en": "CATL"}, {"symbol": "601318", "name": "中国平安", "name_en": "Ping An Insurance"},
            {"symbol": "600036", "name": "招商银行", "name_en": "China Merchants Bank"}, {"symbol": "002594", "name": "比亚迪", "name_en": "BYD"},
            {"symbol": "600276", "name": "恒瑞医药", "name_en": "Hengrui Pharmaceuticals"}, {"symbol": "601899", "name": "紫金矿业", "name_en": "Zijin Mining"},
            {"symbol": "000858", "name": "五粮液", "name_en": "Wuliangye Yibin"}, {"symbol": "000333", "name": "美的集团", "name_en": "Midea Group"},
            {"symbol": "600900", "name": "长江电力", "name_en": "China Yangtze Power"}, {"symbol": "601398", "name": "工商银行", "name_en": "ICBC"},
            {"symbol": "600030", "name": "中信证券", "name_en": "CITIC Securities"}, {"symbol": "300059", "name": "东方财富", "name_en": "East Money"},
            {"symbol": "603259", "name": "药明康德", "name_en": "WuXi AppTec"}, {"symbol": "002475", "name": "立讯精密", "name_en": "Luxshare Precision"},
            {"symbol": "600887", "name": "伊利股份", "name_en": "Yili"}, {"symbol": "000568", "name": "泸州老窖", "name_en": "Luzhou Laojiao"},
            {"symbol": "601012", "name": "隆基绿能", "name_en": "LONGi Green Energy"}, {"symbol": "002415", "name": "海康威视", "name_en": "Hikvision"},
        ],
        "HKStock": [
            {"symbol": "00700", "name": "腾讯控股", "name_en": "Tencent Holdings"}, {"symbol": "09988", "name": "阿里巴巴-W", "name_en": "Alibaba Group"},
            {"symbol": "03690", "name": "美团-W", "name_en": "Meituan"}, {"symbol": "01810", "name": "小米集团-W", "name_en": "Xiaomi Group"},
            {"symbol": "01299", "name": "友邦保险", "name_en": "AIA Group"}, {"symbol": "00939", "name": "建设银行", "name_en": "China Construction Bank"},
            {"symbol": "02318", "name": "中国平安", "name_en": "Ping An Insurance"}, {"symbol": "09618", "name": "京东集团-SW", "name_en": "JD.com"},
            {"symbol": "09888", "name": "百度集团-SW", "name_en": "Baidu"}, {"symbol": "01024", "name": "快手-W", "name_en": "Kuaishou"},
            {"symbol": "02015", "name": "理想汽车-W", "name_en": "Li Auto"}, {"symbol": "09868", "name": "小鹏汽车-W", "name_en": "XPeng"},
            {"symbol": "00388", "name": "香港交易所", "name_en": "HKEX"}, {"symbol": "02269", "name": "药明生物", "name_en": "WuXi Biologics"},
            {"symbol": "00005", "name": "汇丰控股", "name_en": "HSBC Holdings"}, {"symbol": "01398", "name": "工商银行", "name_en": "ICBC"},
            {"symbol": "00883", "name": "中国海洋石油", "name_en": "CNOOC"},
        ],
    }

    try:
        from app.data.market_symbols_seed import get_hot_symbols

        symbols = get_hot_symbols(m, limit=max(int(limit or 15), 1)) or []
        fallback = _FALLBACK_SYMBOLS.get(m, [])
        seen = set()
        merged = []
        for item in list(symbols) + list(fallback):
            sym = str((item or {}).get("symbol") or "").strip()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            merged.append(item)
        # Pull a few extra symbols so partial upstream failures still yield `limit` rows.
        fetch_count = max(int(limit or 15), 1) + 4
        items = merged[:fetch_count]
        if not items:
            return []

        result: List[Dict[str, Any]] = []
        if m in ("USStock", "HKStock", "CNStock") and len(items) > 1:
            workers = min(8, len(items))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_fetch_single_local_stock_quote, m, item, fast=fast) for item in items]
                for fut in as_completed(futures):
                    try:
                        row = fut.result()
                        if row:
                            result.append(row)
                    except Exception as e:
                        logger.debug("Parallel stock quote failed for %s: %s", m, e)
            return result[:max(int(limit or 15), 1)]

        for item in items:
            try:
                row = _fetch_single_local_stock_quote(m, item, fast=fast)
                if row:
                    result.append(row)
            except Exception as e:
                logger.debug("Failed to fetch %s opportunity price %s: %s", m, item.get("symbol"), e)
        return result[:max(int(limit or 15), 1)]
    except Exception as e:
        logger.error("Failed to fetch %s opportunity prices: %s", m, e)
        return []


# ---------------------------------------------------------------------------
# Opportunity analysers
# ---------------------------------------------------------------------------

def analyze_opportunities_crypto(opportunities: list, lang: str = "zh-CN"):
    """Scan crypto market for trading opportunities."""
    crypto_data = get_cached("crypto_prices")
    if not crypto_data:
        crypto_data = fetch_crypto_prices()
        if crypto_data:
            set_cached("crypto_prices", crypto_data)
    if not crypto_data:
        logger.warning("analyze_opportunities_crypto: No crypto data available")
        return

    for coin in (crypto_data or [])[:20]:
        change = safe_float(coin.get("change_24h", 0))
        change_7d = safe_float(coin.get("change_7d", 0))
        symbol = coin.get("symbol", "")
        name = coin.get("name", "")
        price = safe_float(coin.get("price", 0))

        signal = strength = reason = None
        impact = "neutral"

        if change > 15:
            signal, strength = "overbought", "strong"
            reason = _reason("crypto_overbought", lang, pct=change, p7=change_7d)
            impact = "bearish"
        elif change > 5:
            signal, strength = "bullish_momentum", "medium"
            reason = _reason("crypto_bullish", lang, pct=change)
            impact = "bullish"
        elif change < -15:
            signal, strength = "oversold", "strong"
            reason = _reason("crypto_oversold", lang, pct=abs(change))
            impact = "bullish"
        elif change < -5:
            signal, strength = "bearish_momentum", "medium"
            reason = _reason("crypto_bearish", lang, pct=abs(change))
            impact = "bearish"

        if signal:
            opportunities.append({
                "symbol": symbol, "name": name, "price": price,
                "change_24h": change, "change_7d": change_7d,
                "signal": signal, "strength": strength, "reason": reason,
                "impact": impact, "market": "Crypto", "timestamp": int(_time.time()),
            })


def analyze_opportunities_stocks(opportunities: list, lang: str = "zh-CN"):
    """Scan US stocks for trading opportunities."""
    stock_data = get_cached("stock_opportunity_prices")
    if not stock_data:
        stock_data = fetch_stock_opportunity_prices()
        if stock_data:
            set_cached("stock_opportunity_prices", stock_data, 3600)
    if not stock_data:
        logger.warning("analyze_opportunities_stocks: No stock data available")
        return

    for stock in (stock_data or []):
        change = safe_float(stock.get("change", 0))
        symbol, name, price = stock.get("symbol", ""), stock.get("name", ""), safe_float(stock.get("price", 0))

        signal = strength = reason = None
        impact = "neutral"

        if change > 5:
            signal, strength = "overbought", "strong"
            reason = _reason("stock_overbought", lang, pct=change); impact = "bearish"
        elif change > 2:
            signal, strength = "bullish_momentum", "medium"
            reason = _reason("stock_bullish", lang, pct=change); impact = "bullish"
        elif change < -5:
            signal, strength = "oversold", "strong"
            reason = _reason("stock_oversold", lang, pct=abs(change)); impact = "bullish"
        elif change < -2:
            signal, strength = "bearish_momentum", "medium"
            reason = _reason("stock_bearish", lang, pct=abs(change)); impact = "bearish"

        if signal:
            opportunities.append({
                "symbol": symbol, "name": name, "price": price,
                "change_24h": change, "signal": signal, "strength": strength,
                "reason": reason, "impact": impact, "market": "USStock",
                "timestamp": int(_time.time()),
            })


def analyze_opportunities_local_stocks(opportunities: list, market: str, lang: str = "zh-CN"):
    """Scan CN/HK stocks for trading opportunities."""
    m = str(market or "").strip()
    if m not in ("CNStock", "HKStock"):
        return

    cache_key = "cn_stock_opportunity_prices" if m == "CNStock" else "hk_stock_opportunity_prices"
    stock_data = get_cached(cache_key)
    if not stock_data:
        stock_data = fetch_local_stock_opportunity_prices(m, limit=25)
        if stock_data:
            set_cached(cache_key, stock_data, 3600)
    if not stock_data:
        logger.warning("analyze_opportunities_local_stocks: No %s data available", m)
        return

    if m == "CNStock":
        strong_th, medium_th, mild_th = 5.0, 2.0, 1.0
    else:
        strong_th, medium_th, mild_th = 4.0, 1.5, 0.8
    market_cn = ("A-shares" if m == "CNStock" else "HK stocks") if _is_en(lang) else ("A股" if m == "CNStock" else "港股")

    for stock in stock_data:
        change = safe_float(stock.get("change", 0))
        symbol, name, price = stock.get("symbol", ""), stock.get("name", ""), safe_float(stock.get("price", 0))
        # CN/HK rows carry the native Chinese name; resolve the English alias here so
        # rows cached before the alias existed are covered too.
        if _is_en(lang):
            name = english_symbol_name(m, symbol) or stock.get("name_en") or name
        abs_change = abs(change)

        signal = strength = reason = None
        impact = "neutral"

        if change > strong_th:
            signal, strength = "overbought", "strong"
            reason = _reason("local_overbought", lang, mkt=market_cn, pct=change); impact = "bearish"
        elif change > medium_th:
            signal, strength = "bullish_momentum", "medium"
            reason = _reason("local_bullish", lang, mkt=market_cn, pct=change); impact = "bullish"
        elif change > mild_th:
            signal, strength = "bullish_momentum", "weak"
            reason = _reason("local_bullish_mild", lang, mkt=market_cn, pct=change); impact = "bullish"
        elif change < -strong_th:
            signal, strength = "oversold", "strong"
            reason = _reason("local_oversold", lang, mkt=market_cn, pct=abs_change); impact = "bullish"
        elif change < -medium_th:
            signal, strength = "bearish_momentum", "medium"
            reason = _reason("local_bearish", lang, mkt=market_cn, pct=abs_change); impact = "bearish"
        elif change < -mild_th:
            signal, strength = "bearish_momentum", "weak"
            reason = _reason("local_bearish_mild", lang, mkt=market_cn, pct=abs_change); impact = "bearish"
        elif abs_change <= mild_th:
            signal, strength = "consolidation", "weak"
            reason = _reason("local_range", lang, mkt=market_cn, name=name, pct=change); impact = "neutral"

        if signal:
            opportunities.append({
                "symbol": symbol, "name": name, "price": price,
                "change_24h": change, "signal": signal, "strength": strength,
                "reason": reason, "impact": impact, "market": m,
                "timestamp": int(_time.time()),
            })


def analyze_opportunities_forex(opportunities: list, lang: str = "zh-CN"):
    """Scan forex pairs for trading opportunities."""
    forex_data = get_cached("forex_pairs")
    if not forex_data:
        forex_data = fetch_forex_pairs()
        if forex_data:
            set_cached("forex_pairs", forex_data, 3600)
    if not forex_data:
        logger.warning("analyze_opportunities_forex: No forex data available")
        return

    for pair in (forex_data or []):
        change = safe_float(pair.get("change", 0))
        symbol = pair.get("symbol", pair.get("name", ""))
        name = (pair.get("name") or pair.get("name_cn") or "") if _is_en(lang) else (pair.get("name_cn") or pair.get("name") or "")
        price = safe_float(pair.get("price", 0))

        signal = strength = reason = None
        impact = "neutral"

        if change > 1.5:
            signal, strength = "overbought", "strong"
            reason = _reason("forex_overbought", lang, pct=change); impact = "bearish"
        elif change > 0.5:
            signal, strength = "bullish_momentum", "medium"
            reason = _reason("forex_bullish", lang, pct=change); impact = "bullish"
        elif change < -1.5:
            signal, strength = "oversold", "strong"
            reason = _reason("forex_oversold", lang, pct=abs(change)); impact = "bullish"
        elif change < -0.5:
            signal, strength = "bearish_momentum", "medium"
            reason = _reason("forex_bearish", lang, pct=abs(change)); impact = "bearish"

        if signal:
            opportunities.append({
                "symbol": symbol, "name": name, "price": price,
                "change_24h": change, "signal": signal, "strength": strength,
                "reason": reason, "impact": impact, "market": "Forex",
                "timestamp": int(_time.time()),
            })

