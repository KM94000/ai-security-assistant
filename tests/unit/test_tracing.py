"""Tests de la couche de tracage (ticket 24).

Aucun service : le client Langfuse est remplace par un double qui enregistre ce
qu'on lui envoie. C'est ce qui permet de verifier la propriete la plus
importante — ce qui part dans une trace est assaini — sans monter cinq
conteneurs.

Deux exigences structurent ce fichier :

1. **Desactive, le tracage n'a aucun effet.** Ni cout, ni exception, ni
   changement de comportement. C'est ce qui autorise a poser des appels
   `traced(...)` dans le chemin des requetes.
2. **Actif, il ne fait jamais tomber ce qu'il observe.** Un traceur en panne
   reste un traceur en panne, pas une panne du produit.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest

from aisecassist.observability import tracing
from aisecassist.observability.tracing import (
    configure_tracing,
    shutdown_tracing,
    traced,
    tracing_actif,
)
from aisecassist.security.output_guardrail import REMPLACEMENT


class _SpanFactice:
    def __init__(self, journal: list[dict[str, Any]]) -> None:
        self._journal = journal

    def update(self, **valeurs: Any) -> None:
        self._journal.append(valeurs)

    def __enter__(self) -> _SpanFactice:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _ClientFactice:
    """Double du client Langfuse : retient les entrees et les sorties vues."""

    def __init__(self) -> None:
        self.ouvertures: list[dict[str, Any]] = []
        self.mises_a_jour: list[dict[str, Any]] = []

    def start_as_current_observation(self, **kwargs: Any) -> _SpanFactice:
        self.ouvertures.append(kwargs)
        return _SpanFactice(self.mises_a_jour)

    def shutdown(self) -> None:
        return None


@pytest.fixture
def client() -> Iterator[_ClientFactice]:
    """Active le tracage avec un client factice."""
    double = _ClientFactice()
    tracing._client = double
    yield double
    tracing._client = None


@pytest.fixture(autouse=True)
def _tracage_propre() -> Iterator[None]:
    yield
    tracing._client = None


# --- Desactive : un vrai no-op -----------------------------------------------


def test_sans_configuration_le_tracage_est_inactif() -> None:
    assert tracing_actif() is False


def test_desactive_le_bloc_sexecute_normalement() -> None:
    """La propriete qui autorise a instrumenter le chemin des requetes."""
    execute = False

    with traced("etape", question="q") as span:
        execute = True
        span.sortie(reponse="r")

    assert execute


def test_desactive_aucune_exception_ne_remonte() -> None:
    """Meme mal utilise, le tracage ne doit pas casser l'appelant."""
    with traced("etape", objet=object()) as span:
        span.sortie(autre=object())


def test_une_configuration_sans_cles_reste_inactive(caplog: pytest.LogCaptureFixture) -> None:
    """Une configuration incomplete ne doit pas empecher le service de demarrer.

    Le tracage est un confort d'exploitation, pas une fonction du produit.
    Faire echouer le demarrage pour lui reviendrait a le rendre plus critique
    que ce qu'il observe.
    """
    with caplog.at_level(logging.WARNING):
        actif = configure_tracing(
            enabled=True, host="http://localhost:3000", public_key=None, secret_key=None
        )

    assert actif is False
    assert "LANGFUSE_PUBLIC_KEY" in caplog.text


def test_desactive_explicitement_aucune_tentative() -> None:
    assert (
        configure_tracing(
            enabled=False, host="http://localhost:3000", public_key="pk", secret_key="sk"
        )
        is False
    )


def test_arreter_un_tracage_inactif_ne_leve_rien() -> None:
    shutdown_tracing()


# --- Actif : ce qui part, et ce qui n'en part pas ---------------------------


def test_les_entrees_et_sorties_sont_transmises(client: _ClientFactice) -> None:
    with traced("retrieval", k=5, seuil=0.64) as span:
        span.sortie(retenus=2)

    assert client.ouvertures[0]["name"] == "retrieval"
    assert client.ouvertures[0]["input"] == {"k": 5, "seuil": 0.64}
    assert client.mises_a_jour[0]["output"] == {"retenus": 2}


def test_un_secret_est_redige_avant_de_partir(client: _ClientFactice) -> None:
    """Une trace est une seconde sortie du systeme, vers un autre destinataire.

    Le guardrail a ete ecrit pour les reponses ; il merite de s'appliquer ici
    aussi. Sans cela, un secret ecarte de la reponse repartirait par la trace.
    """
    secret = "sk-" + "a1b2c3d4" * 4  # forme de cle, construite ici

    with traced("generation", prompt=f"La cle est {secret}") as span:
        span.sortie(reponse=f"Voici {secret}")

    envoye = client.ouvertures[0]["input"]["prompt"]
    rendu = client.mises_a_jour[0]["output"]["reponse"]
    assert secret not in envoye
    assert secret not in rendu
    assert REMPLACEMENT in envoye


def test_une_cle_de_fournisseur_est_redigee(client: _ClientFactice) -> None:
    """Le secret que le produit detient lui-meme (SEC-02, SEC-12)."""
    cle = "gsk_" + "b" * 40

    with traced("chat", entete=f"Bearer {cle}"):
        pass

    assert cle not in client.ouvertures[0]["input"]["entete"]


def test_une_valeur_demesuree_est_plafonnee(client: _ClientFactice) -> None:
    """Une trace n'est pas un entrepot : un document entier y serait illisible."""
    with traced("ingestion", document="x" * 50_000):
        pass

    envoye = client.ouvertures[0]["input"]["document"]
    assert len(envoye) < 5_000
    assert envoye.endswith("[…]")


def test_les_structures_imbriquees_sont_assainies(client: _ClientFactice) -> None:
    """Les sources et les extraits arrivent en listes de dictionnaires."""
    secret = "sk-" + "c1d2e3f4" * 4

    with traced("retrieval") as span:
        span.sortie(retenus=[{"source": "a.md", "extrait": f"contient {secret}"}])

    rendu = client.mises_a_jour[0]["output"]["retenus"][0]["extrait"]
    assert secret not in rendu


# --- Actif mais en panne : le produit continue -------------------------------


def test_une_panne_a_louverture_nempeche_pas_le_bloc(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class ClientCasse:
        def start_as_current_observation(self, **kwargs: Any) -> Any:
            raise RuntimeError("collecteur injoignable")

    tracing._client = ClientCasse()
    execute = False

    with caplog.at_level(logging.WARNING):
        with traced("etape", question="q") as span:
            execute = True
            span.sortie(reponse="r")

    assert execute
    assert "Ouverture d'une trace echouee" in caplog.text


def test_une_panne_a_lecriture_nempeche_pas_le_bloc(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class SpanCasse:
        def update(self, **valeurs: Any) -> None:
            raise RuntimeError("envoi refuse")

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    class Client:
        def start_as_current_observation(self, **kwargs: Any) -> Any:
            return SpanCasse()

    tracing._client = Client()

    with caplog.at_level(logging.WARNING):
        with traced("etape") as span:
            span.sortie(reponse="r")

    assert "Ecriture d'une trace echouee" in caplog.text


def test_une_panne_a_larret_ne_leve_rien(caplog: pytest.LogCaptureFixture) -> None:
    class Client:
        def shutdown(self) -> None:
            raise RuntimeError("deja ferme")

    tracing._client = Client()

    with caplog.at_level(logging.WARNING):
        shutdown_tracing()

    assert tracing_actif() is False
