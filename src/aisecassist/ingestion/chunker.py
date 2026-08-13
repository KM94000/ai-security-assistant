"""Decoupage du texte en fragments recouvrants.

Fonction pure, sans I/O ni etat : c'est le module le plus simple a tester de
toute la chaine, et celui dont les erreurs sont les plus difficiles a voir en
production — un mauvais decoupage ne plante pas, il degrade silencieusement la
pertinence des reponses.
"""

from __future__ import annotations


class ChunkingError(ValueError):
    """Parametres de decoupage incoherents."""


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Decoupe un texte en fragments de `chunk_size` caracteres, avec recouvrement.

    Le recouvrement evite qu'une phrase coupee en deux par une frontiere de
    fragment ne devienne introuvable : chaque fragment reprend la fin du
    precedent.

    Args:
        text: texte deja assaini.
        chunk_size: longueur maximale d'un fragment, en caracteres.
        overlap: nombre de caracteres repris du fragment precedent.

    Raises:
        ChunkingError: `chunk_size` non positif, ou `overlap` hors de [0, chunk_size[.
    """
    if chunk_size <= 0:
        raise ChunkingError(f"chunk_size doit etre strictement positif, recu {chunk_size}.")
    if overlap < 0:
        raise ChunkingError(f"overlap ne peut pas etre negatif, recu {overlap}.")
    # Un recouvrement superieur ou egal a la taille du fragment empeche la
    # fenetre d'avancer : la boucle tournerait indefiniment en produisant
    # toujours le meme fragment, jusqu'a saturer la memoire. Le controle est
    # ici parce que ce reglage vient de la configuration, donc de l'exterieur.
    if overlap >= chunk_size:
        raise ChunkingError(
            f"overlap ({overlap}) doit etre strictement inferieur a chunk_size "
            f"({chunk_size}), sans quoi le decoupage ne progresse pas."
        )

    if not text:
        return []

    pas = chunk_size - overlap
    fragments = [text[debut : debut + chunk_size] for debut in range(0, len(text), pas)]

    # Les dernieres fenetres peuvent n'etre que des recouvrements du fragment
    # precedent, sans rien apporter de neuf. Une boucle et non un test unique :
    # un recouvrement eleve en produit plusieurs a la suite, et n'en retirer
    # qu'un laissait des quasi-doublons occuper des places du top-k.
    while len(fragments) > 1 and fragments[-1] in fragments[-2]:
        fragments.pop()

    return [fragment for fragment in fragments if fragment.strip()]
