"""Agent definition + where agent definitions are loaded from.

AgentConfig is the *data* that makes one voice agent different from another.
The pipeline code never hard-codes a prompt or voice; it receives an AgentConfig.

`AgentRepository` is a Protocol (the seam); the Postgres implementation lives in
app/agent/repository.py. Every edit creates a new immutable version, and a call
snapshots the config it started with, so editing an agent never changes a live call.
"""

import re
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class AgentSpec(BaseModel):
    """What an admin supplies (create/update). Versioning is the server's job."""

    name: str = Field(min_length=1, max_length=120)
    system_prompt: str = Field(min_length=1, max_length=20_000)
    greeting_instruction: str = Field(
        default="Greet the caller briefly and ask how you can help.", max_length=2_000
    )
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
    # None => fall back to Settings defaults.
    voice: str | None = Field(default=None, max_length=100)
    llm_model: str | None = Field(default=None, max_length=100)
    # Only react to the voice that was registered at the start of the call, ignoring
    # TVs / bystanders. Turn off for e.g. a speakerphone with several real callers.
    speaker_lock: bool = True
    # Knowledge Base: file path to a JSON product/FAQ catalog. Empty = no KB.
    kb_file: str = ""
    kb_top_k: int = 3


class AgentConfig(AgentSpec):
    id: str
    # Bumped on every edit. Sessions record the version they ran with.
    version: int = 1

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not AGENT_ID_RE.match(v):
            raise ValueError("id must be lowercase letters, digits, '-' or '_' (max 63 chars)")
        return v


class AgentRepository(Protocol):
    async def get(self, org_id: str, agent_id: str) -> AgentConfig | None: ...
    async def list(self, org_id: str) -> list[AgentConfig]: ...
    async def create(self, org_id: str, agent_id: str, spec: AgentSpec) -> AgentConfig: ...
    async def update(self, org_id: str, agent_id: str, spec: AgentSpec) -> AgentConfig | None: ...
    async def delete(self, org_id: str, agent_id: str) -> bool: ...


class AgentExists(Exception):
    pass


DEFAULT_AGENT_ID = "default"
DEFAULT_AGENT_SPEC = AgentSpec(
    name="Demo Assistant",
    system_prompt=(
        "You are a jewellery shop marketing agent. The name of the jewellery shop is Lavanya. "
        "You will talk with customers over the call and try to sell our product. Convince the user. "
        "Reply to user query. Be humble. "
        "When the system provides product information from our catalog, use it to answer "
        "the customer's question accurately — mention the product name, price, and key details. "
        "If a product is out of stock, let them know and suggest alternatives. "
        "Your replies are spoken aloud, so keep them short (one to two sentences), "
        "use plain words, and never use lists, markdown, emojis or special symbols. "
        "If you don't know something, say so honestly."
    ),
    kb_file="data/catalog.json",
)
