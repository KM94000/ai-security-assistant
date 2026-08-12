"""Tests du chargement de documents, cas nominaux.

Les cas de rejet — trop gros, mauvais type, binaire — sont dans
`tests/security/test_sec13_ingestion_limits.py`, avec leur identifiant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aisecassist.ingestion.loader import IngestionError, iter_corpus, load_document


def test_charge_un_markdown_et_conserve_son_nom_comme_source(tmp_path: Path) -> None:
    fichier = tmp_path / "owasp-llm.md"
    fichier.write_text("Contenu de reference.", encoding="utf-8")

    document = load_document(fichier, max_bytes=1_000)

    assert document.source == "owasp-llm.md"
    assert document.text == "Contenu de reference."


def test_charge_aussi_les_fichiers_texte(tmp_path: Path) -> None:
    fichier = tmp_path / "notes.txt"
    fichier.write_text("note", encoding="utf-8")

    assert load_document(fichier, max_bytes=1_000).text == "note"


def test_iter_corpus_renvoie_les_fichiers_tries(tmp_path: Path) -> None:
    """L'ordre doit etre reproductible.

    Sans tri, il depend du systeme de fichiers : deux ingestions du meme corpus
    produiraient des rapports differents, ce qui rend tout diagnostic penible.
    """
    for nom in ("c.md", "a.md", "b.md"):
        (tmp_path / nom).write_text("x", encoding="utf-8")

    assert [p.name for p in iter_corpus(tmp_path)] == ["a.md", "b.md", "c.md"]


def test_iter_corpus_descend_dans_les_sous_repertoires(tmp_path: Path) -> None:
    (tmp_path / "sous").mkdir()
    (tmp_path / "sous" / "profond.md").write_text("x", encoding="utf-8")

    assert [p.name for p in iter_corpus(tmp_path)] == ["profond.md"]


def test_un_repertoire_inexistant_est_signale(tmp_path: Path) -> None:
    with pytest.raises(IngestionError):
        iter_corpus(tmp_path / "absent")
