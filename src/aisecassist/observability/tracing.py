"""Traçage des requêtes vers Langfuse (ticket 24, ADR-0015).

Les logs disent *qu'il s'est passé quelque chose*. Une trace dit *ce qui s'est
passé* : la question posée, les extraits retenus et leur score, chaque appel
d'outil, la réponse produite, et le temps de chaque étape. C'est l'outil de
diagnostic dont M5 aura besoin quand une défense cédera et qu'il faudra
comprendre pourquoi.

**Le métier n'importe jamais le SDK.** Il appelle `traced(...)`, défini ici. Ce
module est le seul à connaître Langfuse, exactement comme `llm/ollama.py` est le
seul à connaître l'API d'Ollama (ADR-0002). Le jour où l'on change d'outil, ou
si l'on veut émettre vers un autre collecteur OpenTelemetry, un seul fichier
bouge.

**Désactivé, c'est un vrai no-op.** Sans configuration, `traced(...)` ne
construit rien et n'émet rien : la CI, les tests et un usage hors ligne ne
paient aucun coût et n'ont aucune dépendance à un service.

**Ce qui entre dans une trace est du contenu sensible.** Une trace contient par
construction la question de l'utilisateur et les extraits récupérés — tout ce
que l'on prend soin de tenir hors des logs (SEC-12). Ce n'est pas une
contradiction, c'est un arbitrage assumé : sans ce contenu, une trace ne sert à
rien. Deux conséquences, appliquées ici :

- **les secrets à forme reconnaissable sont rédigés** avant l'envoi, par le même
  guardrail que les réponses ;
- **l'instance Langfuse doit être traitée comme un dépôt de données sensibles**,
  ce que `docs/SECURITY.md` énonce. D'où le choix de l'auto-héberger : le
  contenu ne quitte pas la machine (ADR-0015).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from aisecassist.security.output_guardrail import redact

logger = logging.getLogger(__name__)

# Plafond de longueur d'une valeur envoyée dans une trace. Une trace n'est pas
# un entrepôt : un document entier y serait illisible et coûteux à stocker.
_VALEUR_MAX = 4_000

_client: Any | None = None


class _Span:
    """Poignée rendue par `traced`. Sans traçage actif, tout y est sans effet."""

    def __init__(self, interne: Any | None) -> None:
        self._interne = interne

    def sortie(self, **valeurs: Any) -> None:
        """Attache le résultat de l'étape à la trace en cours."""
        if self._interne is None:
            return
        try:
            self._interne.update(output=_assainir(valeurs))
        except Exception:  # noqa: BLE001 - voir `traced`
            logger.warning("Ecriture d'une trace echouee.", exc_info=True)


_SANS_TRACE = _Span(None)


def configure_tracing(
    *,
    enabled: bool,
    host: str,
    public_key: str | None,
    secret_key: str | None,
) -> bool:
    """Prépare le client de traçage. Rend `True` s'il est actif.

    Une configuration incomplète n'est pas une erreur fatale : le traçage est un
    confort d'exploitation, pas une fonction du produit. Le service démarre sans,
    en le signalant. Faire échouer le démarrage pour un outil de diagnostic
    reviendrait à rendre l'observabilité plus critique que ce qu'elle observe.
    """
    global _client
    _client = None

    if not enabled:
        return False
    if not public_key or not secret_key:
        logger.warning(
            "Tracage demande mais cles absentes : il reste desactive. "
            "Renseigner LANGFUSE_PUBLIC_KEY et LANGFUSE_SECRET_KEY."
        )
        return False

    try:
        from langfuse import Langfuse

        _client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    except Exception:  # noqa: BLE001 - voir ci-dessous
        # Toute panne du traceur — SDK absent, hote injoignable, cles refusees —
        # laisse le produit fonctionner. Un service qui tombe parce que son
        # observabilite est en panne a inverse la hierarchie.
        logger.warning("Initialisation du tracage echouee : il reste desactive.", exc_info=True)
        return False

    logger.info("Tracage actif vers %s.", host)
    return True


def shutdown_tracing() -> None:
    """Vide la file d'envoi à l'arrêt, pour ne pas perdre les dernières traces."""
    global _client
    if _client is None:
        return
    try:
        _client.shutdown()
    except Exception:  # noqa: BLE001
        logger.warning("Arret du tracage echoue.", exc_info=True)
    finally:
        _client = None


def tracing_actif() -> bool:
    """Indique si les appels à `traced` produisent réellement quelque chose."""
    return _client is not None


@contextmanager
def traced(nom: str, **entrees: Any) -> Iterator[_Span]:
    """Ouvre une étape tracée, et la referme à la sortie du bloc.

    Args:
        nom: nom de l'étape, tel qu'il apparaîtra dans l'interface.
        entrees: données d'entrée de l'étape. Assainies avant envoi.

    N'échoue jamais. Une panne du traçage est journalisée puis ignorée : le bloc
    s'exécute de la même façon, traçage actif ou non. C'est ce qui permet de
    poser ces appels dans le chemin des requêtes sans en faire un point de
    défaillance supplémentaire.
    """
    if _client is None:
        yield _SANS_TRACE
        return

    try:
        gestionnaire = _client.start_as_current_observation(name=nom, input=_assainir(entrees))
    except Exception:  # noqa: BLE001
        logger.warning("Ouverture d'une trace echouee.", exc_info=True)
        yield _SANS_TRACE
        return

    with gestionnaire as interne:
        yield _Span(interne)


def _assainir(valeurs: Mapping[str, Any]) -> dict[str, Any]:
    """Rédige les secrets et plafonne les longueurs avant l'envoi.

    Le guardrail de sortie sert ici sa deuxième porte. Il a été écrit pour les
    réponses ; une trace est une seconde sortie du système, vers un autre
    destinataire, et mérite la même barrière.
    """
    return {cle: _valeur_sure(valeur) for cle, valeur in valeurs.items()}


def _valeur_sure(valeur: Any) -> Any:
    if isinstance(valeur, str):
        texte = redact(valeur).text
        return texte if len(texte) <= _VALEUR_MAX else texte[:_VALEUR_MAX] + " […]"
    if isinstance(valeur, (list, tuple)):
        return [_valeur_sure(element) for element in valeur]
    if isinstance(valeur, Mapping):
        return {cle: _valeur_sure(sous_valeur) for cle, sous_valeur in valeur.items()}
    return valeur
