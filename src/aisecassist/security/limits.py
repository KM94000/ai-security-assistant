"""Plafonds de longueur, en entree comme en sortie (SEC-10).

Le plafond est applique **cote serveur**, seul endroit ou il protege : une
generation partie en boucle emettrait sinon des fragments indefiniment, et rien
du cote client ne l'arreterait.

Partage par les deux chemins qui produisent une reponse — `/query` et l'agent —
parce qu'un plafond qui ne couvre qu'une des deux portes n'est pas un plafond.
"""

from __future__ import annotations

MAX_QUESTION_LENGTH = 2_000
"""Plafond de longueur d'une question.

Limite de securite plus que de confort : une question tres longue gonfle le
prompt, donc le cout et la latence. Volontairement non configurable par
environnement, au meme titre que la liste blanche d'extensions a l'ingestion.

Partage par les deux portes d'entree : le schema de `/query` et la validation
des arguments d'outil de l'agent, qui recoit lui aussi des questions — mais
ecrites par un modele.
"""

MARQUEUR_TRONCATURE = "\n\n[reponse tronquee : plafond de longueur atteint]"
"""Marqueur ajoute quand le plafond est atteint.

Tronquer en silence laisserait l'utilisateur devant une reponse coupee au
milieu d'une phrase, sans savoir si le modele a fini, si la connexion a lache,
ou si le serveur a decide d'arreter. Le dire coute une ligne.
"""


def plafonner(texte: str, maximum: int) -> tuple[str, bool]:
    """Plafonne un texte et signale si la coupe a eu lieu.

    Args:
        texte: le texte a plafonner.
        maximum: nombre maximal de caracteres conserves, marqueur non compris.

    Returns:
        Le texte, suivi du marqueur de troncature s'il a ete coupe, et un
        booleen qui dit si la coupe a eu lieu. L'appelant en a besoin : c'est
        lui qui sait s'il faut journaliser l'evenement.
    """
    if len(texte) <= maximum:
        return texte, False
    return texte[:maximum] + MARQUEUR_TRONCATURE, True
