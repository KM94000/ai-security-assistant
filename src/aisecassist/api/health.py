"""Sonde de supervision."""

from fastapi import APIRouter

router = APIRouter()


@router.get(
    "/health",
    tags=["monitoring"],
    summary="Verifier que le service repond",
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
def health() -> dict[str, str]:
    """Sonde de vivacite : confirme que le service tourne.

    Appelee en boucle par les plateformes cloud et la supervision.

    Deliberement independante de Qdrant et du modele : une sonde de vivacite
    repond a la question « ce processus est-il vivant ? », pas « toutes ses
    dependances vont-elles bien ? ». Les confondre ferait redemarrer l'API en
    boucle parce que la base vectorielle est momentanement indisponible.
    """
    return {"status": "ok"}
