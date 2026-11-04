"""Decoupage du texte en fragments.

Fonctions pures, sans I/O ni etat : c'est le module le plus simple a tester de
toute la chaine, et celui dont les erreurs sont les plus difficiles a voir en
production — un mauvais decoupage ne plante pas, il degrade silencieusement la
pertinence des reponses.

Cet avertissement, ecrit au ticket 10, s'est verifie au ticket 41. Le decoupage
par fenetre glissante coupait **au milieu des mots** et produisait des fragments
a cheval sur deux sections, donc des moyennes semantiques de deux sujets. Une
moyenne se place pres du centre de l'espace vectoriel, c'est-a-dire pres de
n'importe quel texte generique : sur un corpus de 50 fragments, la salutation
« Bonjour, comment vas-tu ? » obtenait **0,651** — au-dessus de la plus faible
question couverte. Plus aucun seuil ne separait le pertinent du hors-sujet.

D'ou `chunk_document`, qui respecte les sections. Mesure sur les 47 questions de
calibrage (ADR-0010) : l'ecart entre la pire question couverte et la meilleure
hors-sujet passe de **+0,000 a +0,025**, et la moyenne des questions couvertes
de 0,728 a 0,736.

`chunk_text` reste : il sert de repli pour les documents sans structure, et il
est appele a l'interieur d'une section trop longue pour tenir d'un bloc.
"""

from __future__ import annotations

import re


class ChunkingError(ValueError):
    """Parametres de decoupage incoherents."""


def _valider(chunk_size: int, overlap: int) -> None:
    """Refuse des parametres incoherents, avant tout examen du contenu.

    Appele par les deux decoupeurs, et **inconditionnellement**. Si
    `chunk_document` ne validait qu'en atteignant son repli en fenetre, les
    memes parametres seraient acceptes ou refuses selon le document — un
    comportement qui depend du contenu est precisement ce qu'on ne veut pas
    d'une fonction pure.
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
    _valider(chunk_size, overlap)

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


# Une section Markdown de niveau 2. Le niveau 1 porte le titre du document ;
# les niveaux 3 et au-dela restent DANS leur section, ce qui est voulu : une
# sous-partie sans sa partie perd le contexte qu'on cherche justement a garder.
_TITRE_DOCUMENT = re.compile(r"^# +(.+?)\s*$", re.MULTILINE)
_DEBUT_SECTION = "## "

# Fin de phrase suivie d'une espace. Approximation assumee : une abreviation
# terminee par un point ouvre une coupure a tort. La consequence est benigne
# — un fragment un peu plus court — la ou une coupure au milieu d'un mot, elle,
# degradait l'embedding.
_FIN_DE_PHRASE = re.compile(r"(?<=[.!?])\s+")


def chunk_document(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Decoupe un document en respectant sa structure, si elle en a une.

    Trois regles, par ordre d'application :

    1. **Une section de niveau 2 est une unite.** Elle part entiere si elle
       tient dans `chunk_size`, titre du document compris.
    2. **Le titre du document prefixe chaque fragment.** C'est ce qui porte la
       separation : un fragment qui commence par « OWASP Top 10 pour les
       applications a base de LLM » est loin du francais generique, alors qu'un
       fragment de prose nue en est proche. Mesure : la meilleure question
       hors-sujet tombe de 0,651 a 0,609.
    3. **Une section trop longue est coupee sur des frontieres de phrase.**
       Sans recouvrement : une phrase est deja une unite complete, et la raison
       d'etre du recouvrement — rattraper une phrase coupee en deux — ne se
       presente pas ici.

    Un document sans section de niveau 2 retombe sur `chunk_text`, de meme
    qu'une phrase unique plus longue que `chunk_size`.

    Args:
        text: texte deja assaini.
        chunk_size: longueur maximale d'un fragment, en caracteres.
        overlap: recouvrement, utilise uniquement par les replis en fenetre.

    Returns:
        Les fragments, prefixes de leur titre de document quand il existe.

    Raises:
        ChunkingError: parametres incoherents, comme pour `chunk_text`.
    """
    _valider(chunk_size, overlap)

    if not text.strip():
        return []

    correspondance = _TITRE_DOCUMENT.search(text)
    titre = correspondance.group(1).strip() if correspondance else ""

    # Le titre est retire du corps : il est deja porte par le prefixe, et le
    # repeter deux fois dans le meme fragment dilue l'embedding sans rien
    # apporter.
    corps = _TITRE_DOCUMENT.sub("", text, count=1) if titre else text

    sections = _sections(corps)
    if not sections:
        # Aucune structure a respecter : le comportement d'origine, inchange.
        return chunk_text(text, chunk_size, overlap)

    fragments: list[str] = []
    for section in sections:
        fragments.extend(_decouper_section(section, titre, chunk_size, overlap))
    return fragments


def _sections(text: str) -> list[str]:
    """Separe le texte sur les titres de niveau 2, en les conservant.

    Ce qui precede le premier `##` — titre du document et introduction — forme
    une section a part entiere : l'ecarter perdrait le cadrage du document.
    """
    blocs: list[str] = []
    courant: list[str] = []
    for ligne in text.splitlines():
        if ligne.startswith(_DEBUT_SECTION) and courant:
            blocs.append("\n".join(courant))
            courant = []
        courant.append(ligne)
    if courant:
        blocs.append("\n".join(courant))
    return [bloc.strip() for bloc in blocs if bloc.strip()]


def _decouper_section(section: str, titre: str, chunk_size: int, overlap: int) -> list[str]:
    """Rend une section entiere, ou coupee sur des phrases si elle deborde."""
    if len(_prefixer(section, titre)) <= chunk_size:
        return [_prefixer(section, titre)]

    # Le prefixe est compte dans le budget : sans cela, une section proche de
    # la limite produirait des fragments plus longs que `chunk_size`, et le
    # plafond cesserait d'en etre un.
    budget = chunk_size - len(_prefixer("", titre))
    if budget <= 0:
        # Titre demesure : on ne peut rien prefixer sans depasser. Le document
        # est alors traite comme s'il n'avait pas de titre.
        return chunk_text(section, chunk_size, overlap)

    fragments: list[str] = []
    accumule = ""
    for phrase in _FIN_DE_PHRASE.split(section):
        if len(phrase) > budget:
            # Une seule phrase depasse le budget : aucun decoupage par phrases
            # ne peut la faire tenir. Repli sur la fenetre glissante, qui est
            # le seul decoupage dont la terminaison ne depend pas du contenu.
            if accumule.strip():
                fragments.append(_prefixer(accumule.strip(), titre))
                accumule = ""
            fragments.extend(
                _prefixer(morceau, titre) for morceau in chunk_text(phrase, budget, overlap)
            )
            continue
        if accumule and len(accumule) + len(phrase) + 1 > budget:
            fragments.append(_prefixer(accumule.strip(), titre))
            accumule = ""
        accumule = f"{accumule} {phrase}" if accumule else phrase
    if accumule.strip():
        fragments.append(_prefixer(accumule.strip(), titre))
    return fragments


def _prefixer(corps: str, titre: str) -> str:
    """Ajoute le titre du document devant un fragment, s'il y en a un."""
    return f"{titre}\n\n{corps}" if titre else corps
