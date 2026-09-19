import os

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set in .env")
    return value


API_URL = _require_env("FRONTEND_API_URL")
WS_API_URL = API_URL.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
