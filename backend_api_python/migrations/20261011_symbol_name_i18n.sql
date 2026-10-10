-- Per-locale display names for market symbols (qd_market_symbols.name_i18n).
--
-- `name` stays the canonical stored name (Chinese for A-shares and some HK
-- listings); `name_i18n` carries per-locale overrides so the API can render a
-- symbol name in the caller's language. Same JSONB pattern as the indicator
-- marketplace (qd_indicator_codes.name_i18n).
--
-- Idempotent: only fills a locale when it is still empty, so re-runs and
-- manual edits are preserved.

ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS name_i18n JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "Kweichow Moutai"}'::jsonb
WHERE market = 'CNStock' AND symbol = '600519' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "China Merchants Bank"}'::jsonb
WHERE market = 'CNStock' AND symbol = '600036' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "Ping An Insurance"}'::jsonb
WHERE market = 'CNStock' AND symbol = '601318' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "China Yangtze Power"}'::jsonb
WHERE market = 'CNStock' AND symbol = '600900' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "Zijin Mining"}'::jsonb
WHERE market = 'CNStock' AND symbol = '601899' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "Wuliangye Yibin"}'::jsonb
WHERE market = 'CNStock' AND symbol = '000858' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "Midea Group"}'::jsonb
WHERE market = 'CNStock' AND symbol = '000333' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "BYD"}'::jsonb
WHERE market = 'CNStock' AND symbol = '002594' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "CATL"}'::jsonb
WHERE market = 'CNStock' AND symbol = '300750' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "Ping An Bank"}'::jsonb
WHERE market = 'CNStock' AND symbol = '000001' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "China Vanke"}'::jsonb
WHERE market = 'CNStock' AND symbol = '000002' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "Tencent Holdings"}'::jsonb
WHERE market = 'HKStock' AND symbol = '00700' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "Alibaba Group"}'::jsonb
WHERE market = 'HKStock' AND symbol = '09988' AND COALESCE(name_i18n->>'en-US', '') = '';
UPDATE qd_market_symbols
SET name_i18n = name_i18n || '{"en-US": "Xiaomi Group"}'::jsonb
WHERE market = 'HKStock' AND symbol = '01810' AND COALESCE(name_i18n->>'en-US', '') = '';
