"""Implementation de `LLMProvider` adossee a un serveur Ollama (ADR-0003)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from types import TracebackType
from typing import Any

import httpx

from aisecassist.llm.base import (
    ChatMessage,
    ChatReply,
    LLMError,
    LLMProvider,
    ToolCall,
    ToolCallingProvider,
    ToolSpec,
)

_GENERATE_PATH = "/api/generate"
_CHAT_PATH = "/api/chat"

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider, ToolCallingProvider):
    """Appelle un serveur Ollama via son API HTTP.

    Le client httpx est injectable : les tests unitaires fournissent un
    transport factice, ce qui permet de verifier le contrat sans reseau ni
    serveur Ollama, donc sans test lent ni non deterministe (ADR-0002).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float,
        client: httpx.AsyncClient | None = None,
        *,
        chat_temperature: float = 0.0,
    ) -> None:
        self._model = model
        # Temperature nulle sur le chemin outille. Ollama echantillonne a 0,8 par
        # defaut, et `llama3.1` decrit alors parfois l'appel d'outil en JSON dans
        # son texte au lieu d'emprunter le canal prevu — mesure a l'appui : la
        # meme conversation donne un appel structure une fois, du texte la fois
        # suivante. Choisir un outil n'appelle aucune creativite, et une decision
        # reproductible est une decision auditable.
        self._chat_temperature = chat_temperature
        # On ne ferme que le client qu'on a cree soi-meme : fermer un client
        # injecte reviendrait a saboter l'objet d'un appelant qui le reutilise.
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    async def complete(self, prompt: str) -> str:
        payload = {"model": self._model, "prompt": prompt, "stream": False}
        try:
            response = await self._client.post(_GENERATE_PATH, json=payload)
            response.raise_for_status()
            data: Any = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(_decrire("Appel a Ollama echoue", exc)) from exc
        except json.JSONDecodeError as exc:
            raise LLMError("Reponse d'Ollama illisible : JSON invalide") from exc

        return _extract_fragment(data, context="reponse complete")

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        payload = {"model": self._model, "prompt": prompt, "stream": True}
        try:
            async with self._client.stream("POST", _GENERATE_PATH, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = _parse_stream_line(line)
                    fragment = chunk.get("response")
                    if isinstance(fragment, str) and fragment:
                        yield fragment
                    # Ollama signale la fin par `done: true` sur le dernier
                    # objet. On s'arrete dessus plutot que d'attendre la
                    # fermeture du flux, qui peut trainer.
                    if chunk.get("done") is True:
                        return
        except httpx.HTTPError as exc:
            raise LLMError(_decrire("Flux Ollama interrompu", exc)) from exc

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
    ) -> ChatReply:
        payload = {
            "model": self._model,
            "messages": [_to_ollama_message(message) for message in messages],
            "tools": [_to_ollama_tool(tool) for tool in tools],
            "stream": False,
            "options": {"temperature": self._chat_temperature},
        }
        try:
            response = await self._client.post(_CHAT_PATH, json=payload)
            response.raise_for_status()
            data: Any = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(_decrire("Appel a Ollama (chat) echoue", exc)) from exc
        except json.JSONDecodeError as exc:
            raise LLMError("Reponse d'Ollama illisible : JSON invalide") from exc

        if not isinstance(data, dict):
            raise LLMError("Reponse Ollama inattendue (chat) : objet JSON attendu")
        message = data.get("message")
        if not isinstance(message, dict):
            raise LLMError("Reponse Ollama inattendue (chat) : champ 'message' absent")

        texte = message.get("content")
        return ChatReply(
            text=texte.strip() if isinstance(texte, str) else "",
            tool_calls=_extract_tool_calls(message.get("tool_calls")),
        )

    async def aclose(self) -> None:
        """Libere le client HTTP si ce provider en est proprietaire."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OllamaProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


def _decrire(contexte: str, exc: Exception) -> str:
    """Compose un message d'erreur qui reste exploitable dans les logs.

    httpx leve certaines exceptions — les depassements de delai notamment — dont
    le `str()` est vide. Interpoler l'exception seule produit alors un log du
    genre "Appel a Ollama echoue :", qui ne permet aucun diagnostic. Le nom de
    la classe, lui, est toujours present et suffit souvent a comprendre.
    """
    detail = str(exc).strip()
    return f"{contexte} ({type(exc).__name__})" + (f" : {detail}" if detail else "")


def _parse_stream_line(line: str) -> dict[str, Any]:
    """Decode une ligne NDJSON du flux Ollama."""
    try:
        chunk: Any = json.loads(line)
    except json.JSONDecodeError as exc:
        raise LLMError("Fragment non JSON recu d'Ollama") from exc
    if not isinstance(chunk, dict):
        raise LLMError("Fragment Ollama inattendu : objet JSON attendu")
    return chunk


def _extract_fragment(data: Any, *, context: str) -> str:
    """Extrait le champ `response` en verifiant sa forme.

    On ne fait jamais confiance a la forme de la reponse d'un service externe :
    un `data["response"]` direct ferait remonter un KeyError ou un TypeError
    opaque a des couches qui ne savent pas d'ou il vient.
    """
    if not isinstance(data, dict):
        raise LLMError(f"Reponse Ollama inattendue ({context}) : objet JSON attendu")
    fragment = data.get("response")
    if not isinstance(fragment, str):
        raise LLMError(
            f"Reponse Ollama inattendue ({context}) : champ 'response' absent ou non textuel"
        )
    return fragment


def _to_ollama_message(message: ChatMessage) -> dict[str, Any]:
    """Traduit un message vers la forme attendue par l'API d'Ollama."""
    charge: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_name is not None:
        charge["tool_name"] = message.tool_name
    if message.tool_calls:
        charge["tool_calls"] = [
            {"function": {"name": appel.name, "arguments": dict(appel.arguments)}}
            for appel in message.tool_calls
        ]
    return charge


def _to_ollama_tool(tool: ToolSpec) -> dict[str, Any]:
    """Traduit une declaration d'outil vers la forme attendue par Ollama."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def _extract_tool_calls(brut: Any) -> tuple[ToolCall, ...]:
    """Traduit les appels d'outils annonces, en ecartant ceux qui sont inexploitables.

    Un appel malforme n'est pas une panne du fournisseur : c'est le modele qui a
    mal repondu. Lever une erreur ferait tomber la requete entiere, alors que
    l'agent sait traiter l'absence d'appel — il repondra de lui-meme ou
    redemandera. Les entrees inutilisables sont donc ecartees et comptees.
    """
    if not isinstance(brut, list):
        return ()

    appels: list[ToolCall] = []
    ignores = 0
    for entree in brut:
        appel = _to_tool_call(entree)
        if appel is None:
            ignores += 1
            continue
        appels.append(appel)

    if ignores:
        logger.warning("%d appel(s) d'outil ecarte(s) : forme inexploitable.", ignores)
    return tuple(appels)


def _to_tool_call(entree: Any) -> ToolCall | None:
    """Convertit une entree brute en appel d'outil, ou `None` si elle est inutilisable."""
    if not isinstance(entree, dict):
        return None
    fonction = entree.get("function")
    if not isinstance(fonction, dict):
        return None
    nom = fonction.get("name")
    if not isinstance(nom, str) or not nom:
        return None

    arguments = fonction.get("arguments")
    if isinstance(arguments, str):
        # Certains fournisseurs serialisent les arguments en chaine JSON. Un
        # JSON invalide donne un dictionnaire vide : la validation de l'outil
        # produira un refus explicite, plus utile qu'une exception ici.
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}

    return ToolCall(name=nom, arguments=arguments if isinstance(arguments, dict) else {})
