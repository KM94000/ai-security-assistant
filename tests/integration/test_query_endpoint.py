"""Test d'acceptation de M1 : la chaine complete, du HTTP a la reponse sourcee.

Deselectionne par defaut. Exige Qdrant demarre, et Ollama pour les tests
marques `llm` :

    docker compose -f docker/docker-compose.yml up -d qdrant
    ollama serve
    pytest -m integration

C'est le seul test qui exerce reellement le livrable de M1 : une question part
en HTTP, traverse la validation, la vectorisation, la recherche, l'assemblage du
prompt et le modele, et revient accompagnee de ses sources. Les tests unitaires
verifient chaque etage ; celui-ci verifie qu'ils sont branches ensemble.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aisecassist.generation.prompt import REFUS_SANS_CONTEXTE
from aisecassist.main import app

pytestmark = pytest.mark.integration


@pytest.mark.llm
def test_une_question_reelle_recoit_une_reponse_sourcee(corpus_indexe: str) -> None:
    """Le livrable de M1, verifie de bout en bout.

    `with TestClient(app)` declenche le lifespan : les vrais services sont
    construits, le vrai modele est charge et le vrai Ollama est interroge.
    """
    with TestClient(app) as client:
        reponse = client.post(
            "/query",
            json={"question": "Comment se defendre contre une injection de prompt indirecte ?"},
        )

    assert reponse.status_code == 200
    corps = reponse.json()

    # Une reponse non vide, et surtout des sources : sans provenance, la reponse
    # d'un outil de securite n'est pas verifiable, donc pas utilisable.
    assert corps["answer"].strip() != ""
    assert corps["sources"] != []
    assert any(source["source"] == "owasp-llm-top10.md" for source in corps["sources"])


def test_une_question_hors_corpus_donne_un_refus_sans_appeler_le_modele(
    corpus_indexe: str,
) -> None:
    """La parade a la desinformation : refuser plutot que supposer (LLM09, ADR-0010).

    Avant le seuil de pertinence, ce test ne pouvait exiger qu'une reponse « non
    vide » : la recherche renvoyait toujours ses k extraits, meme pour une
    recette de cuisine, et le modele etait interroge avec un contexte hors sujet.
    Il exige desormais le refus explicite, sans aucune source.

    Il n'est pas marque `llm` et tourne donc en CI, ou aucun Ollama n'ecoute :
    c'est voulu. Sans extrait retenu, le modele n'est pas appele. Si le seuil
    cessait de filtrer, l'appel partirait vers un serveur absent, la route
    repondrait 503, et le test echouerait bruyamment plutot que de passer par
    hasard.
    """
    with TestClient(app) as client:
        reponse = client.post(
            "/query",
            json={"question": "Quelle est la recette traditionnelle du cassoulet ?"},
        )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["answer"] == REFUS_SANS_CONTEXTE
    assert corps["sources"] == []
