"""Application FastAPI : assemblage, cycle de vie et gestion des erreurs."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aisecassist.agents.service import AgentTimeoutError
from aisecassist.api.agent import router as agent_router
from aisecassist.api.deps import build_services, close_services
from aisecassist.api.health import router as health_router
from aisecassist.api.messages import (
    MESSAGE_AGENT_TROP_LONG,
    MESSAGE_INATTENDU,
    MESSAGE_INDISPONIBLE,
)
from aisecassist.api.query import router as query_router
from aisecassist.config import settings
from aisecassist.embeddings.base import EmbedderError
from aisecassist.llm.base import LLMError
from aisecassist.retrieval.service import RetrievalError
from aisecassist.vectorstore.base import VectorStoreError

logger = logging.getLogger(__name__)


def _version() -> str:
    """Lit la version depuis les metadonnees du paquet installe.

    Plutot qu'une constante ici : une version ecrite en dur finit toujours par
    diverger de celle de `pyproject.toml`, et c'est la doc publique qui ment.
    """
    try:
        return version("ai-security-assistant")
    except PackageNotFoundError:  # pragma: no cover - paquet non installe
        return "0.0.0+inconnu"


_DESCRIPTION = """Assistant de **cybersecurite** fonde sur un RAG : les reponses sont construites
a partir d'un corpus de referentiels indexe (OWASP LLM Top 10, MITRE ATLAS,
NIST AI RMF), et **toujours accompagnees de leurs sources**.

### Verifier plutot que croire

Chaque reponse cite les extraits qui l'ont alimentee, avec leur score de
similarite. Une reponse de securite qu'on ne peut pas verifier n'est pas
utilisable : si le corpus ne contient pas de quoi repondre, le service le dit
explicitement au lieu de supposer.

### Trois facons d'interroger

- `POST /query` renvoie la reponse complete en une fois.
- `POST /query/stream` la renvoie au fil de la generation. Sur un modele local,
  le premier texte apparait en environ deux secondes contre une vingtaine pour
  la reponse complete.
- `POST /agent` laisse le modele **choisir ses outils** : chercher dans le
  corpus, consulter une CVE dans la base du NIST, recommencer si besoin. Plus
  pertinent sur une question qui croise plusieurs sources, nettement plus lent
  sur une question simple.

### Quand utiliser l'agent plutot que /query

`/query` cherche toujours, une fois, puis redige : c'est le bon choix par
defaut. L'agent vaut son cout quand la question demande de croiser des sources
— « cette CVE releve-t-elle d'une categorie du OWASP LLM Top 10 ? » — ou quand
une premiere recherche peut en appeler une seconde. Le champ `iterations` de sa
reponse dit combien d'etapes ont reellement eu lieu.

### Gestion des erreurs

Une entree invalide donne un **422** decrivant le champ fautif. Une panne de
dependance donne un **503** volontairement generique : le detail technique part
dans les logs du serveur, jamais dans la reponse. Un agent qui depasse son
budget de temps donne un **504** — rien n'est casse, le cheminement a ete trop
long.
"""

_TAGS = [
    {
        "name": "rag",
        "description": "Interrogation du corpus. Toute reponse est sourcee.",
    },
    {
        "name": "agent",
        "description": (
            "Interrogation par un agent qui choisit ses outils. Les outils "
            "autorises sont fixes par le code, jamais par la question."
        ),
    },
    {
        "name": "monitoring",
        "description": "Sondes de supervision, appelees par la plateforme d'hebergement.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cree les services au demarrage et ferme leurs clients a l'arret."""
    app.state.services = build_services()
    try:
        yield
    finally:
        await close_services(app.state.services)


app = FastAPI(
    title=settings.app_name,
    description=_DESCRIPTION,
    version=_version(),
    openapi_tags=_TAGS,
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(query_router)
app.include_router(agent_router)


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
    return JSONResponse(status_code=503, content={"detail": MESSAGE_INDISPONIBLE})


@app.exception_handler(AgentTimeoutError)
async def agent_trop_long(request: Request, exc: Exception) -> JSONResponse:
    """Budget de temps de l'agent epuise : 504, et non 503.

    La distinction n'est pas cosmetique. Un 503 dit « le service est en panne,
    reessaie a l'identique » ; un 504 dit « la demande a ete trop longue a
    traiter ». Reessayer la meme question ne sert a rien, la reformuler si.
    """
    logger.warning("Agent interrompu sur %s : %s", request.url.path, exc)
    return JSONResponse(status_code=504, content={"detail": MESSAGE_AGENT_TROP_LONG})


@app.exception_handler(Exception)
async def erreur_inattendue(request: Request, exc: Exception) -> JSONResponse:
    """Filet de securite : aucune exception non prevue ne doit fuiter vers le client."""
    logger.exception("Erreur inattendue sur %s", request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": MESSAGE_INATTENDU})
