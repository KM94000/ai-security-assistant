"""Routes POST /query et POST /query/stream (tickets 13 et 14).

Routes minces, conformement a CLAUDE.md section 6 : elles valident, deleguent,
formatent. Aucune logique metier ici — la recherche est dans `retrieval/`,
l'assemblage du prompt et l'appel au modele dans `generation/`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from aisecassist.api.deps import Services, get_services
from aisecassist.api.messages import MESSAGE_INDISPONIBLE
from aisecassist.api.schemas import QueryRequest, QueryResponse, SourceRef
from aisecassist.api.sse import sse_event
from aisecassist.embeddings.base import EmbedderError
from aisecassist.llm.base import LLMError
from aisecassist.observability.tracing import traced
from aisecassist.vectorstore.base import SearchResult, VectorStoreError

logger = logging.getLogger(__name__)

router = APIRouter()

# Reponses d'erreur documentees dans OpenAPI. Sans elles, /docs laisse croire
# qu'un appel ne peut que reussir, et un client n'a aucune raison de prevoir
# les cas de panne.
_REPONSES_ERREUR: dict[int | str, dict[str, Any]] = {
    422: {
        "description": (
            "Requete invalide : champ absent, vide, trop long, de mauvais type, "
            "ou champ inattendu. Le corps de la reponse nomme le champ fautif."
        )
    },
    503: {
        "description": (
            "Une dependance est indisponible (base vectorielle ou modele). Le "
            "message est volontairement generique : le detail part dans les logs "
            "du serveur, jamais dans la reponse."
        )
    },
}

# Exemple de flux, affiche dans /docs : OpenAPI ne sait pas decrire une suite
# d'evenements SSE, seulement un corps de reponse. Sans cet exemple, un client
# n'a aucun moyen de deviner le format.
_EXEMPLE_FLUX = """event: sources
data: {"sources": [{"source": "owasp-llm-top10.md", "score": 0.58}]}

event: token
data: {"text": "L'injection indirecte "}

event: token
data: {"text": "passe par un document ingere."}

event: done
data: {}
"""


@router.post(
    "/query",
    response_model=QueryResponse,
    tags=["rag"],
    summary="Poser une question, recevoir la reponse complete",
    responses=_REPONSES_ERREUR,
)
async def query(
    payload: QueryRequest,
    services: Annotated[Services, Depends(get_services)],
) -> QueryResponse:
    """Repond a une question de cybersecurite a partir du corpus indexe.

    Les sources renvoyees sont les extraits reellement recuperes, avec leur
    score : c'est ce qui permet a l'utilisateur de verifier la reponse plutot
    que de la croire.
    """
    with traced("query", question=payload.question) as span:
        results = await services.retrieval.retrieve(payload.question)
        generated = await services.generation.answer(payload.question, results)
        span.sortie(answer=generated.answer, sources=[r.source for r in results])

    return QueryResponse(
        answer=generated.answer,
        sources=_references(results),
    )


@router.post(
    "/query/stream",
    tags=["rag"],
    summary="Poser une question, recevoir la reponse au fil de la generation",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "Flux Server-Sent Events. Trois types d'evenements : `sources` en "
                "premier, puis autant de `token` que de fragments, enfin `done`. "
                "Une panne survenue apres l'ouverture du flux produit un evenement "
                "`error` — le statut reste 200, les en-tetes etant deja envoyes."
            ),
            "content": {"text/event-stream": {"example": _EXEMPLE_FLUX}},
        },
        **_REPONSES_ERREUR,
    },
)
async def query_stream(
    payload: QueryRequest,
    services: Annotated[Services, Depends(get_services)],
) -> StreamingResponse:
    """Meme reponse que `/query`, emise au fil de la generation.

    Le flux emet trois types d'evenements : `sources` en premier, puis autant
    de `token` que de fragments, et enfin `done`. Les sources arrivent avant le
    texte pour que le client puisse les afficher pendant que la reponse se
    construit.

    La recherche est faite **avant** d'ouvrir le flux, deliberement : tant que
    rien n'est emis, une panne se traduit par un 503 propre via les
    gestionnaires d'erreurs. Une fois le flux ouvert, ce n'est plus possible.
    """
    results = await services.retrieval.retrieve(payload.question)

    return StreamingResponse(
        _flux_sse(services, payload.question, results),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Empeche un reverse proxy de tamponner la reponse : sans cela, le
            # client recoit tout d'un bloc a la fin et le streaming ne sert a rien.
            "X-Accel-Buffering": "no",
        },
    )


async def _flux_sse(
    services: Services,
    question: str,
    results: Sequence[SearchResult],
) -> AsyncIterator[str]:
    """Produit le flux d'evenements SSE."""
    yield sse_event("sources", {"sources": [ref.model_dump() for ref in _references(results)]})

    try:
        async for fragment in services.generation.stream_answer(question, results):
            yield sse_event("token", {"text": fragment})
    except (LLMError, VectorStoreError, EmbedderError) as exc:
        # Le statut 200 et les en-tetes sont deja partis : les gestionnaires
        # d'exception de l'application ne peuvent plus s'appliquer. Sans ce
        # rattrapage, le chemin streame laisserait fuiter ce que le chemin
        # classique masque, et la connexion se fermerait sans explication.
        logger.warning("Flux interrompu par une panne de dependance : %s", exc)
        yield sse_event("error", {"detail": MESSAGE_INDISPONIBLE})
        return

    yield sse_event("done", {})


def _references(results: Sequence[SearchResult]) -> list[SourceRef]:
    return [SourceRef(source=r.source, score=r.score) for r in results]
