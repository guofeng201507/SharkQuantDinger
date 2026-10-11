# SharkQuant — Business Pitch

> Version: 2026-10-11 | Language: English | Companion deck: `SharkQuant_Pitch_EN.pptx`
> `[TBD: ...]` marks information only the founder can provide; the full list is in `FILL_IN.md`.

---

## 0. Executive Summary

**SharkQuant is an AI-native, all-in-one quantitative trading platform: market data → AI research → strategy authoring & backtesting → automated bot execution → live risk controls — in a single product. One retail trader can now run the workflow that used to require a small team.**

- **Product (live)**: running in production at shark.aiorz.cc — 39 feature pages, 7 asset classes (crypto, US equities, HK equities, FX, futures, A-shares, tokenized equities), 8 trading venues (Binance, OKX, Bitget, Bybit, Gate, HTX, IBKR, Alpaca), 222 built-in factors, 58 MCP (Model Context Protocol) tools for AI agents, AI output in 11 languages, bilingual (EN/中文) UI.
- **Model**: subscriptions ($19.9/mo · $199/yr · $499 lifetime) + usage credits (AI & backtests) + indicator-marketplace take rate + referral commissions. Payments (Stripe + stablecoins) are built in and await a merchant channel to be switched on.
- **Why now**: algorithmic trading grows at a 13.6% CAGR ($26.3B in 2026 → $64.3B by 2033); the AI-agent ecosystem exploded in 2026 (MCP servers grew from ~50 at launch to ~8,000–12,000 by Q2 2026), yet "letting an AI agent trade safely" has no standard answer — SharkQuant's Agent Gateway already answers it with paper-only defaults, scoped tokens, rate limits, and full audit trails.
- **Traction**: Aug–Oct 2026 — v5 distributed-architecture upgrade, full front-end replacement, bilingual rollout, security audit, stable production operation.
- **Raise**: [TBD: round / amount / valuation / equity]. Use of funds: R&D 45% / growth 30% / security & compliance 15% / reserve 10% (suggested split).

---

## 1. The Problem: Three Walls Between Retail Traders and Quant Trading

A retail trader who wants to trade systematically hits three disconnected walls:

| Stage | Status quo | Pain |
|---|---|---|
| **Data** | One app for charts, three more sites for macro/news/sentiment | Fragmented; cross-market comparison is nearly impossible |
| **Research** | Writing a strategy means Python + a framework + your own data pipeline; backtesting and execution tools don't talk to each other | Very high barrier; the chain breaks; most people write a strategy but never run it |
| **Execution** | Manual orders while watching charts; bot tools cover crypto only, or US stocks only | Emotional trading; no unified execution layer across markets |

Incumbents each own one slice: TradingView (charts), QuantConnect (engineer-grade engine), 3Commas/Composer (single-market automation). **Nobody has built the full loop from a retail trader's perspective.** With LLMs maturing in 2026, the first-order question became: *can AI flatten all three walls at once?*

**SharkQuant's answer: yes — by being AI-native, not AI-bolted-on.**

---

## 2. Solution: The Whole Quant Workflow in One Product

Six modules form a closed loop:

1. **Markets** — real-time multi-market quotes (5-second WebSocket refresh), candlesticks with MA/BOLL/MACD/RSI, sentiment strip (Fear & Greed / VIX / DXY), Global Market (indices, FX, crypto, commodities + heatmap + economic calendar), **Opportunity Radar** (rule-based whole-market scans).
2. **AI Research** — streaming AI chat with attachments, **Fast Analysis** (multi-source diagnosis of any instrument), AI reports (PDF export, shareable links), **Event Radar** (AI assesses news impact on your positions and watchlist).
3. **Strategy** — script library with online IDE, compile validation, versioning and community publishing; **AI strategy generation** (natural language → backtestable code); 222-factor library + factor research; universes; parameter optimization; per-strategy AI copilot.
4. **Backtest** — a real 6-month BTC dual-MA run produced **+34.99% return over 1,104 equity points**; full trade log, win rate, Sharpe, max drawdown, benchmark-relative metrics. (Screenshots in `assets/en/` use real backtest data.)
5. **Execution** — trading bots (templates + natural-language "AI Smart" creation), trading terminal (orders/close/cancel with confirmations), position & order mirrors, pending-order queue, **24/7 distributed strategy runtime** (leases, heartbeats, idempotency).
6. **Connectivity** — 8 venues (6 crypto exchanges + IBKR/Alpaca for US/HK equities and more); **Agent Gateway** — the whole platform exposed as 58 MCP tools callable by Cursor / Claude Code / Codex and other AI agents.
7. **A governed AI control plane (admin)** — all 31 AI skills and 66 tools are visible in-product: toggle each on/off, risk levels (read / write_draft / trading), read-only flags, renderable and auditable prompts, install/remove skills, and a one-click preflight (LLM · data sources · search · broker · credits). For teams and institutional users, AI capability is a **visible, controllable, auditable asset — not a black box**.

