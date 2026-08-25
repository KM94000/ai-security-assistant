"""Guardrail de sortie : redaction des secrets avant renvoi au client (SEC-02).

**Ce module est une derniere ligne de defense, pas la premiere.** Un secret ne
devrait jamais atteindre le modele : il n'a rien a faire dans le corpus, ni dans
le prompt systeme, ni dans les variables lues par l'application. Si ce guardrail
declenche, c'est qu'une barriere en amont a deja cede — d'ou le journal en
niveau avertissement a chaque declenchement.

**Et il est incomplet par construction.** Une detection par motifs attrape des
formes connues, pas « tout ce qui est secret ». Un mot de passe en clair au
milieu d'une phrase passera. Le presenter comme une garantie serait un
mensonge ; il reduit la surface, il ne la ferme pas.

Ce qu'il attrape de facon fiable : les secrets a forme reconnaissable — cles
privees, jetons de fournisseurs, affectations explicites — et les litteraux que
l'appelant lui signale, notamment le nonce de delimitation du prompt.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

REMPLACEMENT = "[secret redige]"

# Motifs a quantificateurs **bornes**. Ce n'est pas un detail : la redaction en
# flux retient une fenetre de securite dimensionnee sur la plus longue
# correspondance possible. Un `+` non borne rendrait cette fenetre incalculable.
_MOTIFS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cle privee", re.compile(r"-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----")),
    ("cle de fournisseur", re.compile(r"\bsk-[A-Za-z0-9_-]{20,64}\b")),
    ("cle aws", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("jeton github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")),
    ("en-tete bearer", re.compile(r"(?i)\bbearer\s{1,4}[A-Za-z0-9._~+/=-]{20,64}")),
    (
        "affectation de secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|apikey|token|password|passwd|secret)\b"
            r"\s{0,4}[:=]\s{0,4}['\"]?[A-Za-z0-9_\-./+=]{16,64}"
        ),
    ),
)

# Doit rester strictement superieur a la plus longue correspondance possible.
# Verifie par un test : si un motif s'allonge sans que cette valeur suive, la
# redaction en flux laisserait passer un secret a cheval sur deux fragments.
LONGUEUR_MAX_MOTIF = 96


@dataclass(frozen=True, slots=True)
class GuardrailResult:
    """Texte assaini, et categories de secrets rencontrees."""

    text: str
    categories: tuple[str, ...]
    """Noms des categories declenchees, sans doublon.

    Jamais les valeurs : journaliser un secret pour signaler qu'on l'a bloque
    reviendrait a le divulguer une seconde fois, dans un endroit souvent moins
    bien protege que la reponse HTTP.
    """


def redact(text: str, *, literaux: Sequence[str] = ()) -> GuardrailResult:
    """Remplace les secrets reconnus par un marqueur.

    Args:
        text: le texte a assainir.
        literaux: chaines a retirer telles quelles, quelle que soit leur forme.
            Sert au nonce de delimitation du prompt : le modele n'a aucune
            raison de le restituer, et le laisser passer revelerait la structure
            de la cloture de contexte.
    """
    categories: list[str] = []
    resultat = text

    for litteral in literaux:
        if litteral and litteral in resultat:
            resultat = resultat.replace(litteral, REMPLACEMENT)
            _ajouter(categories, "marqueur interne")

    for nom, motif in _MOTIFS:
        resultat, remplacements = motif.subn(REMPLACEMENT, resultat)
        if remplacements:
            _ajouter(categories, nom)

    return GuardrailResult(text=resultat, categories=tuple(categories))


class StreamRedactor:
    """Applique la redaction a un flux, sans laisser passer les secrets a cheval.

    Le probleme propre au streaming : un secret peut etre coupe entre deux
    fragments. Rediger chaque fragment independamment ne verrait rien, et le
    secret serait reconstitue par le client en concatenant.

    Deux mecanismes, complementaires :

    1. **Retenue.** Les `LONGUEUR_MAX_MOTIF` derniers caracteres du tampon ne
       sont jamais emis avant la fin du flux. Une correspondance encore
       incomplete a cet endroit aura le temps de se former.
    2. **Recul devant une correspondance a cheval.** Si une correspondance
       complete chevauche le point de coupe, la coupe recule jusqu'a son debut,
       pour qu'elle soit rédigée d'un seul tenant.

    Cout assume : les premiers caracteres de la reponse sont retenus jusqu'a ce
    que le tampon depasse la fenetre. Sur une reponse courte, tout arrive au
    `flush`. C'est le prix d'une redaction correcte en flux — et l'alternative,
    proteger `/query` mais pas `/query/stream`, offrirait simplement un
    contournement a qui sait lire la documentation.
    """

    def __init__(self, *, literaux: Sequence[str] = ()) -> None:
        self._literaux = tuple(litteral for litteral in literaux if litteral)
        self._tampon = ""
        self._categories: list[str] = []

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(self._categories)

    def feed(self, fragment: str) -> str:
        """Absorbe un fragment et renvoie ce qui peut etre emis sans risque."""
        self._tampon += fragment

        coupe = len(self._tampon) - LONGUEUR_MAX_MOTIF
        if coupe <= 0:
            return ""

        coupe = self._reculer_devant_correspondance(coupe)
        if coupe <= 0:
            return ""

        prefixe = self._tampon[:coupe]
        self._tampon = self._tampon[coupe:]
        return self._rediger(prefixe)

    def flush(self) -> str:
        """Renvoie le reliquat, redige. A appeler en fin de flux."""
        reste, self._tampon = self._tampon, ""
        return self._rediger(reste)

    def _rediger(self, texte: str) -> str:
        resultat = redact(texte, literaux=self._literaux)
        for categorie in resultat.categories:
            _ajouter(self._categories, categorie)
        return resultat.text

    def _reculer_devant_correspondance(self, coupe: int) -> int:
        """Recule la coupe si une correspondance complete l'enjambe."""
        debuts: list[int] = []

        for _, motif in _MOTIFS:
            for correspondance in motif.finditer(self._tampon):
                if correspondance.start() < coupe < correspondance.end():
                    debuts.append(correspondance.start())

        for litteral in self._literaux:
            depart = 0
            while (position := self._tampon.find(litteral, depart)) != -1:
                if position < coupe < position + len(litteral):
                    debuts.append(position)
                depart = position + 1

        return min(debuts, default=coupe)


def _ajouter(categories: list[str], nom: str) -> None:
    if nom not in categories:
        categories.append(nom)
