"""Test d'integration : charge reellement all-MiniLM-L6-v2.

Deselectionne par defaut (marqueur `integration`) car il telecharge environ
90 Mo au premier passage. Le lancer avec :

    pytest -m integration

C'est le seul test qui verifie que `embedding_dimension` correspond vraiment au
modele configure. Les tests unitaires, eux, verifient que l'on reagit
correctement quand ce n'est pas le cas.
"""

import pytest

from aisecassist.config import settings
from aisecassist.embeddings.sentence_transformer import SentenceTransformerEmbedder

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_le_modele_configure_produit_bien_la_dimension_attendue() -> None:
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        settings.embedding_dimension,
    )

    vectors = await embedder.embed(["injection de prompt indirecte"])

    assert len(vectors) == 1
    assert len(vectors[0]) == settings.embedding_dimension


async def test_deux_textes_proches_sont_plus_proches_que_deux_textes_eloignes() -> None:
    """Verifie que la vectorisation porte bien du sens, pas seulement la bonne forme.

    Un embedder mal branche (mauvais modele, texte tronque) peut produire des
    vecteurs de la bonne dimension tout en etant semantiquement inutile.
    """
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        settings.embedding_dimension,
    )

    vectors = await embedder.embed(
        [
            "injection de prompt dans un LLM",
            "attaque par injection de prompt",
            "recette de la tarte aux pommes",
        ]
    )
    proche, similaire, eloigne = vectors

    assert _cosine(proche, similaire) > _cosine(proche, eloigne)


def _cosine(a: list[float], b: list[float]) -> float:
    produit = sum(x * y for x, y in zip(a, b, strict=True))
    norme_a = sum(x * x for x in a) ** 0.5
    norme_b = sum(y * y for y in b) ** 0.5
    return produit / (norme_a * norme_b)