> **One-line definition: one person = a quant team.**

---

## 3. Market & Timing

### 3.1 Market size

- **Algorithmic trading**: $26.3B (2026) → $64.3B (2033), CAGR **13.6%** (Grand View Research); Mordor Intelligence sizes it at $20.23B (2026) → $29.54B (2031); Technavio projects +$23.9B growth over 2026–2030 at a 16.7% CAGR.
- **Online trading platforms**: $12.57B (2026) → $18.18B (2031), CAGR 7.66% (Mordor Intelligence); Precedence Research uses a broader $24.05B (2026) figure.
- **User base**: China's A-share market alone has **250M+ investor accounts** (>99% retail; ChinaClear 2025 annual report), with 4.6M new accounts opened in March 2026 alone; global retail investor counts are in the hundreds of millions.

SharkQuant targets the segment inside this crowd that is **willing to automate but lacks engineering power** — a high-value, high-retention niche that regulatory tightening and AI adoption are actively pushing toward paid software.

### 3.2 Why now

1. **AI-agent ecosystem explosion**: MCP servers grew from ~50 at launch (2024) to an estimated 8,000–12,000 by Q2 2026; "letting agents do the work" is the default enterprise-software theme of 2026.
2. **The agent safety gap is our differentiator**: industry surveys show 47–53% of organizations have had AI agents exceed permissions or cause incidents, and only ~23% have a formal agent-identity system. SharkQuant ships agent tokens + five scope classes + paper-only defaults + rate limits + full audit — **in the most sensitive domain ("let AI trade for me"), safety design *is* the product**.
3. **LLM cost curve**: inference costs keep falling, making "AI participates in every trading decision" viable inside a subscription price point.

---

## 4. Business Model

### 4.1 Revenue streams (all four already built into the product)

| Stream | Mechanics | Status |
|---|---|---|
| **Subscriptions** | $19.9/mo (500 credits) · $199/yr (8,000 credits, hero tier) · $499 lifetime (800 credits/mo) | Plans & billing page live (`/wallet`); awaiting payment channel |
| **Usage credits** | Backtest 30 credits/run, AI codegen 30, AI analysis/review 10, chat 5, event radar 5, AI decision filter 1… | Metering engine live |
| **Indicator marketplace take rate** | Users publish indicators/strategies; buyers pay credits; author share + platform fee (rate configurable) | Browse/purchase flow built; publishing & payouts follow the payment channel |
| **Referrals** | 100 signup credits, +50 per referral, 3-tier 10/5/3% commission, $10 withdrawal threshold | Implemented, off by default pending launch |

Real default limits: 5 running strategies on free tier, 10 on VIP; agent tokens default to 60 requests/minute.

### 4.2 Unit economics ([TBD: replace with real operating data])

- Paid conversion rate: [TBD]
- Monthly churn: [TBD]
- ARPU / average contract value: [TBD]
- Gross margin (net of LLM & data costs): [TBD]
- LTV / CAC: [TBD]

### 4.3 Pricing logic

Comparables: TradingView $12.95–59.95/mo (charts only), 3Commas $15–60/mo (crypto automation only), Composer $10–40/mo (US equities only). At $19.9/mo SharkQuant bundles **cross-market coverage + AI research + backtesting + automated execution** — an order of magnitude more surface area at the same price point. The $499 lifetime tier drives early cash flow and word of mouth.

---

## 5. Competitive Landscape

| Dimension | SharkQuant | TradingView | QuantConnect | 3Commas / Composer | JoinQuant / RiceQuant (CN) |
|---|---|---|---|---|---|
| Markets | Crypto / US / HK / FX / futures / A-shares (7 classes) | Global data (analysis-first) | US & futures leaning | Single-market automation | A-shares first |
| AI-native | ✅ research, generation, review, events — end to end | Partial (AI chart tools) | Partial | Minimal | Partial |
| Backtest + live in one | ✅ same script, backtest → bot execution | ❌ no execution | ✅ (engineer-oriented) | Weak backtests | Strong backtests, high live-trading barrier |
| AI-agent access (MCP) | ✅ 58 tools + scopes + paper-only + audit | ❌ | ❌ | ❌ | ❌ |
| Onboarding | Built for retail (in-app manual, bilingual) | Easy but analysis-only | Hard (coding required) | Medium | Hard (coding required) |
| Target user | Retail + semi-pro | All analysts | Quant engineers | Single-market automation users | CN quant crowd |

