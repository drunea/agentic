from dataclasses import dataclass

from agentic.data.base import DataProvider


@dataclass
class AgentDeps:
    """Shared dependencies passed to every agent via `deps_type`.

    Only a single concrete provider (FMP) exists today. The multi-provider
    fallback chain (`provider_chain`) and the RAG retriever are added when
    something actually needs them.
    """

    provider: DataProvider
