"""Tests des logs structures et de l'identifiant de requete (ticket 23).

La propriete centrale, et la raison d'etre du ticket : **un appel au module
`logging` standard, non modifie, ressort structure et porte l'identifiant de la
requete en cours**. C'est ce qui a permis d'instrumenter vingt-cinq appels
existants sans en reecrire un seul.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient

from aisecassist.main import app
from aisecassist.observability.logging import configure_logging
from aisecassist.observability.request_id import (
    EN_TETE,
    identifiant_recevable,
    nouvel_identifiant,
)


class _Journal:
    """Lit les lignes JSON emises dans le tampon de la configuration de test."""

    def __init__(self, tampon: io.StringIO) -> None:
        self.tampon = tampon

    def lignes(self) -> list[dict[str, Any]]:
        brut = self.tampon.getvalue()
        return [json.loads(ligne) for ligne in brut.splitlines() if ligne.strip()]


@pytest.fixture
def journal() -> Iterator[_Journal]:
    """Configure les logs en JSON vers un tampon, et rend un lecteur.

    La sortie est injectee plutot que capturee : pytest s'interpose entre le
    module `logging` et la sortie standard, ce qui rendrait l'assertion
    dependante du mecanisme de capture au lieu du code teste.
    """
    tampon = io.StringIO()
    configure_logging(level="INFO", json_format=True, stream=tampon)

    yield _Journal(tampon)

    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()
    logging.getLogger().handlers = []


def test_un_appel_logging_standard_ressort_en_json(journal: _Journal) -> None:
    """Le point du ticket : aucun appel existant n'a eu besoin d'etre reecrit."""
    logging.getLogger("aisecassist.retrieval.service").warning("Aucun extrait pertinent.")

    (ligne,) = journal.lignes()

    assert ligne["event"] == "Aucun extrait pertinent."
    assert ligne["level"] == "warning"
    assert ligne["logger"] == "aisecassist.retrieval.service"
    assert "timestamp" in ligne


def test_lidentifiant_de_contexte_rejoint_les_appels_standard(journal: _Journal) -> None:
    """La propagation par variable de contexte, verifiee de bout en bout.

    Le module qui journalise n'a aucune connaissance de l'identifiant : c'est
    tout l'interet de ne pas le passer en parametre.
    """
    structlog.contextvars.bind_contextvars(request_id="abc123")

    logging.getLogger("aisecassist.agents.service").info("Appel d'outil.")

    assert journal.lignes()[0]["request_id"] == "abc123"


def test_une_exception_est_rendue_avec_sa_trace(journal: _Journal) -> None:
    """La trace doit rester exploitable cote serveur — elle ne part jamais au client."""
    try:
        raise ValueError("panne interne")
    except ValueError:
        logging.getLogger("aisecassist.main").exception("Erreur inattendue")

    ligne = journal.lignes()[0]

    assert "panne interne" in ligne["exception"]
    assert ligne["level"] == "error"


def test_les_bibliotheques_bavardes_sont_calmees(journal: _Journal) -> None:
    """httpx emet un INFO par requete : avec un agent, cela noierait nos traces."""
    logging.getLogger("httpx").info("HTTP Request: POST /api/chat")

    assert journal.lignes() == []


def test_reconfigurer_ne_duplique_pas_les_lignes(journal: _Journal) -> None:
    """Un rechargement a chaud du serveur reconfigure : sans soin, tout doublerait."""
    configure_logging(level="INFO", json_format=True, stream=journal.tampon)

    logging.getLogger("aisecassist.test").info("une seule fois")

    assert len(journal.lignes()) == 1


# --- Validation de l'en-tete client -----------------------------------------


@pytest.mark.parametrize(
    "valeur",
    [
        "trace-123_ABC",
        "550e8400e29b41d4a716446655440000",
        "a",
        "x" * 64,
    ],
)
def test_un_identifiant_client_bien_forme_est_accepte(valeur: str) -> None:
    assert identifiant_recevable(valeur) == valeur


@pytest.mark.parametrize(
    "charge",
    [
        "trace\nINFO fausse ligne de journal",
        "trace\r\nlevel=critical",
        'trace" , "level":"critical',
        "trace\x00nul",
        "x" * 65,
        "",
        "trace avec espaces",
        "trace;{}",
    ],
    ids=[
        "saut-de-ligne",
        "crlf",
        "guillemets-json",
        "caractere-nul",
        "trop-long",
        "vide",
        "espaces",
        "ponctuation",
    ],
)
def test_un_identifiant_client_hostile_est_ecarte(charge: str) -> None:
    """Un en-tete client atterrit dans chaque ligne de log de la requete.

    Sans cette validation, un saut de ligne suffirait a fabriquer une ligne de
    journal entiere, qu'un agregateur lirait comme un evenement authentique.
    """
    assert identifiant_recevable(charge) is None


def test_un_identifiant_attribue_est_hexadecimal_et_unique() -> None:
    a, b = nouvel_identifiant(), nouvel_identifiant()

    assert a != b
    assert len(a) == 32
    assert all(c in "0123456789abcdef" for c in a)


# --- Bout en bout, via l'API -------------------------------------------------


def test_la_reponse_porte_lidentifiant_de_la_requete() -> None:
    """Le client doit pouvoir citer un identifiant en signalant une panne."""
    with TestClient(app) as client:
        reponse = client.get("/health")

    assert len(reponse.headers[EN_TETE]) == 32


def test_un_identifiant_fourni_par_le_client_est_repris() -> None:
    """La correlation doit traverser les frontieres de service."""
    with TestClient(app) as client:
        reponse = client.get("/health", headers={EN_TETE: "trace-du-client"})

    assert reponse.headers[EN_TETE] == "trace-du-client"


def test_un_identifiant_hostile_est_remplace_pas_renvoye() -> None:
    """Renvoyer la charge telle quelle la ferait entrer dans les logs du client."""
    with TestClient(app) as client:
        reponse = client.get("/health", headers={EN_TETE: "trace\nfausse-ligne"})

    renvoye = reponse.headers[EN_TETE]
    assert renvoye != "trace\nfausse-ligne"
    assert len(renvoye) == 32


def test_deux_requetes_recoivent_deux_identifiants() -> None:
    with TestClient(app) as client:
        a = client.get("/health").headers[EN_TETE]
        b = client.get("/health").headers[EN_TETE]

    assert a != b
