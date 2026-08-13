"""Chargement des documents du corpus, sous contraintes (SEC-13).

Le corpus est une entree hostile differee : un document empoisonne n'agit pas a
l'ingestion mais au moment ou il est recupere (SECURITY.md, frontiere 5). Ce
module est la premiere barriere — il decide de ce qui a le droit d'entrer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Liste blanche d'extensions, volontairement NON configurable par environnement.
# C'est une decision de securite, pas un reglage : la rendre modifiable par
# variable d'environnement permettrait d'elargir la surface d'attaque sans
# relecture de code ni trace dans le depot.
ALLOWED_SUFFIXES = frozenset({".md", ".txt"})


@dataclass(frozen=True, slots=True)
class RawDocument:
    """Document brut, avant assainissement."""

    source: str
    text: str


class IngestionError(RuntimeError):
    """Echec de chargement d'un document."""


class UnsupportedDocumentError(IngestionError):
    """Le type de fichier n'est pas dans la liste blanche."""


class DocumentTooLargeError(IngestionError):
    """Le document depasse le plafond de taille autorise."""


class UndecodableDocumentError(IngestionError):
    """Le contenu n'est pas du texte UTF-8 exploitable."""


def load_document(path: Path, max_bytes: int) -> RawDocument:
    """Charge un document apres validation de son type et de sa taille.

    Args:
        path: chemin du fichier.
        max_bytes: taille maximale acceptee, en octets.

    Raises:
        UnsupportedDocumentError: extension hors liste blanche.
        DocumentTooLargeError: fichier trop volumineux.
        UndecodableDocumentError: contenu non decodable en UTF-8.
        IngestionError: fichier absent ou illisible.
    """
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise UnsupportedDocumentError(
            f"{path.name} : extension {path.suffix or '(aucune)'} refusee. "
            f"Types acceptes : {', '.join(sorted(ALLOWED_SUFFIXES))}."
        )

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise IngestionError(f"{path.name} : fichier illisible ({exc}).") from exc

    # La taille est verifiee AVANT la lecture, et c'est tout l'interet du
    # controle. Lire puis mesurer laisserait un fichier de plusieurs Go saturer
    # la memoire du processus : le rejet arriverait apres le deni de service
    # qu'il etait cense empecher.
    if size > max_bytes:
        raise DocumentTooLargeError(
            f"{path.name} : {size} octets, plafond a {max_bytes}. Document ignore."
        )

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # Une extension autorisee ne garantit pas un contenu textuel : rien
        # n'empeche de renommer un binaire en .md.
        raise UndecodableDocumentError(
            f"{path.name} : contenu non decodable en UTF-8, probablement binaire."
        ) from exc
    except OSError as exc:
        raise IngestionError(f"{path.name} : lecture impossible ({exc}).") from exc

    return RawDocument(source=path.name, text=text)


def iter_corpus(directory: Path) -> list[Path]:
    """Liste les fichiers candidats d'un repertoire, tries pour etre reproductible.

    Le tri n'est pas cosmetique : sans lui, l'ordre depend du systeme de
    fichiers et deux ingestions du meme corpus produisent des rapports
    differents, ce qui rend tout diagnostic penible.

    Raises:
        IngestionError: le repertoire n'existe pas.
    """
    if not directory.is_dir():
        raise IngestionError(f"{directory} n'est pas un repertoire.")
    return sorted(p for p in directory.rglob("*") if p.is_file())
