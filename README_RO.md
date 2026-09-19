# Agentic — Financial Research Analyst Agent

*[English version](README.md)*

O aplicație de cercetare financiară multi-agent: 11 agenți specialiști (pydantic-ai)
care acoperă fundamentale, tehnic, sentiment, risc, performanță, earnings și altele
pentru orice acțiune, susținută de MySQL, date de piață FMP/yfinance, și alegerea ta
între Ollama local sau Gemini pentru specialiștii care folosesc un LLM. UI în
Streamlit, backend în FastAPI.

A pornit ca replică adaptată a arhitecturii
[gsaini/financial-research-analyst-agent](https://github.com/gsaini/financial-research-analyst-agent)
(orchestrator + agenți specialiști); design-ul a divergat substanțial de atunci
(majoritatea specialiștilor sunt acum Python pur sau un singur apel LLM, nu o buclă
agentică de tool-uri — vezi "Cum funcționează" mai jos).

## Cerințe

- Python 3.13, venv la `.venv/`
- [Ollama](https://ollama.com) local, cu modelul de bază descărcat (`ollama pull qwen3.5:4b`), apoi construit modelul aplicației pornind de la acesta, cu o fereastră de context mai mare (implicit Ollama e 4096 tokeni, ceea ce se depășește odată ce un rezultat de la tool-ul RAG intră în prompt — vezi `llm.py` pentru detalii): `ollama create qwen3.5-4b-16k -f Modelfile.qwen3.5-4b-16k`. `OLLAMA_MODEL` din `.env` e implicit setat la acest tag derivat. Ales în locul lui `qwen2.5:14b-instruct` (mai mare) după o comparație directă (vezi nota din `llm.py`) — atât `qwen2.5:14b`, cât și `mistral:7b` au lăsat necompletate sau au inventat câmpuri din output-ul structurat; `qwen3.5:4b` nu, deși e cel mai mic dintre cele trei.
- Docker Desktop (pentru MySQL)
- O cheie API [Financial Modeling Prep](https://site.financialmodelingprep.com) (singura cheie strict necesară — tot restul din `.env.example` e opțional sau are o valoare implicită gratuită rezonabilă)

## Pornire

```powershell
# 0. Doar prima dată: copiază template-ul și completează-ți propriile chei
copy .env.example .env

# 1. MySQL
docker compose up -d

# 2. Migrații
.venv\Scripts\python.exe -m alembic upgrade head

# 3. API — într-un terminal
.venv\Scripts\python.exe -m uvicorn agentic.api.main:app --port 8000 --reload

# 4. Streamlit — în alt terminal
.venv\Scripts\python.exe -m streamlit run frontend\Home.py
```

Apoi deschide:
- API docs: http://localhost:8000/docs
- UI: http://localhost:8501

## Cum funcționează

Fiecare simbol are **un singur instantaneu live** în tabela `company_analysis` — un
rând identificat după ticker, care ține cel mai recent rezultat al fiecărui specialist
plus propria lui marcă de timp. Nu există coadă de job-uri: `GET
/api/v1/company/{symbol}` doar citește acel rând și răspunde instant. `POST
/api/v1/company/{symbol}/refresh` pornește în fundal doar specialiștii ceruți (via
FastAPI `BackgroundTasks`) și actualizează același rând pe măsură ce fiecare termină —
închiderea tab-ului sau navigarea în altă parte nu anulează nimic, iar la revenire se
vede orice s-a terminat între timp. Paginile Streamlit verifică actualizările printr-un
fragment ușor cu auto-refresh, nu o buclă blocantă.

Odată ce toți specialiștii de care are nevoie o pagină sunt proaspeți, un pas de
**orchestrator** (doar pe pagina Stock Analysis) face un apel LLM suplimentar peste
toate rezultatele lor, ca să semnaleze contradicții între specialiști (de exemplu un
trend tehnic optimist față de un trend de earnings în deteriorare) și să scrie o
sinteză cross-signal scurtă, împărțită într-o perspectivă pe termen scurt (1-3 luni) și
una pe termen lung (3-5 ani).

**ETF-urile și fondurile sunt detectate din start** (verificat o singură dată per
simbol, apoi cache-uit) — niciun specialist nu e construit pentru altceva decât
situațiile financiare proprii ale unei companii operaționale, deci nu rulează nimic
pentru un fond; UI-ul doar afișează un anunț în loc.

Fiecare specialist are propriul TTL de prospețime (câteva minute pentru date de preț
live, ore pentru lucruri ca metricile de risc, și o regulă de tipul "a raportat compania
ceva nou de la ultima verificare" pentru date derivate din filing-uri ca AFFO) — vezi
`FRESHNESS_SECONDS` și `is_expired()` din `orchestration.py`.

### Backend LLM per specialist

Doar 5 din cei 11 specialiști — plus pasul de cross-signal al orchestratorului —
folosesc un LLM (restul sunt Python/matematică pură: fără ambiguitate, nimic de
sintetizat). Fiecare poate rula independent pe Ollama local sau Gemini: setează
`{NUME}_LLM_BACKEND=gemini` în `.env` (sau `LLM_BACKEND=gemini` ca implicit global) ca
să schimbi local/gratuit cu cloud/rapid — vezi `.env.example` pentru suprascrierea
fiecărui specialist și `llm.py` pentru cum se rezolvă. Apelurile Gemini sunt limitate
la 5/minut ca să nu depășească limita per-minut a free tier-ului, dar limita
**zilnică** a free tier-ului e de doar ~20 cereri/model — nu există nicio soluție la
nivel de cod pentru asta, deci folosirea intensă a Gemini pe multe simboluri într-o
singură zi va lovi eventual un 429.

## Specialiști

| Specialist | Ce face | LLM? |
|---|---|---|
| Data Collector | Preț live, volum, capitalizare de piață | Nu |
| Technical | RSI/MACD/SMA/EMA/Bollinger Bands, clasificare de trend | Nu |
| Risk | VaR/CVaR (Monte Carlo), Altman Z-Score, Piotroski F-Score, îndatorare | Nu |
| Performance | Randamente (1lună/3luni/6luni/1an), Sharpe/Sortino, backtest-uri vs. benchmark | Nu |
| Earnings | Istoric surprize EPS/venituri, streak de beat-uri, schimbări de rating de la analiști, comparație cu peers | Nu |
| Financial Statements | Situații financiare standardizate (venit/bilanț/cash-flow), eficiență de capital (ROIC/WACC/EVA/DuPont), politică de capital return, segmentare | Nu |
| AFFO | Doar REIT-uri: Adjusted Funds From Operations extras din filing-uri 10-K | Da (extragere din filing) |
| Valuation | P/E, P/B, ROE, FCF/acțiune, fair value DCF, peers, interpretare a factorilor de risc din filing-uri SEC | Da (interpretare filing, doar dacă au fost ingerate filing-uri) |
| Sentiment | Tonul știrilor (scor VADER + sinteză LLM când semnalele sunt mixte) | Da |
| Earnings Call | Tonul conferinței, subiecte cheie, detectare de răspunsuri evazive | Da |
| Disruption | R&D/venituri și creștere vs. benchmark de sector, oportunități/amenințări competitive din știri recente | Da |

## Pagini

- **Stock Analysis** — imagine de ansamblu: card de identitate, matrice de semnale (un
  rând per specialist), sinteză cross-signal, și controalele de refresh pentru
  specialiștii de mai jos.
- **Fundamental Deep Dive** — Financial Statements + AFFO în detaliu complet.
- **Technical Charts**
- **Sentiment & News** — Sentiment + Earnings Call, plus fluxul global de știri de piață.
- **Valuation**
- **Market Disruption**
- **Earnings Comparison**
- **Risk Analysis**
- **Performance & Backtesting**
- **Watchlists** — creează/administrează liste de simboluri; o vedere de tip screener
  citește ce e deja cache-uit pentru fiecare simbol (trend tehnic, nivel de risc, zonă
  Altman) fără să declanșeze vreodată o analiză nouă doar pentru că un simbol e pe o
  listă.
- **Alerts** — vezi mai jos.

## Alerte

`11_Alerts.py` creează alerte de preț (`POST /api/v1/alerts` — simbol, `price_above`/`price_below`, prag) și afișează un flux live alimentat de `WS /api/v1/ws/alerts`. Fără broker/Redis: fiecare conexiune WebSocket deschisă rulează propria buclă de polling, verificând cotația live a fiecărei alerte active la fiecare 30s și trimițând un mesaj prima dată când se declanșează în cadrul acelei conexiuni — deci fluxul arată doar alertele care se declanșează cât timp pagina e deschisă.

## RAG (filings SEC)

Înainte ca specialistul Valuation să poată cita din filings, trebuie ingerat 10-K-ul unei companii:

```powershell
.venv\Scripts\python.exe -m agentic.rag.ingest --symbol AAPL
```

Necesită `SEC_EDGAR_CONTACT_EMAIL` în `.env` (SEC EDGAR cere un email de contact în User-Agent-ul descărcării). Fragmentele sunt transformate în embeddings local via Ollama (`OLLAMA_EMBED_MODEL`, implicit `nomic-embed-text` — `ollama pull nomic-embed-text` întâi) și stocate în `./chroma_data`. Dacă nu s-a ingerat nimic pentru un simbol, Valuation doar întoarce o listă `filing_citations` goală, nu eșuează.

## Variabile de mediu

Toată configurarea stă în `.env` (exclus din git, nu se comite niciodată).
`.env.example` e template-ul de referință — copiază-l în `.env` și completează-ți
propriile chei. E organizat pe numărul paginii, deci setările fiecărui specialist stau
lângă pagina care îl folosește. `FMP_KEY` e singura cheie strict necesară ca aplicația
să pornească; orice altă cheie de provider deblochează o sursă de date opțională sau
lasă un specialist să ruleze mai rapid pe Gemini în loc de Ollama local.

## Licență & scop

Licențiat MIT (vezi `LICENSE`) — dar construit și rulat pe baza mai multor API-uri
terțe ale căror planuri gratuite interzic explicit uzul de producție/comercial
(NewsAPI, GNews — vezi notele din `.env.example`). Acest proiect e gândit pentru uz
personal/local cu propriile chei API, nu ca produs redistribuibil construit pe acele
planuri gratuite.

## Contribuții

A pornit ca proiect personal, acum e public — contribuțiile sunt binevenite, câteva reguli simple:

- Deschide un issue sau un PR mic și focalizat pe `master`. Un singur subiect per PR e mai ușor de revizuit decât un pachet mare.
- Nu comite niciodată `.env` sau chei API reale. `.env.example` e template-ul — ține-l sincronizat dacă adaugi o variabilă nouă.
- Un specialist nou urmează tiparul existent: o funcție simplă, sau un singur apel LLM fără tool-uri pentru cazul rar care chiar are nevoie de unul (nu o buclă agentică) — înregistrat în dicționarul `SPECIALISTS` din `orchestration.py`, cu propria schemă în `schemas/` și, dacă are nevoie de o pagină, un fișier numerotat în `frontend/pages/`.
- Dacă schimbarea ta atinge documentația pentru utilizatori, actualizează `README.md` — nu e nevoie să atingi și `README_RO.md` sau să știi română ca să contribui; versiunea română e ținută sincronizată separat de maintainer.
- Comentariile din cod explică logica (o constrângere neevidentă, un workaround, sursa unei formule) — nu cum sau când a fost scris codul.

## Oprire

- Dacă API-ul/Streamlit-ul rulează într-un terminal vizibil: **Ctrl+C** în acel terminal.
- MySQL: `docker compose stop` (păstrează datele) sau `docker compose down` (șterge containerul, păstrează volumul cu datele).
- Dacă un proces a rămas pornit "detașat" (fără terminal la vedere) și nu știi PID-ul, găsește-l după port și oprește-l:

```powershell
Get-NetTCPConnection -LocalPort 8000,8501 -State Listen | Select-Object LocalPort, OwningProcess
Stop-Process -Id <OwningProcess> -Force
```

## Debugging fără API/UI

```powershell
.venv\Scripts\python.exe scripts\debug_run.py [SIMBOL]
```

Rulează fiecare specialist pentru un simbol (implicit `AAPL`) direct — fără HTTP, fără
DB — și tipărește rezultatul (sau eșecul) fiecăruia pe măsură ce termină.
