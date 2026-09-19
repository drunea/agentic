# Agentic — Financial Research Analyst Agent

*[Versiune în română](README_RO.md)*

A multi-agent financial research app: 11 specialist agents (pydantic-ai) covering
fundamentals, technicals, sentiment, risk, performance, earnings, and more for any
stock, backed by MySQL, FMP/yfinance market data, and your choice of local Ollama or
Gemini for the specialists that use an LLM. Streamlit UI, FastAPI backend.

Originally started as an adapted replica of
[gsaini/financial-research-analyst-agent](https://github.com/gsaini/financial-research-analyst-agent)'s
orchestrator + specialist-agent architecture; the design has since diverged
substantially (most specialists are now pure Python or a single LLM call rather than
an agentic tool-loop — see "How it works" below).

## Requirements

- Python 3.13, venv at `.venv/`
- [Ollama](https://ollama.com) running locally, with the base model pulled (`ollama pull qwen3.5:4b`), then the app's model built from it with a larger context window (Ollama's default 4096 tokens overflows once a RAG tool result is in the prompt — see `llm.py` for details): `ollama create qwen3.5-4b-16k -f Modelfile.qwen3.5-4b-16k`. `.env`'s `OLLAMA_MODEL` defaults to this derived tag. Chosen over the larger `qwen2.5:14b-instruct` after a direct comparison (see `llm.py`'s NOTE on model choice) — `qwen2.5:14b` and `mistral:7b` both unreliably dropped or fabricated tool-result fields in structured output, `qwen3.5:4b` didn't, despite being the smallest of the three.
- Docker Desktop (for MySQL)
- A [Financial Modeling Prep](https://site.financialmodelingprep.com) API key (the only required third-party key — everything else in `.env.example` is optional or has a sensible free default)

## Start

```powershell
# 0. First time only: copy the template and fill in your own keys
copy .env.example .env

# 1. MySQL
docker compose up -d

# 2. Migrations
.venv\Scripts\python.exe -m alembic upgrade head

# 3. API — in one terminal
.venv\Scripts\python.exe -m uvicorn agentic.api.main:app --port 8000 --reload

# 4. Streamlit — in another terminal
.venv\Scripts\python.exe -m streamlit run frontend\Home.py
```

Then open:
- API docs: http://localhost:8000/docs
- UI: http://localhost:8501

## How it works

Every symbol has **one live snapshot** in the `company_analysis` table — a row keyed
by ticker, holding each specialist's latest result plus its own timestamp. There's no
job queue: `GET /api/v1/company/{symbol}` just reads that row and returns instantly.
`POST /api/v1/company/{symbol}/refresh` backgrounds only the specialists you asked
for (via FastAPI `BackgroundTasks`) and updates the same row in place as each one
finishes — closing the tab or navigating away doesn't cancel anything, and coming
back later just shows whatever's landed so far. Streamlit pages poll for updates with
a lightweight auto-refreshing fragment, not a blocking loop.

Once every specialist a page needs is fresh, an **orchestrator** step (Stock Analysis
page only) makes one further LLM call over all their results, to flag contradictions
between specialists (e.g. a bullish technical trend against a deteriorating earnings
trend) and write a short cross-signal summary split into a short-term (1-3 months)
and long-term (3-5 years) view.

**ETFs and funds are detected up front** (checked once per symbol, cached) — none of
the specialists assume anything but an operating company's own financial statements,
so nothing runs for a fund; the UI just shows a notice instead.

Each specialist's freshness has its own TTL (a few minutes for live price data, hours
for things like risk metrics, and a "has this company reported since we last checked"
rule for filing-derived data like AFFO) — see `orchestration.py`'s `FRESHNESS_SECONDS`
and `is_expired()`.

### LLM backend per specialist

Only 5 of the 11 specialists — plus the orchestrator's cross-signal step — call an LLM
at all (the rest are pure Python/math: no ambiguity, nothing to synthesize). Each one
can independently run on local Ollama or Gemini: set `{NAME}_LLM_BACKEND=gemini` in
`.env` (or `LLM_BACKEND=gemini` as a global default) to trade local/free for
cloud/fast — see `.env.example` for every specialist's override and `llm.py` for how
it resolves. Gemini calls are throttled to 5/minute to stay under the free tier's RPM
cap, but the free tier's **daily** cap is only ~20 requests/model — there's no
code-level mitigation for that, so heavy Gemini use across many symbols in one day
will eventually 429.

## Specialists

| Specialist | What it does | LLM? |
|---|---|---|
| Data Collector | Live price, volume, market cap | No |
| Technical | RSI/MACD/SMA/EMA/Bollinger Bands, trend classification | No |
| Risk | Monte Carlo VaR/CVaR, Altman Z-Score, Piotroski F-Score, leverage | No |
| Performance | Returns (1mo/3mo/6mo/1y), Sharpe/Sortino, backtests vs. benchmark | No |
| Earnings | EPS/revenue surprise history, beat streak, analyst grade changes, peer comparison | No |
| Financial Statements | Standardized income/balance/cash-flow tables, capital efficiency (ROIC/WACC/EVA/DuPont), capital return policy, segmentation | No |
| AFFO | REIT-only: Adjusted Funds From Operations extracted from 10-K filings | Yes (filing extraction) |
| Valuation | P/E, P/B, ROE, FCF/share, DCF fair value, peers, SEC filing risk-factor interpretation | Yes (filing interpretation, only if filings ingested) |
| Sentiment | News headline tone (VADER score + LLM synthesis when signals are mixed) | Yes |
| Earnings Call | Transcript tone, key topics, evasive-answer detection | Yes |
| Disruption | R&D/revenue and growth vs. sector benchmark, competitive opportunities/threats from recent headlines | Yes |

## Pages

- **Stock Analysis** — overview: identity card, signal matrix (one row per specialist),
  cross-signal summary, and the refresh controls for the specialists below.
- **Fundamental Deep Dive** — Financial Statements + AFFO in full detail.
- **Technical Charts**
- **Sentiment & News** — Sentiment + Earnings Call, plus the global market-news feed.
- **Valuation**
- **Market Disruption**
- **Earnings Comparison**
- **Risk Analysis**
- **Performance & Backtesting**
- **Watchlists** — create/manage symbol lists; a screener view reads whatever's
  already cached for each symbol (technical trend, risk level, Altman zone) without
  ever triggering a fresh analysis just because a symbol is on a list.
- **Alerts** — see below.

## Alerts

`11_Alerts.py` creates price alerts (`POST /api/v1/alerts` — symbol, `price_above`/`price_below`, threshold) and shows a live feed fed by `WS /api/v1/ws/alerts`. No broker/Redis: each open WebSocket connection runs its own polling loop, checking every active alert's live quote every 30s and pushing a message the first time it triggers in that connection's lifetime — so the feed only shows alerts that fire while the page is open.

## RAG (SEC filings)

Before the Valuation specialist can cite filing excerpts, ingest a company's 10-K:

```powershell
.venv\Scripts\python.exe -m agentic.rag.ingest --symbol AAPL
```

Requires `SEC_EDGAR_CONTACT_EMAIL` in `.env` (SEC EDGAR requires a contact email in the download User-Agent). Chunks are embedded locally via Ollama (`OLLAMA_EMBED_MODEL`, default `nomic-embed-text` — `ollama pull nomic-embed-text` first) and stored in `./chroma_data`. If nothing has been ingested for a symbol, Valuation just returns an empty `filing_citations` list rather than failing.

## Environment variables

All configuration lives in `.env` (gitignored, never committed). `.env.example` is
the reference template — copy it to `.env` and fill in your own keys. It's organized
by page number, so each specialist's settings sit next to the page that uses them.
`FMP_KEY` is the only key you strictly need to get the app running; every other
provider key unlocks an optional data source or lets a specialist run faster on
Gemini instead of local Ollama.

## License & scope

MIT-licensed (see `LICENSE`) — but built and run against several third-party APIs
whose free tiers explicitly forbid production/commercial use (NewsAPI, GNews — see
the notes in `.env.example`). This project is intended for personal/local use with
your own API keys, not as a redistributable product built on those free tiers.

## Contributing

Started as a personal project, now public — contributions are welcome, a few simple rules:

- Open an issue or a small, focused PR against `master`. One topic per PR is easier to review than a large bundle.
- Never commit `.env` or real API keys. `.env.example` is the template — keep it in sync if you add a new variable.
- A new specialist follows the existing pattern: a plain function, or a single tool-free LLM call for the rare case that genuinely needs one (no agentic tool-loop) — registered in `orchestration.py`'s `SPECIALISTS` dict, with its own schema in `schemas/` and, if it needs a page, a numbered file in `frontend/pages/`.
- If your change touches user-facing docs, update `README.md` — no need to also touch `README_RO.md` or know Romanian to contribute; the Romanian version is kept in sync separately by the maintainer.
- Code comments explain the logic (a non-obvious constraint, a workaround, a formula's source) — not how or when the code was written.

## Stop

- If the API/Streamlit are running in a visible terminal: **Ctrl+C** in that terminal.
- MySQL: `docker compose stop` (keeps the data) or `docker compose down` (removes the container, keeps the data volume).
- If a process was left running "detached" (no visible terminal) and you don't know its PID, find it by port and stop it:

```powershell
Get-NetTCPConnection -LocalPort 8000,8501 -State Listen | Select-Object LocalPort, OwningProcess
Stop-Process -Id <OwningProcess> -Force
```

## Debugging without the API/UI

```powershell
.venv\Scripts\python.exe scripts\debug_run.py [SYMBOL]
```

Runs every specialist for one symbol (default `AAPL`) directly — no HTTP, no DB — and
prints each one's result (or failure) as it completes.
