"""Doubles de test partages.

Ils implementent les interfaces reelles (`Embedder`, `VectorStore`,
`LLMProvider`) plutot que d'etre des mocks generiques : si une signature
d'interface change, ces doubles cassent a la compilation mypy plutot que de
laisser passer des tests qui ne testent plus rien.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from aisecassist.agents.tools import Tool, ToolResult
from aisecassist.embeddings.base import Embedder
from aisecassist.generation.service import GenerationService
from aisecassist.llm.base import (
    ChatMessage,
    ChatReply,
    LLMProvider,
    ToolCallingProvider,
    ToolSpec,
)
from aisecassist.retrieval.service import RetrievalService
from aisecassist.vectorstore.base import SearchResult, VectorStore

DIMENSION = 4


class FakeEmbedder(Embedder):
    """Vectorise de facon deterministe, sans modele."""

    def __init__(self, dimension: int = DIMENSION) -> None:
        self._dimension = dimension
        self.calls: list[list[str]] = []

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(texte) % 7), 1.0, 0.0, 0.0] for texte in texts]


class FakeVectorStore(VectorStore):
    """Renvoie une liste d'extraits fixee a la construction."""

    def __init__(self, results: Sequence[SearchResult] | None = None) -> None:
        self._results = list(results or [])
        self.last_k: int | None = None

    async def ensure_collection(self, dimension: int) -> None:
        return None

    async def add(
        self,
        texts: Sequence[str],
        vectors: Sequence[Sequence[float]],
        sources: Sequence[str],
    ) -> None:
        return None

    async def search(self, query_vector: Sequence[float], k: int) -> list[SearchResult]:
        self.last_k = k
        return self._results[:k]


class FakeLLM(LLMProvider):
    """Renvoie une reponse fixee, et conserve le prompt recu."""

    def __init__(self, response: str = "reponse du modele") -> None:
        self._response = response
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._response

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        yield self._response


class StreamingLLM(LLMProvider):
    """Emet une suite de fragments fixee, pour tester le streaming.

    `FakeLLM` n'emet qu'un seul fragment : il ne prouverait rien du decoupage
    ni de l'ordre.
    """

    def __init__(self, fragments: Sequence[str]) -> None:
        self._fragments = list(fragments)
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "".join(self._fragments)

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        for fragment in self._fragments:
            yield fragment


class ExplodingLLM(LLMProvider):
    """Leve l'erreur fournie a chaque appel, pour tester la gestion de panne."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def complete(self, prompt: str) -> str:
        raise self._error

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        raise self._error
        yield ""  # pragma: no cover - rend la fonction generatrice


class ExplodingVectorStore(VectorStore):
    """Leve l'erreur fournie a la recherche."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def ensure_collection(self, dimension: int) -> None:
        return None

    async def add(
        self,
        texts: Sequence[str],
        vectors: Sequence[Sequence[float]],
        sources: Sequence[str],
    ) -> None:
        return None

    async def search(self, query_vector: Sequence[float], k: int) -> list[SearchResult]:
        raise self._error


def extrait(text: str, source: str = "doc.md", score: float = 0.9) -> SearchResult:
    """Raccourci de construction d'un `SearchResult`."""
    return SearchResult(text=text, source=source, score=score)


def make_generation(llm: LLMProvider, max_answer_chars: int = 8_000) -> GenerationService:
    """Construit un `GenerationService` pour les tests.

    Le plafond de longueur est un argument obligatoire du service : il vient de
    la configuration et ne doit pas avoir de valeur implicite en production.
    Cette fabrique evite de le repeter dans chaque test, tout en laissant ceux
    qui verifient la troncature le fixer explicitement.
    """
    return GenerationService(llm, max_answer_chars=max_answer_chars)


def make_retrieval(
    store: VectorStore,
    *,
    embedder: Embedder | None = None,
    default_k: int = 5,
    min_score: float = 0.0,
) -> RetrievalService:
    """Construit un `RetrievalService` pour les tests.

    Le seuil de pertinence est un argument obligatoire du service : il depend du
    modele d'embeddings et vient de la configuration (ADR-0010). Ici il vaut 0 par
    defaut, pour que les tests qui ne portent pas sur le filtrage n'en dependent
    pas ; ceux qui le verifient le fixent explicitement.
    """
    return RetrievalService(
        embedder or FakeEmbedder(),
        store,
        default_k,
        min_score=min_score,
    )


class ScriptedChatLLM(ToolCallingProvider):
    """Rejoue une suite de reponses fixee, et conserve ce qu'on lui a envoye.

    Quand le script est epuise, la derniere reponse est rejouee. C'est ce qui
    permet de tester un plafond : un modele qui redemande le meme outil sans
    fin est exactement le cas que le plafond doit couper.
    """

    def __init__(self, replies: Sequence[ChatReply]) -> None:
        if not replies:
            raise ValueError("Au moins une reponse est requise.")
        self._replies = list(replies)
        self.conversations: list[list[ChatMessage]] = []
        self.outils_presentes: list[ToolSpec] = []

    @property
    def appels(self) -> int:
        """Nombre de fois ou le modele a ete interroge."""
        return len(self.conversations)

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
    ) -> ChatReply:
        self.conversations.append(list(messages))
        self.outils_presentes = list(tools)
        indice = min(len(self.conversations) - 1, len(self._replies) - 1)
        return self._replies[indice]


class FakeTool(Tool):
    """Outil de test : renvoie une observation fixee et enregistre ses appels."""

    def __init__(
        self,
        name: str = "rechercher_corpus",
        observation: str = "extrait de test",
        sources: Sequence[str] = ("owasp.md",),
    ) -> None:
        self._name = name
        self._observation = observation
        self._sources = tuple(sources)
        self.arguments_recus: list[Mapping[str, Any]] = []

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._name,
            description="Outil de test.",
            parameters={"type": "object", "properties": {"question": {"type": "string"}}},
        )

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        self.arguments_recus.append(dict(arguments))
        return ToolResult(observation=self._observation, sources=self._sources)
