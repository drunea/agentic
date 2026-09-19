from pydantic import BaseModel, Field


class SpecialistView(BaseModel):
    status: str  # "never_run" | "pending" | "running" | "done" | "error"
    result: dict | None = None
    error: str | None = None
    updated_at: str | None = None
    is_expired: bool


class OrchestratorView(BaseModel):
    status: str = "never_run"  # "never_run" | "running" | "done" | "error"
    contradictions: list[dict] = Field(default_factory=list)
    summary: str | None = None
    error: str | None = None
    updated_at: str | None = None


class CompanyAnalysisView(BaseModel):
    symbol: str
    specialists: dict[str, SpecialistView]
    orchestrator: OrchestratorView | None = None
    # None until the first refresh attempt checks it (see
    # orchestration.py::get_symbol_kind) — "etf"/"fund" means no specialist
    # has run or ever will for this symbol; the frontend shows a plain
    # message instead of the specialist grid once this is known.
    symbol_kind: str | None = None
    # Cached alongside symbol_kind (same profile call) — company name,
    # exchange, sector, industry, description. None until first checked.
    identity: dict | None = None
    # True while a refresh_company() background task is in flight for this
    # symbol, from ANY page — every "Analyze"/"Analyze selected" button
    # reads this and disables itself, so two pages can't trigger
    # overlapping refreshes for the same symbol. See
    # repository.try_acquire_refresh_lock()/is_refresh_locked().
    is_refreshing: bool = False


class RefreshRequest(BaseModel):
    specialists: list[str]
    # Narrow, specific field rather than a generic per-specialist params
    # dict — only `affo` uses this today (walk-backward iterations per
    # refresh click); add another specific field if a future specialist
    # needs its own refresh-time option, rather than building a generic
    # mechanism no other specialist needs yet.
    affo_iterations: int = 1