**Differentiation summary**: ① AI-native by design; ② one loop from research to execution; ③ the only platform that productized *safe* AI-agent access to trading; ④ multi-market + multi-language, built for cross-border growth.

---

## 6. Technology & Moat

**Architecture (verifiable facts)**:

- **Distributed runtime**: 18 container services (PostgreSQL, two Redis instances, Kafka, HTTP API, trading worker, strategy dispatcher/evaluator, audit worker, schedulers). PostgreSQL is the single source of truth; Kafka carries versioned events; strategy runtimes are physically separated from the HTTP tier.
- **Fund-safety design**: leases + heartbeats + fencing + idempotency keys prevent duplicate orders; agent live-trading requires four conditions to hold simultaneously (token scope, explicit authorization, risk acknowledgement, non-default mode); every action audited.
- **Multi-tenancy**: 4 roles + fine-grained permissions + tenant-scoped agent tokens; validated in production QA (48 routes × 2 languages).
- **AI**: pluggable LLM providers (OpenRouter et al.), visible model-level fallback; 11 output languages.
- **Security**: 2026-10-11 audit — 0 known vulnerabilities across 62 scanned dependencies, full security-header coverage, no business ports exposed, CSP staged. Details in `docs/security/`.
- **Scale path**: the V6 architecture RFC targets **20,000 users / 100,000 concurrent strategies**; the first horizontal-runtime module has shipped.
- **Self-hosting**: one-command installer + container images for data-sovereignty-sensitive users (unlocks studio/institutional niches).

**Moat logic**: full-loop products are hard (data licensing, cross-market symbology, order state machines, risk engines, audit) — that complexity is the barrier; an agent ecosystem on top of our MCP tools creates network effects; the multi-market data pipelines and 8 venue integrations are assets bought with time.

---

## 7. Milestones (Jul–Oct 2026)

| Date | Progress |
|---|---|
| ≤ Jul 2026 | v3 → v5.5 distributed upgrade (Kafka, isolated strategy runtimes, native exchange clients) |
| 2026-09-20 | AI entry-decision gate + billing (JEV); strategy evolution (TPE / grid / walk-forward) and signal virtual accounts |
| 2026-10-08 | Self-built front end P0–P2 shipped in a single day, containerized for production |
| 2026-10-09 | Rebranded as SharkQuant; user management, auth loop, indicator IDE and marketplace v1 |
| 2026-10-10 | Full i18n (1,823 keys EN/ZH 1:1), wallet/membership, live dashboards, Polymarket prediction markets; **production launch at shark.aiorz.cc** |
| 2026-10-11 | Request-language plumbing (X-App-Lang); hot-swappable in-app manual; 48-route bilingual QA sweep; security audit (0 dependency vulns) |

> The team compressed "engine upgrade + front-end rewrite + internationalization + security hardening" into three months — speed of execution is itself a milestone.

---

## 8. Go-To-Market

1. **Content & community**: out-of-the-box guides (built-in bilingual manual) with "let AI write your first strategy" as the hook; strategy community publishing is already shipped.
2. **Agent-ecosystem distribution**: our MCP tools put SharkQuant inside AI agents' toolboxes — Cursor/Claude users can call quotes, backtests and paper trading in natural language, which drives developer-led word of mouth.
3. **Marketplace flywheel**: authors publish → buyers pay → platform takes a fee → more authors. Comments, sales panels and versioning are live.
4. **Cross-border, multi-language**: bilingual UI + 11 AI output languages; beachhead in emerging-market semi-pro traders (SEA, Middle East).
5. **Referral loop**: three-tier commission parameters are built in, to be paired with credit incentives at launch.
6. [TBD: planned paid channels and budget]

---

## 9. Roadmap

**Shipped**: distributed runtime, cross-market data, end-to-end AI, backtest engine, bot execution, 8 venues, Agent Gateway, indicator marketplace (browse/purchase), wallet & plans, bilingual UI, in-app manual, security baseline.

**In progress (next 1–2 quarters)**:
- Turn on payment channels (Stripe + stablecoins) to activate subscriptions and marketplace settlement;
- Full marketplace publish/payout loop;
- MFA, OAuth, button-level permissions (enterprise security asks);
- Deeper mobile experience.

