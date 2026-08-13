"""Orchestration de la chaine d'ingestion : charger, assainir, decouper, indexer.

Point d'entree en ligne de commande :

    python -m aisecassist.ingestion.pipeline data/corpus
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

from aisecassist.config import settings
from aisecassist.embeddings.base import Embedder
from aisecassist.embeddings.sentence_transformer import SentenceTransformerEmbedder
from aisecassist.ingestion.chunker import chunk_text
from aisecassist.ingestion.cleaner import clean_text
from aisecassist.ingestion.loader import IngestionError, iter_corpus, load_document
from aisecassist.vectorstore.base import VectorStore
from aisecassist.vectorstore.qdrant import QdrantVectorStore


@dataclass(frozen=True, slots=True)
class SkippedDocument:
    """Document ecarte, et pourquoi."""

    source: str
    reason: str


@dataclass(frozen=True, slots=True)
class IngestionReport:
    """Bilan d'une ingestion.

    Les documents ecartes sont enumeres, jamais simplement comptes. Une
    ingestion qui saute des fichiers en silence donne l'illusion d'un corpus
    complet : on croit une source indexee alors qu'elle est absente, et les
    reponses seront incompletes sans que rien ne le signale.
    """

    documents_ingested: int
    chunks_indexed: int
    invisible_removed: int
    skipped: tuple[SkippedDocument, ...]


class IngestionPipeline:
    """Enchaine chargement, assainissement, decoupage, vectorisation, indexation."""

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        *,
        chunk_size: int,
        chunk_overlap: int,
        max_document_bytes: int,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._max_document_bytes = max_document_bytes

    async def ingest_directory(self, directory: Path) -> IngestionReport:
        """Ingere tous les documents recevables d'un repertoire.

        Un document refuse n'interrompt pas l'ingestion : il est ecarte et
        consigne dans le rapport. Un corpus de reference contient rarement que
        des fichiers valides, et echouer au premier fichier bancal rendrait
        l'outil inutilisable.
        """
        await self._store.ensure_collection(self._embedder.dimension)

        documents = 0
        chunks = 0
        invisibles = 0
        ecartes: list[SkippedDocument] = []

        for path in iter_corpus(directory):
            try:
                raw = load_document(path, self._max_document_bytes)
            except IngestionError as exc:
                ecartes.append(SkippedDocument(source=path.name, reason=str(exc)))
                continue

            cleaned = clean_text(raw.text)
            invisibles += cleaned.removed_invisible

            fragments = chunk_text(cleaned.text, self._chunk_size, self._chunk_overlap)
            if not fragments:
                ecartes.append(
                    SkippedDocument(source=raw.source, reason="document vide apres assainissement")
                )
                continue

            vectors = await self._embedder.embed(fragments)
            await self._store.add(fragments, vectors, [raw.source] * len(fragments))

            documents += 1
            chunks += len(fragments)

        return IngestionReport(
            documents_ingested=documents,
            chunks_indexed=chunks,
            invisible_removed=invisibles,
            skipped=tuple(ecartes),
        )


def build_default_pipeline() -> tuple[IngestionPipeline, QdrantVectorStore]:
    """Assemble un pipeline a partir de la configuration.

    Renvoie aussi le store, dont l'appelant doit fermer le client.
    """
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        settings.embedding_dimension,
    )
    store = QdrantVectorStore(settings.qdrant_url, settings.qdrant_collection)
    pipeline = IngestionPipeline(
        embedder,
        store,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        max_document_bytes=settings.max_document_bytes,
    )
    return pipeline, store


async def _run(directory: Path) -> IngestionReport:
    pipeline, store = build_default_pipeline()
    async with store:
        return await pipeline.ingest_directory(directory)


def main() -> None:
    """Point d'entree en ligne de commande."""
    parser = argparse.ArgumentParser(description="Ingere un corpus dans la base vectorielle.")
    parser.add_argument("directory", type=Path, help="repertoire contenant les documents")
    args = parser.parse_args()

    report = asyncio.run(_run(args.directory))

    print(f"Documents ingeres  : {report.documents_ingested}")
    print(f"Fragments indexes  : {report.chunks_indexed}")
    print(f"Invisibles retires : {report.invisible_removed}")
    if report.skipped:
        print(f"\nDocuments ecartes ({len(report.skipped)}) :")
        for skipped in report.skipped:
            print(f"  - {skipped.source} : {skipped.reason}")


if __name__ == "__main__":
    main()
