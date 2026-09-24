"""Configuration des logs structures (ticket 23, ADR-0014).

**Le parti pris : ne reecrire aucun appel existant.** Les vingt-cinq
`logger.warning(...)` du projet utilisent le module `logging` standard. Plutot
que de les convertir un par un, structlog est branche *en aval* de `logging` :
chaque enregistrement, d'ou qu'il vienne — notre code comme une bibliotheque
tierce — traverse la meme chaine de traitement et ressort au meme format.

Un appel inchange gagne donc l'horodatage, le niveau, le nom du module et
l'identifiant de requete, sans qu'une seule ligne de metier ne bouge.

**L'identifiant de requete voyage par variable de contexte**, jamais en
parametre. Le passer de fonction en fonction changerait la signature de toute la
chaine d'appel — exactement le genre de modification virale qu'on evite. Une
`ContextVar` est portee par la tache asyncio courante : chaque requete a la
sienne, sans qu'aucun code intermediaire n'ait a la connaitre.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, TextIO

import structlog

# Bruit de fond des bibliotheques tierces, ramene a l'essentiel. `httpx` emet un
# INFO par requete HTTP : avec un agent qui en enchaine plusieurs par question,
# cela noierait nos propres traces.
_BIBLIOTHEQUES_BAVARDES = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    "sentence_transformers": logging.WARNING,
}

_PREPARATION: list[Any] = [
    # En premier : sans lui, l'identifiant de requete n'atteindrait pas les
    # enregistrements venus du module `logging` standard.
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]


def configure_logging(
    *,
    level: str = "INFO",
    json_format: bool = True,
    stream: TextIO | None = None,
) -> None:
    """Installe la chaine de traitement des logs, pour tout le processus.

    Args:
        level: niveau plancher, par nom (`DEBUG`, `INFO`, `WARNING`...).
        json_format: une ligne JSON par enregistrement. Vrai par defaut, parce
            que c'est ce qu'attend un agregateur de logs. Faux donne une sortie
            coloree, lisible a l'oeil pendant le developpement.
        stream: destination de sortie. `sys.stdout` par defaut. Injectable pour
            la meme raison que le client httpx des fournisseurs : un test doit
            pouvoir lire ce qui a ete emis sans dependre du mecanisme de capture
            de l'executeur de tests, qui s'interpose entre le module `logging`
            et la sortie standard.

    Appelable plusieurs fois sans dommage : les tests reconfigurent, et un
    rechargement a chaud du serveur aussi.
    """
    rendu: Any = (
        structlog.processors.JSONRenderer()
        if json_format
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[*_PREPARATION, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    formateur = structlog.stdlib.ProcessorFormatter(
        # `foreign_pre_chain` est la piece maitresse : c'est elle qui fait passer
        # les enregistrements du `logging` standard par nos processeurs.
        foreign_pre_chain=_PREPARATION,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, rendu],
    )

    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(formateur)

    racine = logging.getLogger()
    # On remplace les handlers au lieu d'en ajouter : sans cela, une seconde
    # configuration ferait apparaitre chaque ligne en double.
    racine.handlers = [handler]
    racine.setLevel(level.upper())

    for nom, plancher in _BIBLIOTHEQUES_BAVARDES.items():
        logging.getLogger(nom).setLevel(plancher)
