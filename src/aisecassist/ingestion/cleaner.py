"""Assainissement du texte ingere (amorce SEC-04).

Ce module ne cherche pas a decider si un document est malveillant — c'est un
jugement de contenu, qu'on ne sait pas rendre de facon fiable. Il supprime la
**tromperie** : les caracteres qu'un relecteur humain ne voit pas mais que le
modele lit.

C'est la difference essentielle. Un document qui ecrit en clair "ignore tes
instructions" est visible : il sera traite par la delimitation du contexte
(ticket 12) et par la resistance comportementale (M5). Un document qui cache la
meme phrase derriere des caracteres de largeur nulle, ou qui inverse l'ordre
d'affichage avec des marques bidirectionnelles, est invisible a la relecture du
corpus. Aucune revue humaine ne l'attrapera.

Apres passage ici, le corpus dit ce qu'il a l'air de dire.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Seuls caracteres de controle conserves : ils portent la structure du document.
_CONTROLES_AUTORISES = frozenset({"\n", "\t"})

# Reduit le remplissage horizontal, mais uniquement apres un caractere visible.
# L'indentation de debut de ligne est donc preservee : le corpus de reference
# contient des extraits de code (OWASP, NIST), et les aplatir abimerait les
# passages restitues a l'utilisateur.
_REMPLISSAGE_INTERNE = re.compile(r"(\S)[ \t]{2,}")
_LIGNES_VIDES_MULTIPLES = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class CleanedText:
    """Texte assaini, accompagne de ce qui a ete retire."""

    text: str
    removed_invisible: int
    """Nombre de caracteres invisibles supprimes.

    Compte remonte volontairement jusqu'au rapport d'ingestion : quelques
    occurrences sont banales (un BOM, un liant typographique), mais plusieurs
    dizaines dans un document ne le sont pas. C'est un signal, pas une preuve.
    """


def clean_text(raw: str) -> CleanedText:
    """Normalise et assainit un texte avant decoupage.

    Trois etapes, dans cet ordre :

    1. Normalisation Unicode NFKC — replie les formes de compatibilite et les
       sosies typographiques sur leur forme canonique, pour qu'un meme mot
       s'ecrive d'une seule facon.
    2. Suppression des categories Cc (controle) et Cf (format), hors retour a
       la ligne et tabulation. Cette regle par categorie couvre d'un coup les
       caracteres de largeur nulle (U+200B, U+FEFF, U+2060) et les marques
       bidirectionnelles (U+202A a U+202E, U+2066 a U+2069) utilisees par les
       attaques de type Trojan Source. Une liste explicite serait a completer
       a chaque nouvelle version d'Unicode ; la categorie, non.
    3. Normalisation des espaces — de longues suites d'espaces ou de lignes
       vides servent a pousser du contenu hors du champ de vision d'un
       relecteur, et gaspillent le budget de chaque fragment. La reduction ne
       s'applique qu'apres un caractere visible : l'indentation de debut de
       ligne est preservee, faute de quoi les extraits de code du corpus
       seraient aplatis.

    Les caracteres invisibles sont **supprimes** et non remplaces par un espace.
    C'est deliberé : "IGNO\\u200bRE" redevient "IGNORE" au lieu de rester
    coupe en deux. On ne cherche pas a effacer la charge, mais a la rendre
    lisible telle qu'elle est — y compris par les defenses situees en aval.
    """
    normalise = unicodedata.normalize("NFKC", raw)

    conserves: list[str] = []
    supprimes = 0
    for caractere in normalise:
        if caractere in _CONTROLES_AUTORISES:
            conserves.append(caractere)
            continue
        if unicodedata.category(caractere) in ("Cc", "Cf"):
            supprimes += 1
            continue
        conserves.append(caractere)

    texte = "".join(conserves)
    texte = _REMPLISSAGE_INTERNE.sub(r"\1 ", texte)
    texte = _LIGNES_VIDES_MULTIPLES.sub("\n\n", texte)

    return CleanedText(text=texte.strip(), removed_invisible=supprimes)