**Planned**: V6 horizontal scale (20k users / 100k strategies), portfolio rebalancing, pairs trading, dynamic universes, [TBD: 1–2 roadmap highlights the founder wants investors to remember].

---

## 10. Team

- Founder / CEO: [TBD: name, one-line background, prior achievements]
- CTO / Tech lead: [TBD]
- Core team: [TBD: product / quant research / growth]
- Advisors: [TBD, if any]

> Suggested angle: full-stack AI + financial-engineering background; **shipping from zero to production in three months** (see milestones) is the best résumé.

---

## 11. The Raise & Use of Funds

- **Round**: [TBD: angel / seed / pre-A]
- **Amount**: [TBD]
- **Valuation / equity**: [TBD]
- **Use of funds (suggested split)**:

| Use | % | Detail |
|---|---|---|
| R&D (AI + scale) | 45% | V6 horizontal scale, model-cost optimization, more markets/venues |
| Growth | 30% | Content marketing, agent-ecosystem evangelism, international acquisition |
| Security & compliance | 15% | Audits, data-source licensing, cross-border compliance |
| Reserve | 10% | Cash buffer |

- **12-month milestones**: [TBD: e.g., paying users / MRR / market coverage targets]

---

## 12. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Trust barrier ("will I let it trade for me?") | Paper-only by default; confirmations on live actions; 4-condition gate for agents; full audit trail |
| Data-source dependence & cost | Engineered multi-tier fallbacks; self-hosted caching; costs amortize with scale |
| Regulatory uncertainty (cross-border, AI advisory) | Positioned as software/tools, not advisory; no fund pooling, no discretionary management; compliance budget reserved |
| Incumbents extending (brokers, TradingView) | Lead with agent ecosystem + full-loop speed; self-hosting niche; community assets (strategies/indicators) compound first |
| Model-cost volatility | Multi-provider pluggability + model fallbacks; credit pricing passes usage costs through explicitly |

---

## 13. Disclaimer

This material is for evaluation by prospective investors only and is not an offer, solicitation, or recommendation of any security, fund, or investment product. Product screenshots come from the live system. Example backtest returns (+34.99% / +46.31%) are historical simulations, not indicative of future performance and not a guarantee. Crypto assets and leverage carry high risk. Commercial and financial figures are subject to due diligence.

---

## Appendix: Sources

1. Grand View Research — Algorithmic Trading Market (2026: $26.3B → 2033: $64.3B, CAGR 13.6%): https://www.grandviewresearch.com/industry-analysis/algorithmic-trading-market-report
2. Mordor Intelligence — Algorithmic Trading Market (2026: $20.23B → 2031: $29.54B): https://www.mordorintelligence.com/industry-reports/algorithmic-trading-market
3. Technavio — Algorithmic Trading Market 2026–2030 (+$23.9B, CAGR 16.7%): https://www.technavio.com/report/algorithmic-trading-market-industry-analysis
4. Mordor Intelligence — Online Trading Platform Market (2026: $12.57B → 2031: $18.18B, CAGR 7.66%): https://www.mordorintelligence.com/industry-reports/online-trading-platform-market
5. Precedence Research — Online Trading Platform Market (2026: $24.05B → 2035: $44.29B): https://www.precedenceresearch.com/online-trading-platform-market
6. Securities Times (证券时报) — China A-share investors top 250M (ChinaClear 2025 annual report): https://www.stcn.com/article/detail/3960120.html
7. 21st Century Business Herald — 4.6M new A-share accounts in March 2026: https://www.21jingji.com/article/20260404/herald/f2153bbe438e581e03d60fd8814fccf6.html
8. TradingView Pricing (Essential $12.95 / Plus $29.95 / Premium $59.95, annual): https://www.tradingview.com/pricing/
9. Composer — QuantConnect vs Composer (Advanced $10 / Pro $40 per month): https://www.composer.trade/learn/quantconnect-vs-composer-which-is-the-better-platform-to-create-a-stock-trading-bot
10. 3Commas Pricing (Starter $15 / Pro $40 / Expert $60): https://ideaproof.io/saas-pricing/product/3commas
11. presenc.ai — MCP Server Ecosystem Statistics 2026 (~8,000–12,000 servers, Q2 2026): https://presenc.ai/research/mcp-server-ecosystem-statistics-2026
12. Practical DevSecOps — MCP Security Statistics 2026 (47–53% of orgs hit agent permission incidents; ~23% have formal agent identity): https://www.practical-devsecops.com/mcp-security-statistics-2026-report/

(Product and architecture claims are individually verifiable in the repository and the live environment.)
