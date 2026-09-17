"""SEC-11 — gestion des erreurs et absence de fuite d'information.

Reference : docs/SECURITY.md, matrice section 6.
Attendu : 4xx propre sur entree malformee, sortie echappee, aucune trace
d'exception ni detail interne renvoye au client.

Une trace exposee renseigne un attaquant sur la pile logicielle, les chemins du
serveur et les versions installees — c'est du travail de reconnaissance offert.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from aisecassist.api.deps import Services, get_services
from aisecassist.generation.service import GenerationService
from aisecassist.llm.base import LLMError
from aisecassist.main import app
from aisecassist.retrieval.service import RetrievalService
from aisecassist.vectorstore.base import VectorStoreError
from tests.doubles import (
    ExplodingLLM,
    ExplodingVectorStore,
    FakeLLM,
    FakeVectorStore,
    StreamingLLM,
    extrait,
    make_generation,
    make_retrieval,
)

# Marqueurs qui trahiraient une fuite d'information interne dans une reponse.
_FUITES = (
    "Traceback",
    'File "',
    "aisecassist",
    "httpx",
    "qdrant",
    "sentence_transformers",
    "localhost",
    "6333",
    "11434",
)


def _services(retrieval: RetrievalService, generation: GenerationService) -> Services:
    return Services(
        retrieval=retrieval,
        generation=generation,
        store=cast(Any, None),
        llm=cast(Any, None),
    )


def _client(services: Services) -> TestClient:
    # TestClient sans gestionnaire de contexte : le lifespan ne demarre pas,
    # donc aucun vrai modele ni client Qdrant n'est construit.
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


@pytest.fixture(autouse=True)
def _nettoyer_les_surcharges() -> Any:
    yield
    app.dependency_overrides.clear()


def _assert_sans_fuite(corps: str) -> None:
    for marqueur in _FUITES:
        assert marqueur not in corps, f"fuite d'information interne : {marqueur!r}"


# --- Entrees malformees : 4xx propre ---------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},  # champ absent
        {"question": ""},  # vide
        {"question": "   "},  # blanc, doit etre rogne puis refuse
        {"question": "x" * 2_001},  # au-dela du plafond
        {"question": "valide", "inattendu": "valeur"},  # champ non prevu
        {"question": 42},  # mauvais type
        {"question": None},
    ],
)
def test_une_entree_malformee_donne_un_422_sans_fuite(payload: dict[str, object]) -> None:
    services = _services(
        make_retrieval(FakeVectorStore()),
        make_generation(FakeLLM()),
    )

    reponse = _client(services).post("/query", json=payload)

    assert reponse.status_code == 422
    _assert_sans_fuite(reponse.text)


def test_un_corps_qui_nest_pas_du_json_donne_un_422() -> None:
    services = _services(
        make_retrieval(FakeVectorStore()),
        make_generation(FakeLLM()),
    )

    reponse = _client(services).post(
        "/query",
        content=b"pas du json",
        headers={"Content-Type": "application/json"},
    )

    assert reponse.status_code == 422
    _assert_sans_fuite(reponse.text)


# --- Pannes de dependance : 503 generique ----------------------------------


def test_une_panne_du_modele_donne_un_503_sans_detail_interne() -> None:
    """Le message d'erreur d'Ollama ne doit pas atteindre le client."""
    services = _services(
        make_retrieval(FakeVectorStore([extrait("contenu")])),
        make_generation(ExplodingLLM(LLMError("connexion refusee sur http://localhost:11434"))),
    )

    reponse = _client(services).post("/query", json={"question": "question"})

    assert reponse.status_code == 503
    assert "connexion refusee" not in reponse.text
    _assert_sans_fuite(reponse.text)


def test_une_panne_de_la_base_vectorielle_donne_un_503_sans_detail_interne() -> None:
    services = _services(
        make_retrieval(
            ExplodingVectorStore(VectorStoreError("qdrant injoignable sur http://localhost:6333")),
        ),
        make_generation(FakeLLM()),
    )

    reponse = _client(services).post("/query", json={"question": "question"})

    assert reponse.status_code == 503
    assert "injoignable" not in reponse.text
    _assert_sans_fuite(reponse.text)


# --- Contenu hostile dans la question --------------------------------------


def test_une_charge_xss_dans_la_question_ne_ressort_pas_telle_quelle() -> None:
    """La reponse est du JSON : le contenu doit y etre encode, jamais interprete.

    Le vrai risque est en aval — une interface qui injecterait cette valeur dans
    du HTML. On verifie ici que la couche API ne renvoie pas la charge dans un
    contexte ou elle serait executable, et que le type de contenu est bien JSON.
    """
    charge = "<script>alert('xss')</script>"
    services = _services(
        make_retrieval(FakeVectorStore([extrait("contenu")])),
        make_generation(FakeLLM("reponse neutre")),
    )

    reponse = _client(services).post("/query", json={"question": charge})

    assert reponse.status_code == 200
    assert reponse.headers["content-type"].startswith("application/json")
    assert charge not in reponse.json()["answer"]


def test_une_question_de_longueur_maximale_est_acceptee() -> None:
    """La borne doit etre inclusive : rejeter la valeur limite serait un faux positif."""
    services = _services(
        make_retrieval(FakeVectorStore([extrait("contenu")])),
        make_generation(FakeLLM()),
    )

    reponse = _client(services).post("/query", json={"question": "x" * 2_000})

    assert reponse.status_code == 200


# --- Cas nominal ------------------------------------------------------------


def test_une_question_valide_renvoie_une_reponse_sourcee() -> None:
    services = _services(
        make_retrieval(
            FakeVectorStore([extrait("Valider les entrees.", source="owasp.md", score=0.87)]),
        ),
        make_generation(FakeLLM("Il faut valider les entrees.")),
    )

    reponse = _client(services).post("/query", json={"question": "Comment mitiger une XSS ?"})

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["answer"] == "Il faut valider les entrees."
    assert corps["sources"] == [{"source": "owasp.md", "score": 0.87}]


def test_sans_extrait_pertinent_la_reponse_est_un_refus_explicite() -> None:
    """Mieux vaut refuser que supposer : c'est la parade a la desinformation (LLM09)."""
    services = _services(
        make_retrieval(FakeVectorStore([])),
        make_generation(FakeLLM()),
    )

    reponse = _client(services).post("/query", json={"question": "sujet absent du corpus"})

    assert reponse.status_code == 200
    corps = reponse.json()
    assert "ne contient aucun extrait pertinent" in corps["answer"]
    assert corps["sources"] == []


