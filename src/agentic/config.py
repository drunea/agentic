"""Central settings for the agentic package, loaded from environment/.env."""

import platform
import subprocess

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Populates os.environ from .env too, not just this module's Settings — needed
# so llm.py can read dynamic per-agent overrides like ORCHESTRATOR_LLM_BACKEND
# via plain os.getenv() without a fixed field for every possible agent name.
# override=True: python-dotenv defaults to leaving an already-set env var
# alone, so under `uvicorn --reload` (which re-imports modules but never
# clears os.environ) editing an EXISTING .env value would silently keep
# being ignored across reloads — only brand-new variables would ever pick
# up their .env value. override=True makes every reload re-sync from the
# current .env contents, not just the first one.
load_dotenv(override=True)


def _detect_ollama_host(configured_host: str = "") -> str:
    """Resolve the Ollama host, auto-detecting the Windows host IP under WSL.

    `OLLAMA_HOST` is conventionally used to configure the *server's* bind
    address (e.g. "0.0.0.0" to listen on all interfaces) — that value is
    meaningless as a client connection target, so it's ignored here rather
    than trusted verbatim.
    """
    if configured_host and configured_host != "0.0.0.0":
        return configured_host

    if "microsoft" in platform.uname().release.lower():
        try:
            output = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
            ).stdout
            return output.split()[2]
        except Exception:
            pass
    return "localhost"


class Settings(BaseSettings):
    """No hardcoded VALUES live here — every setting with a real, specific
    value (a URL, a port, a hostname, a model name, a db name...) is a
    required field with no `=` default, so a missing `.env` entry fails
    loudly at startup (`ValidationError`, naming exactly what's missing)
    instead of silently falling back to a value baked into this Python
    file.

    The exception is fields where an EMPTY string is itself a meaningful,
    intentional default — not a forgotten value:
    - `gemini_api_key`/`fred_api_key`/`alpha_vantage_api_key`/
      `sec_edgar_contact_email`: optional/reserved integrations, checked at
      their point of use (`if not settings.x: ...` skip/raise there) — an
      app that never uses Gemini or FRED shouldn't be forced to have keys
      for them.
    - `ollama_host`: empty deliberately triggers `_detect_ollama_host`'s
      auto-detect logic below, not a missing value.
    - `alert_webhook_url`: empty means "no webhook" — specialist failure
      alerts still go to the log and the Stock Analysis page banner.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    fmp_key: str
    fmp_base_url: str
    fmp_legacy_base_url: str
    fred_api_key: str = ""
    fred_base_url: str
    alpha_vantage_api_key: str = ""

    massive_api_key: str
    massive_base_url: str
    news_api_key: str
    news_api_base_url: str
    gnews_api_key: str
    gnews_base_url: str
    market_news_provider_order: str

    roicai_api_key: str
    roicai_base_url: str
    earnings_call_provider_order: str

    ollama_host: str = ""
    ollama_port: int
    ollama_model: str
    ollama_embed_model: str

    llm_backend: str  # global fallback default: "ollama" | "gemini"
    gemini_api_key: str = ""
    gemini_model: str
    mysql_host: str
    mysql_port: int
    mysql_db: str
    mysql_user: str
    mysql_password: str
    mysql_root_password: str

    chroma_persist_dir: str
    sec_edgar_company_name: str
    sec_edgar_contact_email: str = ""

    alert_webhook_url: str = ""

    @property
    def ollama_base_url(self) -> str:
        host = _detect_ollama_host(self.ollama_host)
        return f"http://{host}:{self.ollama_port}/v1"

    @property
    def ollama_native_base_url(self) -> str:
        """Ollama's own API (embeddings) — not the OpenAI-compatible `/v1` shim."""
        host = _detect_ollama_host(self.ollama_host)
        return f"http://{host}:{self.ollama_port}"

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}"
        )


settings = Settings()
