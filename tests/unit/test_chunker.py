"""Tests du decoupage en fragments.

Fonction pure : aucun mock, aucune I/O. Un mauvais decoupage ne plante pas, il
degrade la pertinence en silence — d'ou l'insistance sur les invariants.
"""

from __future__ import annotations

import pytest

from aisecassist.ingestion.chunker import ChunkingError, chunk_text


def test_un_texte_plus_court_que_la_fenetre_donne_un_seul_fragment() -> None:
    assert chunk_text("abc", chunk_size=10, overlap=2) == ["abc"]


def test_un_texte_vide_ne_donne_aucun_fragment() -> None:
    assert chunk_text("", chunk_size=10, overlap=2) == []


def test_le_decoupage_couvre_tout_le_texte() -> None:
    fragments = chunk_text("abcdefghij", chunk_size=4, overlap=1)

    assert fragments == ["abcd", "defg", "ghij"]


def test_chaque_fragment_reprend_la_fin_du_precedent() -> None:
    """Sans recouvrement, une phrase a cheval sur deux fragments devient introuvable."""
    fragments = chunk_text("abcdefghij", chunk_size=4, overlap=1)

    for precedent, suivant in zip(fragments[:-1], fragments[1:], strict=True):
        assert suivant[0] == precedent[-1]


def test_aucun_fragment_vide_ou_blanc_nest_produit() -> None:
    fragments = chunk_text("a\n\n\n   \n\nb", chunk_size=3, overlap=1)

    assert all(fragment.strip() for fragment in fragments)


def test_une_taille_de_fragment_non_positive_est_refusee() -> None:
    with pytest.raises(ChunkingError):
        chunk_text("texte", chunk_size=0, overlap=0)


def test_un_recouvrement_negatif_est_refuse() -> None:
    with pytest.raises(ChunkingError):
        chunk_text("texte", chunk_size=10, overlap=-1)


def test_un_recouvrement_superieur_ou_egal_a_la_fenetre_est_refuse() -> None:
    """Garde-fou contre une boucle infinie.

    Si le recouvrement egale la taille du fragment, la fenetre n'avance jamais :
    le decoupage produirait indefiniment le meme fragment jusqu'a saturer la
    memoire. Ces deux valeurs viennent de la configuration, donc de l'exterieur.
    """
    with pytest.raises(ChunkingError):
        chunk_text("texte", chunk_size=5, overlap=5)

    with pytest.raises(ChunkingError):
        chunk_text("texte", chunk_size=5, overlap=9)
