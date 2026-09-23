"""Tests des invariants de configuration.

Ces valeurs viennent de l'environnement. Une faute de frappe dans un `.env` doit
faire echouer le chargement, pas produire une panne d'execution trois couches
plus bas dont le message ne nomme meme pas la variable en cause.

**Ces tests ignorent deliberement le `.env` local** (`_env_file=None`). Sans
cela, ils affirmeraient les valeurs de la machine qui les execute : verts en CI,
qui n'a pas de `.env`, et rouges chez le developpeur qui en a un — ou pire,
verts chez les deux pour de mauvaises raisons. Un test qui depend de
l'environnement ne teste pas le code.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from aisecassist.config import Settings


def _reglages(**surcharges: Any) -> Settings:
    """Construit des reglages a partir des seuls defauts du code."""
    return Settings(_env_file=None, **surcharges)


def test_la_configuration_par_defaut_est_valide() -> None:
    settings = _reglages()

    assert settings.chunk_overlap < settings.chunk_size
    assert settings.retrieval_top_k > 0


def test_un_recouvrement_superieur_ou_egal_a_la_taille_est_refuse_au_chargement() -> None:
    """Sans ce controle, l'erreur ne surgissait qu'au premier document ingere.

    Potentiellement des heures apres le demarrage, et loin de la variable
    fautive.
    """
    with pytest.raises(ValidationError) as excinfo:
        _reglages(chunk_size=800, chunk_overlap=900)

    message = str(excinfo.value)
    assert "CHUNK_OVERLAP" in message
    assert "CHUNK_SIZE" in message


def test_un_recouvrement_egal_a_la_taille_est_refuse() -> None:
    with pytest.raises(ValidationError):
        _reglages(chunk_size=800, chunk_overlap=800)


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("retrieval_top_k", 0),
        ("retrieval_top_k", -1),
        ("chunk_size", 0),
        ("chunk_overlap", -1),
        ("embedding_dimension", 0),
        ("max_document_bytes", 0),
        ("llm_timeout_s", 0),
    ],
)
def test_les_valeurs_hors_bornes_sont_refusees(champ: str, valeur: int) -> None:
    """`RETRIEVAL_TOP_K=0` demarrait sans un mot, puis chaque requete finissait en 503."""
    with pytest.raises(ValidationError):
        _reglages(**{champ: valeur})


@pytest.mark.parametrize("seuil", [-1.01, 1.01, 64])
def test_un_seuil_de_pertinence_hors_de_lechelle_cosinus_est_refuse(seuil: float) -> None:
    """`RETRIEVAL_MIN_SCORE=64` — un pourcentage au lieu d'une similarite — refuserait tout.

    Chaque question recevrait « le corpus ne contient rien », sans la moindre
    erreur : la panne ressemblerait a un corpus vide.
    """
    with pytest.raises(ValidationError):
        _reglages(retrieval_min_score=seuil)


def test_une_revision_de_modele_vide_est_refusee() -> None:
    """Une revision vide reviendrait a suivre la derniere version publiee du modele.

    Le seuil de pertinence est calibre sur des poids precis (ADR-0010).
    """
    with pytest.raises(ValidationError):
        _reglages(embedding_model_revision="")


def test_lidentifiant_du_modele_inclut_la_revision() -> None:
    """C'est cet identifiant que la collection enregistre et verifie."""
    settings = _reglages(embedding_model="org/modele", embedding_model_revision="abc123")

    assert settings.embedding_model_id == "org/modele@abc123"


# --- Choix du fournisseur de modele (ticket 26, ADR-0013) --------------------


def test_un_fournisseur_heberge_sans_cle_est_refuse_au_demarrage() -> None:
    """Sans cette regle, la panne n'apparaitrait qu'a la premiere question.

    L'application demarrerait, `/health` repondrait 200, et l'utilisateur
    recevrait un 503 generique — dont le message ne nomme volontairement pas la
    cause. Autant refuser au chargement, la ou on peut encore nommer la
    variable manquante.
    """
    with pytest.raises(ValidationError, match="HOSTED_LLM_API_KEY"):
        _reglages(llm_provider="hosted", hosted_llm_api_key=None)


def test_le_fournisseur_local_reste_le_defaut() -> None:
    """La CI et les tests d'integration en dependent : ils n'ont aucune cle."""
    assert _reglages().llm_provider == "ollama"


def test_un_fournisseur_inconnu_est_refuse() -> None:
    """Une faute de frappe dans `LLM_PROVIDER` ne doit pas retomber sur un defaut."""
    with pytest.raises(ValidationError):
        _reglages(llm_provider="grok")


def test_un_fournisseur_heberge_avec_cle_est_accepte() -> None:
    settings = _reglages(llm_provider="hosted", hosted_llm_api_key="gsk_fictive_pour_le_test")

    assert settings.hosted_llm_base_url.startswith("https://")
