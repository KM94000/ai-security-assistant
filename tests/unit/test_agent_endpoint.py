"""Tests de la route POST /agent (ticket 21).

Aucun modele ne tourne : le service d'agent est reel, mais son fournisseur est
un double qui rejoue un script. Ce qui est verifie ici, c'est le contrat HTTP —
ce qui entre, ce qui sort, et ce qui se passe quand ca tourne mal.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from aisecassist.agents.service import AgentService
from aisecassist.api.deps import Services, get_services
from aisecassist.api.messages import MESSAGE_AGENT_TROP_LONG, MESSAGE_INDISPONIBLE
from aisecassist.llm.base import ChatReply, LLMError, ToolCall, ToolCallingProvider
from aisecassist.main import app
from aisecassist.security.limits import MAX_QUESTION_LENGTH
from tests.doubles import ExplodingChatLLM, FakeTool, ScriptedChatLLM, SlowChatLLM


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Rend un client dont l'agent repond immediatement, sans outil."""
    yield from _client_avec(ScriptedChatLLM([ChatReply(text="Une reponse directe.")]))


def _client_avec(
    llm: ToolCallingProvider,
    *outils: FakeTool,
    timeout_s: float = 5.0,
) -> Iterator[TestClient]:
    agent = AgentService(
        llm,
        outils or (FakeTool(),),
        max_iterations=3,
        max_answer_chars=8_000,
        timeout_s=timeout_s,
    )
    services = Services(
        retrieval=cast(Any, None),
        generation=cast(Any, None),
        agent=agent,
        store=cast(Any, None),
        llm=cast(Any, None),
        cve=cast(Any, None),
    )
    # TestClient sans gestionnaire de contexte : le lifespan ne demarre pas,
    # donc aucun vrai modele ni client Qdrant n'est construit.
    app.dependency_overrides[get_services] = lambda: services
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_une_question_recoit_une_reponse_avec_ses_sources() -> None:
    outil = FakeTool(name="rechercher_corpus", sources=("owasp-llm-top10.md",))
    llm = ScriptedChatLLM(
        [
            ChatReply(
                text="",
                tool_calls=(ToolCall(name="rechercher_corpus", arguments={"question": "q"}),),
            ),
            ChatReply(text="L'injection indirecte passe par un document ingere."),
        ]
    )

    for client in _client_avec(llm, outil):
        reponse = client.post("/agent", json={"question": "Qu'est-ce qu'une injection ?"})

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["answer"] == "L'injection indirecte passe par un document ingere."
    assert corps["sources"] == ["owasp-llm-top10.md"]
    assert corps["iterations"] == 1


def test_une_reponse_sans_outil_annonce_zero_iteration(client: TestClient) -> None:
    """`iterations` rend le cheminement visible, y compris quand il est vide.

    Zero signifie que le modele a repondu de lui-meme. C'est une information
    utile : une reponse sans source ni iteration n'engage que le modele.
    """
    corps = client.post("/agent", json={"question": "bonjour"}).json()

    assert corps["iterations"] == 0
    assert corps["sources"] == []


@pytest.mark.parametrize(
    "charge",
    [
        {},
        {"question": ""},
        {"question": "   "},
        {"question": "x" * (MAX_QUESTION_LENGTH + 1)},
        {"question": ["une", "liste"]},
        {"question": "valide", "max_iterations": 99},
    ],
    ids=["absente", "vide", "espaces", "trop-longue", "mauvais-type", "champ-inattendu"],
)
def test_une_entree_invalide_donne_un_422(client: TestClient, charge: dict[str, object]) -> None:
    """Le meme schema que `/query` : l'agent n'est pas une porte aux regles plus souples.

    `max_iterations` en dernier cas n'est pas un hasard : c'est precisement le
    genre de parametre qu'un client curieux tenterait de pousser pour relever
    un plafond de securite. `extra="forbid"` le refuse.
    """
    assert client.post("/agent", json=charge).status_code == 422


def test_une_panne_du_modele_donne_un_503_generique() -> None:
    """Meme traitement que `/query` : la panne est journalisee, jamais decrite."""
    for client in _client_avec(ExplodingChatLLM(LLMError("Ollama injoignable sur 11434"))):
        reponse = client.post("/agent", json={"question": "question"})

    assert reponse.status_code == 503
    assert reponse.json() == {"detail": MESSAGE_INDISPONIBLE}


def test_un_agent_trop_long_donne_un_504_et_pas_un_503() -> None:
    """La distinction est faite pour le client, pas pour la forme.

    Un 503 invite a reessayer a l'identique ; ici cela ne servirait a rien. Le
    504 dit que le traitement a ete trop long, et le message oriente vers la
    seule action utile — reformuler.
    """
    for client in _client_avec(SlowChatLLM(delai_s=30.0), timeout_s=0.05):
        reponse = client.post("/agent", json={"question": "question interminable"})

    assert reponse.status_code == 504
    assert reponse.json() == {"detail": MESSAGE_AGENT_TROP_LONG}
