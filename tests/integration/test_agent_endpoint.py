"""Test d'acceptation de M3 : le livrable du jalon, exerce en HTTP (ticket 21).

Deselectionne par defaut. Exige Qdrant, Ollama et un acces sortant vers la base
du NIST :

    docker compose -f docker/docker-compose.yml up -d qdrant
    ollama serve
    pytest -m integration

Les tests unitaires verifient le contrat HTTP avec un modele scripte, et
`test_agent_real_model.py` verifie que le vrai modele choisit ses outils. Celui-
ci verifie ce qu'aucun des deux ne couvre : que l'assemblage complet tient —
route, services construits au demarrage, agent, outils, et retour JSON.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aisecassist.main import app
from aisecassist.security.limits import MAX_QUESTION_LENGTH

pytestmark = [pytest.mark.integration, pytest.mark.llm, pytest.mark.network]


def test_une_question_complexe_recoit_une_reponse_multi_etapes(corpus_indexe: str) -> None:
    """Le critere d'acceptation du ticket 21, mot pour mot.

    `with TestClient(app)` declenche le cycle de vie : les vrais services sont
    construits — modele d'embeddings charge, client Qdrant ouvert, agent arme de
    ses deux outils.

    La question croise deux sources : une vulnerabilite nommee, qui appelle la
    base du NIST, et une categorie de risque, qui appelle le corpus. `iterations`
    rend le cheminement visible dans la reponse, ce qui est precisement ce que
    « multi-etapes tracee » demande.
    """
    with TestClient(app) as client:
        reponse = client.post(
            "/agent",
            json={
                "question": (
                    "Que decrit la CVE-2021-44228, et a quelle categorie du "
                    "OWASP LLM Top 10 ce type de faille se rattache-t-il ?"
                )
            },
        )

    assert reponse.status_code == 200
    corps = reponse.json()

    assert corps["answer"].strip() != ""
    assert corps["iterations"] >= 1
    # Des sources reelles : elles ne peuvent provenir que d'outils executes.
    assert corps["sources"] != []


def test_une_question_trop_longue_est_refusee_avant_tout_travail() -> None:
    """Le plafond d'entree protege aussi la porte la plus couteuse.

    Ce test ne porte pas de marqueur `llm` a titre individuel mais herite de
    celui du module ; il n'appelle de toute facon ni le modele ni Qdrant, le
    refus intervenant a la validation du schema.
    """
    with TestClient(app) as client:
        reponse = client.post("/agent", json={"question": "x" * (MAX_QUESTION_LENGTH + 1)})

    assert reponse.status_code == 422
