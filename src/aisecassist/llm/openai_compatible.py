"""Fournisseur hebergé parlant l'API « chat completions » (ticket 26, ADR-0013).

Une seule implementation pour plusieurs hebergeurs — Groq, OpenAI, Together,
Mistral, Fireworks, ou un vLLM local — parce qu'ils exposent tous la meme forme
d'API. On n'en change que par `HOSTED_LLM_BASE_URL` et `HOSTED_LLM_MODEL` ;
aucune ligne de code ne bouge.

**Ce que ce module existe pour prouver.** L'ADR-0003 affirme depuis le premier
jour que changer de fournisseur ne touche aucun module metier. C'etait une
promesse d'architecture non verifiee. Ce fichier la met a l'epreuve : il
implemente les deux memes interfaces qu'`OllamaProvider`, et rien d'autre dans
le projet ne sait qu'il existe — sauf la racine de composition, dont c'est le
role.

**Pourquoi httpx plutot que le SDK officiel.** Le projet parle deja a Ollama en
HTTP direct ; l'API de chat tient en deux formes de requete. Ajouter un SDK
apporterait des dizaines de paquets transitifs — donc de la surface de chaine
d'approvisionnement (LLM03) — pour economiser une centaine de lignes que nous
devons de toute facon comprendre. Ce qu'on perd : les reessais automatiques et
la gestion fine des quotas, a reprendre si le besoin apparait.
"""

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

_CHEMIN_CHAT = "/chat/completions"
_FIN_DE_FLUX = "[DONE]"

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider, ToolCallingProvider):
    """Appelle un service de chat de forme OpenAI.

    La cle d'API n'est jamais journalisee, ni incluse dans un message d'erreur :
    les exceptions de ce module ne portent que le contexte et le type de la
    panne, comme celles d'`OllamaProvider`.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout_s: float,
        client: httpx.AsyncClient | None = None,
        *,
        chat_temperature: float = 0.0,
    ) -> None:
        self._model = model
        # Meme raison qu'avec Ollama : choisir un outil n'appelle aucune
        # creativite, et une decision reproductible est auditable (ADR-0011).
        self._chat_temperature = chat_temperature
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def complete(self, prompt: str) -> str:
        donnees = await self._poster(
            {"model": self._model, "messages": [{"role": "user", "content": prompt}]}
        )
        return _texte_du_premier_choix(donnees)

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        charge = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        try:
            async with self._client.stream("POST", _CHEMIN_CHAT, json=charge) as reponse:
                await _verifier_le_flux(reponse)
                async for ligne in reponse.aiter_lines():
                    if not ligne.startswith("data:"):
                        continue
                    charge_ligne = ligne[len("data:") :].strip()
                    # Le fournisseur signale la fin par une sentinelle textuelle.
                    # On s'arrete dessus plutot que d'attendre la fermeture du
                    # flux, qui peut trainer.
                    if charge_ligne == _FIN_DE_FLUX:
                        return
                    fragment = _fragment_du_flux(charge_ligne)
                    if fragment:
                        yield fragment
        except httpx.HTTPError as exc:
            raise LLMError(_decrire("Flux du fournisseur interrompu", exc)) from exc

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
    ) -> ChatReply:
        donnees = await self._poster(
            {
                "model": self._model,
                "messages": [_vers_message(message) for message in messages],
                "tools": [_vers_outil(outil) for outil in tools],
                "temperature": self._chat_temperature,
            }
        )
        message = _premier_message(donnees)
        texte = message.get("content")
        return ChatReply(
            text=texte.strip() if isinstance(texte, str) else "",
            tool_calls=_extraire_appels(message.get("tool_calls")),
        )

    async def aclose(self) -> None:
        """Libere le client HTTP si ce provider en est proprietaire."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OpenAICompatibleProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def _poster(self, charge: dict[str, Any]) -> dict[str, Any]:
        """Envoie une requete non streamee et rend l'objet JSON verifie."""
        try:
            reponse = await self._client.post(_CHEMIN_CHAT, json={**charge, "stream": False})
            reponse.raise_for_status()
            donnees: Any = reponse.json()
        except httpx.HTTPStatusError as exc:
            raise LLMError(_decrire_statut(exc)) from exc
        except httpx.HTTPError as exc:
            raise LLMError(_decrire("Appel au fournisseur echoue", exc)) from exc
        except json.JSONDecodeError as exc:
            raise LLMError("Reponse du fournisseur illisible : JSON invalide") from exc

        if not isinstance(donnees, dict):
            raise LLMError("Reponse inattendue du fournisseur : objet JSON attendu")
        return donnees


def _decrire(contexte: str, exc: Exception) -> str:
    """Compose un message exploitable dans les logs, sans jamais la cle d'API."""
    detail = str(exc).strip()
    return f"{contexte} ({type(exc).__name__})" + (f" : {detail}" if detail else "")