# --- Chemin streame : les memes garanties -----------------------------------
#
# Une fois le flux ouvert, le statut 200 et les en-tetes sont deja partis : les
# gestionnaires d'exception de l'application ne peuvent plus s'appliquer. Sans
# rattrapage explicite dans le generateur, le chemin streame laisserait fuiter
# ce que le chemin classique masque.


def _evenements(corps: str) -> list[tuple[str, dict[str, Any]]]:
    """Decoupe un corps SSE en couples (nom d'evenement, charge decodee)."""
    resultats: list[tuple[str, dict[str, Any]]] = []
    for bloc in corps.strip().split("\n\n"):
        lignes = bloc.splitlines()
        nom = next(li.removeprefix("event: ") for li in lignes if li.startswith("event: "))
        charge = next(li.removeprefix("data: ") for li in lignes if li.startswith("data: "))
        resultats.append((nom, json.loads(charge)))
    return resultats


def test_le_flux_emet_les_sources_puis_les_fragments_puis_la_fin() -> None:
    services = _services(
        make_retrieval(
            FakeVectorStore([extrait("Valider.", source="owasp.md", score=0.87)]),
        ),
        make_generation(StreamingLLM(["Il ", "faut ", "valider."])),
    )

    reponse = _client(services).post("/query/stream", json={"question": "Comment ?"})

    assert reponse.status_code == 200
    assert reponse.headers["content-type"].startswith("text/event-stream")

    evenements = _evenements(reponse.text)
    noms = [nom for nom, _ in evenements]

    # L'ordre structurel est contractuel : les sources d'abord, `done` en
    # dernier. Le nombre d'evenements `token`, lui, ne l'est pas — le guardrail
    # de sortie regroupe les fragments courts dans sa fenetre de retenue.
    assert noms[0] == "sources"
    assert noms[-1] == "done"
    assert set(noms[1:-1]) == {"token"}
    assert evenements[0][1]["sources"] == [{"source": "owasp.md", "score": 0.87}]
    assert "".join(charge["text"] for nom, charge in evenements if nom == "token") == (
        "Il faut valider."
    )


def test_une_panne_pendant_le_flux_devient_un_evenement_erreur_sans_fuite() -> None:
    """Le cas que les gestionnaires d'exception ne peuvent plus attraper."""
    services = _services(
        make_retrieval(FakeVectorStore([extrait("contenu")])),
        make_generation(ExplodingLLM(LLMError("connexion refusee sur http://localhost:11434"))),
    )

    reponse = _client(services).post("/query/stream", json={"question": "question"})

    # Le statut reste 200 : les en-tetes etaient deja partis quand la panne est
    # survenue. C'est l'evenement qui porte l'erreur, pas le code HTTP.
    assert reponse.status_code == 200

    evenements = _evenements(reponse.text)
    noms = [nom for nom, _ in evenements]
    assert "error" in noms
    assert "done" not in noms, "le flux ne doit pas se declarer termine apres une panne"

    detail = next(charge["detail"] for nom, charge in evenements if nom == "error")
    assert "connexion refusee" not in detail
    _assert_sans_fuite(reponse.text)


def test_une_entree_malformee_sur_le_flux_donne_un_422_avant_ouverture() -> None:
    """La validation precede l'ouverture du flux : un 4xx reste possible."""
    services = _services(
        make_retrieval(FakeVectorStore()),
        make_generation(FakeLLM()),
    )

    reponse = _client(services).post("/query/stream", json={"question": ""})

    assert reponse.status_code == 422
    _assert_sans_fuite(reponse.text)


def test_une_panne_de_recherche_sur_le_flux_donne_un_503_avant_ouverture() -> None:
    """La recherche a lieu avant d'ouvrir le flux, deliberement.

    Tant que rien n'est emis, une panne se traduit encore par un 503 propre.
    """
    services = _services(
        make_retrieval(
            ExplodingVectorStore(VectorStoreError("qdrant injoignable sur http://localhost:6333")),
        ),
        make_generation(FakeLLM()),
    )

    reponse = _client(services).post("/query/stream", json={"question": "question"})

    assert reponse.status_code == 503
    _assert_sans_fuite(reponse.text)
