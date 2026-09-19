import logging

from fastapi import FastAPI

from agentic.api.routers import alerts, company, health, market_data, watchlists

# Root stays at WARNING so third-party INFO chatter (httpx logs every request)
# doesn't flood the console; only this project's own loggers go down to INFO.
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("agentic").setLevel(logging.INFO)

app = FastAPI(title="Financial Research Analyst Agent")
app.include_router(company.router, prefix="/api/v1")
app.include_router(watchlists.router, prefix="/api/v1")
app.include_router(market_data.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1")
