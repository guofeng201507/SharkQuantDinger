-- Reactivate curated crypto hot symbols that were deactivated by the
-- case-sensitive venue cleanup (seed rows use exchange='Binance' while the
-- cleanup whitelist was lowercase), which left the crypto hot list empty and
-- the trading/market pages without a default pair list.
--
-- The cleanup itself is fixed in init.sql / 20260711_crypto_catalog_six_venues.sql
-- (LOWER(exchange) NOT IN ...); this migration repairs the data that was
-- already deactivated. Idempotent: only touches still-deactivated hot rows.

UPDATE qd_market_symbols
SET is_active = 1
WHERE market = 'Crypto'
  AND is_hot = 1
  AND is_active = 0;
