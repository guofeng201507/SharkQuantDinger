# SharkQuant Current Architecture (Production)

Last verified: **2026-10-17** · Production release: **v5.5.5** · Diagram: [architecture-v5.svg](screenshots/architecture-v5.svg) / [PNG](screenshots/architecture-v5.png)

This document describes the architecture that is **actually running** in
production. It complements the target and contributor-oriented documents under
[`docs/architecture/`](architecture/README.md); when the two differ, this file is
the current-state reference.

## 1. Entry and frontends

```text
Internet
  → host nginx 1.24 (TLS, vhosts: sharkv2.conf / quantdinger.conf / quantdinger-legacy.conf)
      → sharkfe-web (self-built Vue SPA, nginx-unprivileged, 127.0.0.1:8888 → :8080)
          → sharkfe-bff (Node BFF, :8787)
              → quantdinger-backend:5000 (Flask + Gunicorn)
      → quantdinger-frontend (legacy UI, 127.0.0.1:8890) ──┐
      → quantdinger-mobile   (legacy mobile H5)            ├→ quantdinger-backend:5000
```

- **Primary UI**: the self-built `frontend/` (SharkQuant). `/api` and `/ws` go
  through the Node BFF, so rebuilding the backend does **not** require a BFF or
  web reload.
- **Legacy UI** stays deployed in parallel (`quantdinger-frontend`,
  `quantdinger-mobile`) and proxies `/api` directly to the backend. Its nginx
  caches the backend container IP, so run
  `docker exec quantdinger-frontend nginx -s reload` after recreating backend.
- **Human API**: Flask + Gunicorn in `quantdinger-backend`.
- **Agent access**: `/api/agent/v1` (Agent Gateway). MCP clients run the
  `quantdinger_mcp` package locally/remotely and call the gateway; MCP is not a
  separate production container.

## 2. Runtime ownership (actual containers)

| Container | Owns | Must not own |
| --- | --- | --- |
| `quantdinger-backend` | Auth, validation, queries, durable command submission | Trading loops, long schedules |
| `quantdinger-trading-worker-1` | Control/realtime runtimes, broker sessions, fenced order submission, position reconciliation, grid actors | Public HTTP, distributed bar evaluation |
| `quantdinger-strategy-dispatcher-worker-1` | Closed-bar consumption, strategy-shard batch publication | Strategy code execution, exchange orders |
| `quantdinger-strategy-evaluator-worker-1` | Distributed bar runtimes, inbox claims, leases, checkpoints, order intents | Direct exchange submission |
| `quantdinger-scheduler-worker` | Portfolio, deployment, payment, notification schedules | General Celery work |
| `quantdinger-kafka-audit-worker` | Event-contract and delivery audit | Strategy decisions, orders |
| `quantdinger-celery-worker` / `-beat` | Finite, serializable, retryable jobs and their schedule | Persistent trading runtimes |
| `quantdinger-migration` (one-shot) | Ordered schema updates | Concurrent API serving |
| `quantdinger-kafka-init` (one-shot) | Versioned topic creation | Runtime event processing |
| `quantdinger-env-sync` (one-shot) | Root `.env` synchronization for v5.5+ | Business logic |

Exchange-native flat closes, position-ownership health, and the OKX 59669 retry
are implemented inside the trading/pending-order path. Operational semantics and
the three safety switches are documented in
[Live-trading safety](trading/LIVE_TRADING_SAFETY.md).

## 3. State, messaging, and integrations

- **PostgreSQL 18.3** — durable source of truth (commands, leases, heartbeats,
  audit records, event inboxes, actors, strategies, trading state).
- **Redis 7.4 ×2** — `quantdinger-redis` (evictable cache) and
  `quantdinger-redis-jobs` (Celery broker/results, AOF + `noeviction`).
- **Kafka 4.3.1** — ordered inter-process event backbone
  (`qd.market.bar.closed.v1`, `qd.strategy.evaluate.v1`, `qd.order.intent.v1`,
  `qd.order.event.v1`, `qd.runtime.dlq.v1`, `qd.strategy.lifecycle.v1`).
- **SearXNG** — self-hosted search/news source used by the news pipeline. It is
  not part of `docker-compose.yml` and is started separately on the host.
- **Market data** — venue-native OHLCV/quotes via the shared market-data router
  (CCXT/native clients; Yahoo/Nasdaq/yfinance/Finnhub for US equities).
- **AI** — multi-provider LLM layer (OpenRouter and compatible providers) plus
  optional JEV event filtering; factor research itself does not call an LLM.

## 4. Deployment provenance

- Single-host Docker Compose.
- `quantdinger-backend:local` and `sharkfe-web:*` are **built locally**;
  the legacy `quantdinger-frontend` / `quantdinger-mobile` images come from GHCR.
- Root `.env` is the configuration source; `env-sync` is a one-shot service.
- Production code is tracked by `git pull --ff-only` in `/root/QuantDinger`.

## 5. Observability (current state)

- JSON logs with request IDs and process roles; a metrics endpoint exists.
- **Prometheus, Grafana, and Alertmanager are not deployed.** The architecture
  diagram marks dashboards as optional; do not assume scraped metrics.
- Health checks: container health probes, `/api/health`, and worker heartbeats in
  `qd_worker_heartbeats`.

## 6. Verified version matrix

| Component | Version |
| --- | --- |
| PostgreSQL | 18.3 (`postgres:18.3-alpine`) |
| Redis | 7.4.11 (`redis:7-alpine`) |
| Kafka | 4.3.1 (`apache/kafka:4.3.1`) |
| Python | 3.12.15 |
| TA-Lib | 0.8.1 |
| litellm | 1.104.x |
| pandas | 3.0.x |
| Legacy frontend/mobile | `ghcr.io/openbyteinc/quantdinger-*:v5.5.4` |
| Self-built frontend | `sharkfe-web:20261017c` + `sharkfe-bff:20261011u` |

## 7. How to verify this document

```bash
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
docker compose config --services
docker exec quantdinger-db psql -U quantdinger -d quantdinger -tAc 'select version()'
docker exec quantdinger-backend python -V
systemctl is-active nginx && nginx -v
docker ps -a --format '{{.Names}}' | grep -iE 'prometheus|grafana|alertmanager' || echo 'none'
```

## 8. Related documents

- [Architecture overview](architecture/README.md) — process ownership and state rules
- [Backend architecture](architecture/ARCHITECTURE.md) — package boundaries
- [Module boundaries](architecture/MODULE_BOUNDARIES.md)
- [Concurrency model](architecture/CONCURRENCY_MODEL.md)
- [Strategy lifecycle](architecture/STRATEGY_LIFECYCLE.md)
- [Live-trading safety](trading/LIVE_TRADING_SAFETY.md)
- [Frontend deployment](deployment/FRONTEND_DEPLOYMENT_EN.md)
- [Distributed runtime scaling](deployment/DISTRIBUTED_RUNTIME_SCALING.md)
