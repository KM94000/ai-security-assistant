"""Route POST /agent (ticket 21).

Route mince, comme `/query` : elle valide, delegue, formate. Toute la logique
— le graphe, la liste blanche d'outils, les plafonds — vit dans `agents/`.

**Le meme schema d'entree que `/query`.** Deliberement : l'agent n'est pas une
seconde porte aux regles plus souples, c'est une autre facon de traiter la meme
question. Lui donner son propre plafond de longueur reviendrait tot ou tard a en
faire un contournement de l'autre (SEC-10).

**Pas de variante streamee.** La reponse finale de l'agent sort du dernier appel
au modele, apres les eventuels appels d'outils : il n'y a rien a emettre avant
que le cheminement ne soit termine. Un flux n'apporterait donc que l'illusion du
direct. Il deviendra interessant quand les etapes elles-memes seront emises, ce
qui suppose le tracage de M4.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from aisecassist.api.deps import Services, get_services
from aisecassist.api.schemas import AgentResponse, QueryRequest

logger = logging.getLogger(__name__)

router = APIRouter()

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
    504: {
        "description": (
            "L'agent n'a pas abouti dans le budget de temps imparti. Rien n'est "
            "casse : le cheminement a simplement ete trop long. Reformuler la "
            "question en la rendant plus precise reduit le nombre d'etapes."
        )
    },
}


@router.post(
    "/agent",
    response_model=AgentResponse,
    tags=["agent"],
    summary="Poser une question complexe, laisser l'agent choisir ses outils",
    responses=_REPONSES_ERREUR,
)
async def agent(
    payload: QueryRequest,
    services: Annotated[Services, Depends(get_services)],
) -> AgentResponse:
    """Repond a une question en laissant le modele choisir ses outils.

    La difference avec `/query` n'est pas la qualite de la reponse, c'est le
    chemin : `/query` cherche toujours dans le corpus, une fois, puis redige.
    L'agent decide s'il cherche, ou il cherche, et s'il doit recommencer — ce
    qui le rend meilleur sur une question qui croise plusieurs sources, et plus
    lent sur une question simple.

    Le champ `iterations` rend ce cheminement visible : zero signifie que le
    modele a repondu de lui-meme, sans rien consulter.
    """
    resultat = await services.agent.answer(payload.question)

    return AgentResponse(
        answer=resultat.answer,
        sources=list(resultat.sources),
        iterations=resultat.iterations,
    )