def _decrire_statut(exc: httpx.HTTPStatusError) -> str:
    """Nomme les deux codes qui ont une cause actionnable, sans citer la reponse.

    Le corps d'une erreur d'API peut contenir l'en-tete d'authentification
    reflete ou des details de compte. On ne retient donc que le code, et on
    traduit les deux cas ou savoir lequel change ce qu'il y a a faire.
    """
    code = exc.response.status_code
    if code == 401:
        return "Fournisseur : authentification refusee (401). Verifier HOSTED_LLM_API_KEY."
    if code == 429:
        return "Fournisseur : quota atteint (429)."
    return f"Appel au fournisseur refuse (HTTP {code})"


async def _verifier_le_flux(reponse: httpx.Response) -> None:
    """Leve avant de consommer le flux si le statut est en erreur.

    `raise_for_status()` sur une reponse streamee ne peut pas lire le corps :
    il faut l'avoir consomme. On ne le lit pas — le statut suffit, et le corps
    d'erreur d'un fournisseur n'a pas a se retrouver dans nos logs.
    """
    if reponse.status_code >= 400:
        await reponse.aread()
        raise LLMError(f"Flux refuse par le fournisseur (HTTP {reponse.status_code})")


def _fragment_du_flux(charge: str) -> str | None:
    """Decode la charge d'une ligne SSE et rend le fragment de texte s'il y en a un."""
    if not charge:
        return None

    try:
        objet: Any = json.loads(charge)
    except json.JSONDecodeError as exc:
        raise LLMError("Fragment non JSON recu du fournisseur") from exc
    if not isinstance(objet, dict):
        return None

    choix = objet.get("choices")
    if not isinstance(choix, list) or not choix or not isinstance(choix[0], dict):
        return None
    delta = choix[0].get("delta")
    if not isinstance(delta, dict):
        return None
    contenu = delta.get("content")
    return contenu if isinstance(contenu, str) else None


def _premier_message(donnees: dict[str, Any]) -> dict[str, Any]:
    """Extrait le message du premier choix, en verifiant chaque forme."""
    choix = donnees.get("choices")
    if not isinstance(choix, list) or not choix:
        raise LLMError("Reponse inattendue du fournisseur : aucun choix")
    premier = choix[0]
    if not isinstance(premier, dict):
        raise LLMError("Reponse inattendue du fournisseur : choix malforme")
    message = premier.get("message")
    if not isinstance(message, dict):
        raise LLMError("Reponse inattendue du fournisseur : champ 'message' absent")
    return message


def _texte_du_premier_choix(donnees: dict[str, Any]) -> str:
    contenu = _premier_message(donnees).get("content")
    if not isinstance(contenu, str):
        raise LLMError("Reponse inattendue du fournisseur : contenu absent ou non textuel")
    return contenu


def _vers_message(message: ChatMessage) -> dict[str, Any]:
    """Traduit un message vers la forme attendue par l'API.

    Deux differences avec Ollama, toutes deux imposees par le protocole :
    un resultat d'outil se designe par `tool_call_id` et non par le nom de
    l'outil, et un appel annonce par l'assistant doit porter ce meme
    identifiant. C'est la raison d'etre du champ `ToolCall.id`.
    """
    charge: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.role == "tool":
        # Repli sur le nom quand le fournisseur d'origine n'attribuait pas
        # d'identifiant : la serialisation des appels ci-dessous fait le meme
        # repli, donc les deux cotes restent apparies.
        charge["tool_call_id"] = message.tool_call_id or message.tool_name or ""
    if message.tool_calls:
        charge["tool_calls"] = [
            {
                "id": appel.id or appel.name,
                "type": "function",
                "function": {"name": appel.name, "arguments": json.dumps(dict(appel.arguments))},
            }
            for appel in message.tool_calls
        ]
    return charge


def _vers_outil(outil: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": outil.name,
            "description": outil.description,
            "parameters": dict(outil.parameters),
        },
    }


def _extraire_appels(brut: Any) -> tuple[ToolCall, ...]:
    """Traduit les appels annonces, en ecartant ceux qui sont inexploitables.

    Meme regle qu'avec Ollama : un appel malforme est une erreur du modele, pas
    une panne du fournisseur. L'agent sait traiter l'absence d'appel.
    """
    if not isinstance(brut, list):
        return ()

    appels: list[ToolCall] = []
    ignores = 0
    for entree in brut:
        appel = _vers_appel(entree)
        if appel is None:
            ignores += 1
            continue
        appels.append(appel)

    if ignores:
        logger.warning("%d appel(s) d'outil ecarte(s) : forme inexploitable.", ignores)
    return tuple(appels)


def _vers_appel(entree: Any) -> ToolCall | None:
    if not isinstance(entree, dict):
        return None
    fonction = entree.get("function")
    if not isinstance(fonction, dict):
        return None
    nom = fonction.get("name")
    if not isinstance(nom, str) or not nom:
        return None

    # Ici les arguments arrivent **toujours** en chaine JSON, contrairement a
    # Ollama qui rend un objet. Un JSON invalide donne un dictionnaire vide :
    # la validation de l'outil produira un refus explicite, plus utile qu'une
    # exception a ce niveau.
    arguments: Any = fonction.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}

    identifiant = entree.get("id")
    return ToolCall(
        name=nom,
        arguments=arguments if isinstance(arguments, dict) else {},
        id=identifiant if isinstance(identifiant, str) and identifiant else None,
    )
