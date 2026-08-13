"""Route POST /query (ticket 13).

Route mince, conformement a CLAUDE.md section 6 : elle valide, delegue, formate.
Aucune logique metier ici — la recherche est dans `retrieval/`, l'assemblage du
prompt et l'appel au modele dans `generation/`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from aisecassist.api.deps import Services, get_services
from aisecassist.api.schemas import QueryRequest, QueryResponse, SourceRef

router = APIRouter()


@router.post("/query", response_model=QueryResponse, tags=["rag"])
async def query(
    payload: QueryRequest,
    services: Annotated[Services, Depends(get_services)],
) -> QueryResponse:
    """Repond a une question de cybersecurite a partir du corpus indexe.

    Les sources renvoyees sont les extraits reellement recuperes, avec leur
    score : c'est ce qui permet a l'utilisateur de verifier la reponse plutot
    que de la croire.
    """
    results = await services.retrieval.retrieve(payload.question)
    generated = await services.generation.answer(payload.question, results)

    return QueryResponse(
        answer=generated.answer,
        sources=[SourceRef(source=r.source, score=r.score) for r in results],
    )
