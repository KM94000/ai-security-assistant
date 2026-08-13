"""Application FastAPI : assemblage, cycle de vie et gestion des erreurs."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aisecassist.api.deps import build_services, close_services
from aisecassist.api.health import router as health_router
from aisecassist.api.query import router as query_router
from aisecassist.config import settings
from aisecassist.embeddings.base import EmbedderError
from aisecassist.llm.base import LLMError
from aisecassist.retrieval.service import RetrievalError
from aisecassist.vectorstore.base import VectorStoreError

logger = logging.getLogger(__name__)

# Messages renvoyes au client. Volontairement generiques : le detail technique
# part dans les logs, jamais dans la reponse. Une trace d'exception exposee
# renseigne un attaquant sur la pile, les chemins et les versions
# (CLAUDE.md section 6 ; SECURITY.md, SEC-11).
_MESSAGE_INDISPONIBLE = "Le service est temporairement indisponible. Reessayez plus tard."
_MESSAGE_INATTENDU = "Une erreur interne est survenue."


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cree les services au demarrage et ferme leurs clients a l'arret."""
    app.state.services = build_services()
    try:
        yield
    finally:
        await close_services(app.state.services)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(health_router)
app.include_router(query_router)


@app.exception_handler(LLMError)
@app.exception_handler(VectorStoreError)
@app.exception_handler(EmbedderError)
@app.exception_handler(RetrievalError)
async def dependance_indisponible(request: Request, exc: Exception) -> JSONResponse:
    """Panne d'une dependance : 503, sans exposer laquelle ni pourquoi.

    Dire au client que "la connexion a Qdrant sur le port 6333 a echoue" lui
    apprend la topologie interne. Le detail est journalise cote serveur.
    """
    logger.warning("Dependance indisponible sur %s : %s", request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": _MESSAGE_INDISPONIBLE})


@app.exception_handler(Exception)
async def erreur_inattendue(request: Request, exc: Exception) -> JSONResponse:
    """Filet de securite : aucune exception non prevue ne doit fuiter vers le client."""
    logger.exception("Erreur inattendue sur %s", request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": _MESSAGE_INATTENDU})
