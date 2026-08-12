"""SEC-13 — validation d'ingestion : fichier surdimensionne ou de type inattendu.

Reference : docs/SECURITY.md, matrice section 6.
Attendu : rejete, **pas de crash**. Les deux moities comptent — un rejet qui
fait tomber l'ingestion complete est un deni de service a un fichier pres.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
from qdrant_client import AsyncQdrantClient

from aisecassist.embeddings.base import Embedder
from aisecassist.ingestion.loader import (
    DocumentTooLargeError,
    UndecodableDocumentError,
    UnsupportedDocumentError,
    load_document,
)
from aisecassist.ingestion.pipeline import IngestionPipeline
from aisecassist.vectorstore.qdrant import QdrantVectorStore

pytestmark = pytest.mark.anyio

_DIM = 4


class _FakeEmbedder(Embedder):
    """Vectoriseur deterministe : ce test porte sur l'ingestion, pas sur MiniLM."""

    @property
    def dimension(self) -> int:
        return _DIM

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(texte) % 7), 1.0, 0.0, 0.0] for texte in texts]


@pytest.fixture
async def pipeline() -> AsyncIterator[IngestionPipeline]:
    client = AsyncQdrantClient(location=":memory:")
    try:
        yield IngestionPipeline(
            _FakeEmbedder(),
            QdrantVectorStore(url="", collection="sec13", client=client),
            chunk_size=100,
            chunk_overlap=10,
            max_document_bytes=1_000,
        )
    finally:
        await client.close()


# --- Rejets au chargement -------------------------------------------------


def test_un_fichier_trop_volumineux_est_refuse(tmp_path: Path) -> None:
    fichier = tmp_path / "enorme.md"
    fichier.write_text("x" * 5_000, encoding="utf-8")

    with pytest.raises(DocumentTooLargeError):
        load_document(fichier, max_bytes=1_000)


def test_la_taille_est_verifiee_avant_toute_lecture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le point qui donne sa valeur au controle, et le seul qui soit subtil.

    Lire le fichier puis mesurer sa taille rejetterait bien le document — mais
    apres avoir charge plusieurs Go en memoire. Le rejet arriverait donc apres
    le deni de service qu'il etait cense empecher.

    On rend `read_text` explosif : si le chargeur le touche, le test echoue
    avec une autre exception que celle attendue.
    """
    fichier = tmp_path / "enorme.md"
    fichier.write_text("x" * 5_000, encoding="utf-8")

    def _interdit(*args: object, **kwargs: object) -> str:
        raise AssertionError("read_text ne doit pas etre appele : la taille est deja hors bornes")

    monkeypatch.setattr(Path, "read_text", _interdit)

    with pytest.raises(DocumentTooLargeError):
        load_document(fichier, max_bytes=1_000)


@pytest.mark.parametrize("nom", ["charge.exe", "archive.zip", "script.sh", "sans_extension"])
def test_un_type_de_fichier_hors_liste_blanche_est_refuse(tmp_path: Path, nom: str) -> None:
    fichier = tmp_path / nom
    fichier.write_text("contenu", encoding="utf-8")

    with pytest.raises(UnsupportedDocumentError):
        load_document(fichier, max_bytes=1_000)


def test_un_binaire_renomme_en_markdown_est_refuse(tmp_path: Path) -> None:
    """Une extension autorisee ne prouve rien sur le contenu."""
    fichier = tmp_path / "deguise.md"
    fichier.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x01binaire")

    with pytest.raises(UndecodableDocumentError):
        load_document(fichier, max_bytes=1_000)


# --- Resilience du pipeline ------------------------------------------------


async def test_un_document_refuse_narrete_pas_l_ingestion(
    tmp_path: Path, pipeline: IngestionPipeline
) -> None:
    """La seconde moitie de l'attendu SEC-13 : rejete, mais pas de crash.

    Un corpus de reference contient rarement que des fichiers impeccables.
    Echouer au premier document bancal rendrait l'outil inutilisable.
    """
    (tmp_path / "valide.md").write_text("Contenu de reference exploitable.", encoding="utf-8")
    (tmp_path / "enorme.md").write_text("x" * 5_000, encoding="utf-8")
    (tmp_path / "charge.exe").write_text("contenu", encoding="utf-8")
    (tmp_path / "deguise.md").write_bytes(b"\xff\xfe\x00\x01")

    report = await pipeline.ingest_directory(tmp_path)

    assert report.documents_ingested == 1
    assert report.chunks_indexed == 1
    assert len(report.skipped) == 3


async def test_chaque_document_ecarte_est_nomme_avec_sa_raison(
    tmp_path: Path, pipeline: IngestionPipeline
) -> None:
    """Une ingestion qui saute des fichiers en silence donne l'illusion d'un corpus complet.

    On croit une source indexee alors qu'elle est absente, et les reponses sont
    incompletes sans que rien ne le signale.
    """
    (tmp_path / "enorme.md").write_text("x" * 5_000, encoding="utf-8")

    report = await pipeline.ingest_directory(tmp_path)

    assert len(report.skipped) == 1
    ecarte = report.skipped[0]
    assert ecarte.source == "enorme.md"
    assert "plafond" in ecarte.reason


async def test_un_corpus_entierement_invalide_ne_fait_pas_planter(
    tmp_path: Path, pipeline: IngestionPipeline
) -> None:
    (tmp_path / "a.exe").write_text("x", encoding="utf-8")
    (tmp_path / "b.zip").write_text("x", encoding="utf-8")

    report = await pipeline.ingest_directory(tmp_path)

    assert report.documents_ingested == 0
    assert report.chunks_indexed == 0
    assert len(report.skipped) == 2
