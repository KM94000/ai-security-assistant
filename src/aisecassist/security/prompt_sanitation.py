"""Assainissement du contenu non fiable avant insertion dans un prompt.

Deux entrees fournissent du texte que personne n'a ecrit pour nous : les
extraits recuperes dans le corpus, et leur provenance. Les deux finissent dans
un prompt, et les deux ont pu etre rediges par un attaquant (SEC-01b, SEC-04).
Ce module retire ce qui a la *forme* d'un delimiteur de bloc, pour qu'un extrait
ne puisse pas se faire passer pour la cloture du contexte.

Une seule implementation pour les deux chemins qui parlent au modele :
l'assemblage du prompt de `/query` (ADR-0009) et les observations d'outils
rendues a l'agent (M3). Dupliquer ces quelques lignes serait le meilleur moyen
de n'en corriger qu'une le jour ou un contournement sera trouve.
"""

from __future__ import annotations

import re

# Tout ce qui ressemble a un delimiteur est neutralise dans le contenu, quelle
# que soit la valeur du nonce. Le nonce reel etant imprevisible, cette regle ne
# devrait jamais rien attraper — c'est precisement pour cela qu'on la met : elle
# ne coute rien et couvre le cas ou la generation du nonce serait affaiblie un
# jour par erreur.
_FORME_DELIMITEUR = re.compile(r"=== *(?:CONTEXTE|QUESTION)-[0-9a-fA-F]{8,} *===")

MARQUEUR_RETIRE = "[marqueur retire]"

# Plafond de longueur d'une provenance affichee dans un prompt. Un nom de
# fichier legitime tient tres largement en dessous.
SOURCE_MAX = 200


def neutralize_markers(contenu: str) -> str:
    """Retire du contenu tout ce qui a la forme d'un delimiteur de bloc."""
    return _FORME_DELIMITEUR.sub(MARQUEUR_RETIRE, contenu)


def safe_source(source: str) -> str:
    """Rend une provenance sure a interpoler sur une seule ligne d'un prompt.

    La provenance emprunte exactement le meme chemin non fiable que le texte :
    c'est une valeur du payload Qdrant, ecrite a l'ingestion ou directement en
    base. Une premiere version neutralisait le texte et oubliait la source qui
    l'accompagne — un nom de fichier contenant un saut de ligne suffisait alors
    a rompre la structure "[n] source : X" et a faire passer du texte pour une
    nouvelle entree de contexte.

    Trois mesures, dans cet ordre :

    1. Les sauts de ligne deviennent des espaces. La provenance doit tenir sur
       une ligne, sinon elle cree une structure qu'elle n'est pas censee creer.
    2. Neutralisation de la forme des delimiteurs — appliquee **apres** l'etape
       precedente, pour attraper un marqueur qui aurait ete reassemble par le
       repliement des lignes.
    3. Plafond de longueur : un nom de fichier legitime tient largement dessous,
       et une valeur demesuree ne doit pas gonfler le prompt.
    """
    sur_une_ligne = source.replace("\r", " ").replace("\n", " ")
    neutralise = neutralize_markers(sur_une_ligne).strip()
    if len(neutralise) > SOURCE_MAX:
        return neutralise[:SOURCE_MAX] + "…"
    return neutralise
