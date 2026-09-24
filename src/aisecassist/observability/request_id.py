"""Identifiant de requete : attribution, validation, propagation (ticket 23).

Un identifiant par requete est ce qui rend une panne racontable. Sans lui, les
traces de trois requetes concurrentes s'entrelacent dans le meme flux et plus
personne ne sait quelle recherche a precede quelle generation.

**Un en-tete client est une entree hostile.** Accepter `X-Request-ID` tel quel
ouvrirait deux portes, toutes deux vers les logs :

- **l'injection de logs** — un saut de ligne dans la valeur, et l'attaquant
  fabrique une ligne de journal entiere, qu'un agregateur lira comme un
  evenement authentique ;
- **le gonflement** — une valeur de dix kilo-octets recopiee dans chaque ligne
  d'une requete, multipliee par le nombre de requetes.

D'ou une forme stricte et courte. Une valeur non conforme n'est pas une erreur
pour le client : elle est simplement ignoree, et le serveur en attribue une.
Refuser la requete punirait un client mal configure pour un detail de confort.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

EN_TETE = "X-Request-ID"

# Alphanumerique, tiret et souligne, 64 caracteres au plus. Couvre un UUID, un
# identifiant de trace, un numero de corrélation d'infrastructure — et exclut
# tout ce qui pourrait structurer une ligne de log : sauts de ligne, guillemets,
# accolades, caracteres de controle.
_FORME_VALIDE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def nouvel_identifiant() -> str:
    """Attribue un identifiant : 32 caracteres hexadecimaux."""
    return uuid.uuid4().hex


def identifiant_recevable(valeur: str | None) -> str | None:
    """Rend la valeur fournie par le client si elle est sure, sinon `None`."""
    if valeur is None:
        return None
    return valeur if _FORME_VALIDE.match(valeur) else None


class RequestIdMiddleware:
    """Attache un identifiant a chaque requete, et le rend au client.

    Intergiciel ASGI ecrit a la main plutot que `BaseHTTPMiddleware` de
    Starlette : ce dernier enveloppe la reponse dans une tache separee, ce qui
    casse la propagation des variables de contexte vers le code appele — donc
    precisement ce qu'on cherche a faire ici.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        identifiant = identifiant_recevable(_en_tete_entrant(scope)) or nouvel_identifiant()

        # Purge avant de lier : une tache reutilisee par la boucle d'evenements
        # conserverait sinon le contexte de la requete precedente, et deux
        # requetes se retrouveraient sous le meme identifiant.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=identifiant)

        async def send_avec_en_tete(message: Message) -> None:
            if message["type"] == "http.response.start":
                entetes = [*message.get("headers", [])]
                entetes.append((EN_TETE.lower().encode(), identifiant.encode()))
                message = {**message, "headers": entetes}
            await send(message)

        try:
            await self._app(scope, receive, send_avec_en_tete)
        finally:
            structlog.contextvars.clear_contextvars()


def _en_tete_entrant(scope: Scope) -> str | None:
    """Lit `X-Request-ID` dans les en-tetes ASGI, insensible a la casse."""
    attendu = EN_TETE.lower().encode()
    entetes: Iterable[tuple[bytes, bytes]] = scope.get("headers", [])
    for nom, valeur in entetes:
        if nom.lower() == attendu:
            # latin-1 ne leve jamais : tout octet y a une correspondance. La
            # validation qui suit se charge d'ecarter ce qui n'est pas sain.
            return valeur.decode("latin-1")
    return None
