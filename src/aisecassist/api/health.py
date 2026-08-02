from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["monitoring"])
def health() -> dict[str, str]:
    """Sonde de vivacite : confirme que le service tourne.

    Appelee en boucle par les plateformes cloud et la supervision.
    """
    return {"status": "ok"}
