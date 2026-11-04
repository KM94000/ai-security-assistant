"""Configuration partagee par tous les tests."""

from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Restreint les tests asynchrones a asyncio.

    anyio sait aussi piloter trio ; sans ce fixture il executerait chaque test
    async une fois par backend. La production tourne sur asyncio (uvicorn), le
    second passage ne prouverait rien et doublerait la duree de la suite.
    """
    return "asyncio"


@pytest.fixture(autouse=True, scope="session")
def _tracage_neutralise() -> Iterator[None]:
    """Coupe le tracage pour toute la suite, quoi que dise le `.env` local.

    Sans cela, un developpeur qui a active Langfuse sur son poste voit la suite
    ouvrir une connexion reelle a chaque test qui demarre l'application — lente,
    et dependante d'un service qui n'a rien a voir avec ce qui est teste. La CI,
    elle, n'a pas de `.env` et passerait : le test serait vert ou rouge selon la
    machine, pas selon le code.

    C'est la meme lecon que pour les tests de configuration, generalisee : **un
    test ne doit jamais dependre de l'environnement de celui qui l'execute.**
    Les tests qui veulent verifier le tracage installent leur propre double.
    """
    from aisecassist.config import settings

    patch = pytest.MonkeyPatch()
    patch.setattr(settings, "langfuse_enabled", False)
    yield
    patch.undo()
