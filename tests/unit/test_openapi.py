"""Tests du schema OpenAPI (ticket 16).

La documentation se degrade en silence : on ajoute une route, on oublie de
decrire ses erreurs, et `/docs` laisse croire qu'un appel ne peut que reussir.
Ces tests transforment cette exigence en controle automatique.
"""

from __future__ import annotations

import json

import pytest

from aisecassist.main import app

_ROUTES_PUBLIQUES = ["/query", "/query/stream", "/agent"]


@pytest.fixture(scope="module")
def schema() -> dict:
    return app.openapi()


def test_les_metadonnees_sont_renseignees(schema: dict) -> None:
    info = schema["info"]

    assert info["title"]
    assert info["description"].strip()
    # La version vient des metadonnees du paquet : une constante en dur finirait
    # par diverger de pyproject.toml, et c'est la doc publique qui mentirait.
    assert info["version"] != "0.0.0+inconnu"


def test_les_tags_sont_decrits(schema: dict) -> None:
    tags = {t["name"]: t["description"] for t in schema["tags"]}

    assert set(tags) == {"rag", "agent", "monitoring"}
    assert all(description.strip() for description in tags.values())


@pytest.mark.parametrize("chemin", _ROUTES_PUBLIQUES)
def test_chaque_route_publique_documente_ses_erreurs(schema: dict, chemin: str) -> None:
    """Une route qui ne documente que le 200 ment sur son contrat.

    Un client n'a alors aucune raison de prevoir la validation ni la panne.
    """
    reponses = schema["paths"][chemin]["post"]["responses"]

    assert "422" in reponses, "entree invalide non documentee"
    assert "503" in reponses, "panne de dependance non documentee"
    assert all(reponses[code]["description"].strip() for code in ("422", "503"))


@pytest.mark.parametrize("chemin", _ROUTES_PUBLIQUES)
def test_chaque_route_publique_a_un_resume_explicite(schema: dict, chemin: str) -> None:
    resume = schema["paths"][chemin]["post"]["summary"]

    # FastAPI derive un resume du nom de la fonction quand on n'en fournit pas.
    # "Query" ou "Query Stream" signale un oubli, pas une intention.
    assert resume not in ("Query", "Query Stream")
    assert len(resume) > 15


def test_le_format_du_flux_sse_est_documente(schema: dict) -> None:
    """OpenAPI ne sait pas decrire une suite d'evenements, seulement un corps.

    Sans exemple, un client n'a aucun moyen de deviner le format du flux.
    """
    contenu = schema["paths"]["/query/stream"]["post"]["responses"]["200"]["content"]

    assert "text/event-stream" in contenu
    exemple = contenu["text/event-stream"]["example"]
    assert "event: sources" in exemple
    assert "event: token" in exemple
    assert "event: done" in exemple


def test_les_schemas_de_reponse_portent_un_exemple(schema: dict) -> None:
    composants = schema["components"]["schemas"]

    for nom in ("QueryResponse", "SourceRef"):
        assert "example" in composants[nom], f"{nom} sans exemple dans /docs"


def test_le_schema_est_serialisable(schema: dict) -> None:
    """Garde-fou : un schema non serialisable fait echouer /docs a l'execution."""
    assert json.dumps(schema)
