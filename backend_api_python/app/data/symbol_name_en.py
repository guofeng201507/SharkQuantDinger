"""English display names for CN/HK symbols whose stored name is Chinese only.

`qd_market_symbols.name` holds the native (Chinese) name for A-share and some
Hong Kong listings. The API returns an English alias when the caller's UI
language is not Chinese, so an English interface never falls back to Chinese
names. This is a display alias only — the symbol itself never changes.

Per-locale names are stored durably on the symbol row in
`qd_market_symbols.name_i18n` (JSONB, the same pattern as the indicator
marketplace); this map is the seed/fallback for rows that have no localized
name yet. Extend the durable map in the database rather than this file.
"""
from __future__ import annotations

from typing import Optional

# key: (market, symbol) -> English display name
SYMBOL_NAME_EN: dict[tuple[str, str], str] = {
    # A-shares
    ("CNStock", "600519"): "Kweichow Moutai",
    ("CNStock", "600036"): "China Merchants Bank",
    ("CNStock", "601318"): "Ping An Insurance",
    ("CNStock", "600900"): "China Yangtze Power",
    ("CNStock", "601899"): "Zijin Mining",
    ("CNStock", "000858"): "Wuliangye Yibin",
    ("CNStock", "000333"): "Midea Group",
    ("CNStock", "002594"): "BYD",
    ("CNStock", "300750"): "CATL",
    ("CNStock", "000001"): "Ping An Bank",
    # Hong Kong (only rows stored with a Chinese name; the rest are already latin)
    ("HKStock", "00700"): "Tencent Holdings",
    ("HKStock", "09988"): "Alibaba Group",
    ("HKStock", "01810"): "Xiaomi Group",
}


def english_symbol_name(market: str, symbol: str) -> Optional[str]:
    """English alias for a symbol, or None when the stored name is already usable."""
    return SYMBOL_NAME_EN.get((str(market or "").strip(), str(symbol or "").strip().upper()))
