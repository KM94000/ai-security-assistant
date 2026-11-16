"""Tests du decoupage en fragments.

Fonction pure : aucun mock, aucune I/O. Un mauvais decoupage ne plante pas, il
degrade la pertinence en silence — d'ou l'insistance sur les invariants.
"""

from __future__ import annotations

import pytest

from aisecassist.ingestion.chunker import ChunkingError, chunk_document, chunk_text


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


def test_toutes_les_queues_redondantes_sont_retirees() -> None:
    """Non-regression : un seul `pop()` ne suffisait pas.

    Avec un recouvrement eleve, plusieurs fragments de fin sont entierement
    contenus dans leurs predecesseurs. Une premiere version n'en retirait qu'un,
    et les quasi-doublons restants pouvaient occuper plusieurs places du top-k
    pour le meme passage, evincant d'autres sources.
    """
    fragments = chunk_text("abcdefghij", chunk_size=8, overlap=6)

    for precedent, suivant in zip(fragments, fragments[1:], strict=False):
        assert suivant not in precedent, f"{suivant!r} est redondant avec {precedent!r}"


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


# --- Decoupage conscient de la structure (ticket 41) -------------------------
#
# Ce que ces tests figent n'est pas une preference de style : c'est la raison
# pour laquelle le seuil de pertinence fonctionne a nouveau. Un fragment a
# cheval sur deux sections est une moyenne semantique de deux sujets, donc
# proche du centre de l'espace vectoriel, donc proche de n'importe quel texte
# generique. C'est ce qui avait fait remonter « Bonjour, comment vas-tu ? » a
# 0,651 et annule toute separation (ADR-0010, reevaluation du ticket 41).

_DOCUMENT = """# Titre du document

Introduction du document.

## Premiere section

Contenu de la premiere section.

## Deuxieme section

Contenu de la deuxieme section.
"""


def test_chaque_section_donne_un_fragment() -> None:
    fragments = chunk_document(_DOCUMENT, 1_000, 100)

    assert len(fragments) == 3  # l'introduction compte pour une section
    assert "Premiere section" in fragments[1]
    assert "Deuxieme section" in fragments[2]


def test_une_section_nest_pas_coupee_si_elle_tient() -> None:
    fragments = chunk_document(_DOCUMENT, 1_000, 100)

    entiere = next(f for f in fragments if "Premiere section" in f)
    assert "Contenu de la premiere section." in entiere


def test_chaque_fragment_porte_le_titre_du_document() -> None:
    """C'est ce prefixe qui eloigne les fragments du texte generique."""
    for fragment in chunk_document(_DOCUMENT, 1_000, 100):
        assert fragment.startswith("Titre du document")


def test_le_titre_napparait_pas_deux_fois() -> None:
    """Le repeter diluerait l'embedding sans rien apporter."""
    fragments = chunk_document(_DOCUMENT, 1_000, 100)

    assert fragments[0].count("Titre du document") == 1


def test_un_document_sans_titre_nest_pas_prefixe() -> None:
    sans_titre = "## Une section\n\nDu contenu."

    assert chunk_document(sans_titre, 1_000, 100) == ["## Une section\n\nDu contenu."]


def test_un_document_sans_section_retombe_sur_la_fenetre_glissante() -> None:
    """Le comportement d'origine reste la pour tout ce qui n'est pas structure."""
    plat = "a" * 2_000

    assert chunk_document(plat, 800, 120) == chunk_text(plat, 800, 120)


def test_les_sous_sections_restent_dans_leur_section() -> None:
    """Une sous-partie sans sa partie perd le contexte qu'on cherche a garder."""
    texte = "# T\n\n## Section\n\nAvant.\n\n### Sous-partie\n\nApres.\n"

    fragments = chunk_document(texte, 1_000, 100)

    assert len(fragments) == 1
    assert "Sous-partie" in fragments[0]


def test_une_section_trop_longue_est_coupee_sur_des_phrases() -> None:
    phrase = "Ceci est une phrase de longueur raisonnable. "
    texte = f"# T\n\n## S\n\n{phrase * 40}"

    fragments = chunk_document(texte, 600, 100)

    assert len(fragments) > 1
    # Aucun fragment ne commence au milieu d'un mot : c'est tout l'enjeu.
    for fragment in fragments:
        corps = fragment.split("\n\n", 1)[1]
        assert corps.startswith(("##", "Ceci"))


def test_aucun_fragment_ne_depasse_la_taille_demandee() -> None:
    """Le prefixe est compte dans le budget, sinon le plafond n'en est pas un."""
    texte = "# Un titre assez long pour peser\n\n## S\n\n" + "Phrase courte. " * 100

    for fragment in chunk_document(texte, 500, 50):
        assert len(fragment) <= 500


def test_une_phrase_unique_trop_longue_ne_bloque_pas() -> None:
    """Aucun decoupage par phrases ne peut la faire tenir : repli sur la fenetre."""
    texte = "# T\n\n## S\n\n" + "x" * 3_000

    fragments = chunk_document(texte, 400, 50)

    assert len(fragments) > 1
    assert all(len(f) <= 400 for f in fragments)


def test_un_document_vide_ne_donne_aucun_fragment() -> None:
    assert chunk_document("   \n\n  ", 800, 120) == []


def test_les_parametres_incoherents_sont_refuses_comme_pour_la_fenetre() -> None:
    with pytest.raises(ChunkingError):
        chunk_document("# T\n\n## S\n\ntexte", 100, 100)
