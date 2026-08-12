"""Configuration partagee par tous les tests."""

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Restreint les tests asynchrones a asyncio.

    anyio sait aussi piloter trio ; sans ce fixture il executerait chaque test
    async une fois par backend. La production tourne sur asyncio (uvicorn), le
    second passage ne prouverait rien et doublerait la duree de la suite.
    """
    return "asyncio"
