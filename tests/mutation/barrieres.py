"""Les barrieres de securite, et comment les neutraliser (ticket 27).

Ce module ne teste rien. Il declare **ce qu'il faudrait casser** pour que
chaque barriere cesse de proteger, afin que le harnais verifie qu'un test
s'en apercoit.

**Pourquoi des fonctions et non des constantes.** Les tests construisent les
services en leur injectant leurs plafonds (`max_iterations=2`,
`max_answer_chars=120`). Remplacer une valeur de configuration ne les
atteindrait donc pas : la neutralisation doit viser **le site qui applique**
la regle, pas la valeur qu'elle compare. C'est aussi plus honnete — on mesure
si le *comportement* est teste, pas si une constante est lue.

**Le piege a connaitre.** Une barriere dont le test importe la constante
qu'il verifie est faiblement muable : deplacer la constante deplace aussi
l'attendu du test. Quand c'est le cas, on vise le comportement.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import pytest

_TOUT_ACCEPTER = re.compile(r"(?s).*")
"""Expression qui accepte n'importe quoi, sauts de ligne compris."""


@dataclass(frozen=True, slots=True)
class Barriere:
    """Une barriere de securite et sa neutralisation."""

    nom: str
    sec: str
    """L'identifiant de `docs/SECURITY.md` que cette barriere sert."""
    ce_quelle_empeche: str
    """Une phrase : ce qui deviendrait possible sans elle."""
    neutraliser: Callable[[pytest.MonkeyPatch], None]
    tests: tuple[str, ...]
    """Les chemins de tests censes la couvrir. Au moins un doit rougir."""


# --- Neutralisations ---------------------------------------------------------
#
# Chacune recoit un MonkeyPatch et rend la barriere inoperante, sans rien
# casser d'autre. Une neutralisation qui ferait echouer les tests pour une
# raison etrangere a la barriere rendrait le resultat ininterpretable.


def _casser_format_cve(patch: pytest.MonkeyPatch) -> None:
    """Le format d'un identifiant CVE n'est plus verifie."""
    from aisecassist.agents import cve

    patch.setattr(cve, "_MOTIF_CVE", _TOUT_ACCEPTER)


def _casser_identifiant_requete(patch: pytest.MonkeyPatch) -> None:
    """N'importe quelle valeur de `X-Request-ID` est acceptee telle quelle."""
    from aisecassist.observability import request_id

    patch.setattr(request_id, "_FORME_VALIDE", _TOUT_ACCEPTER)


def _casser_guardrail_sortie(patch: pytest.MonkeyPatch) -> None:
    """Plus aucun motif de secret n'est reconnu."""
    from aisecassist.security import output_guardrail

    patch.setattr(output_guardrail, "_MOTIFS", ())


def _casser_plafond_longueur(patch: pytest.MonkeyPatch) -> None:
    """`plafonner` ne coupe plus rien, quel que soit le maximum demande."""
    from aisecassist.agents import service as agent_service
    from aisecassist.generation import service as generation_service
    from aisecassist.security import limits

    def _sans_plafond(texte: str, maximum: int) -> tuple[str, bool]:
        return texte, False

    patch.setattr(limits, "plafonner", _sans_plafond)
    # Les deux appelants l'ont importee PAR VALEUR (`from ... import plafonner`) :
    # patcher le module d'origine ne les atteindrait pas. Les viser tous les
    # deux est aussi ce qui verifie que les deux portes sont couvertes.
    patch.setattr(generation_service, "plafonner", _sans_plafond)
    patch.setattr(agent_service, "plafonner", _sans_plafond)


def _casser_plafond_iterations(patch: pytest.MonkeyPatch) -> None:
    """La boucle de l'agent ne coupe plus jamais sur le plafond."""
    from aisecassist.agents.service import AgentService

    original = AgentService._suite

    def _sans_plafond(self: AgentService, etat: object) -> str:
        resultat = original(self, etat)  # type: ignore[arg-type]
        return "executer" if resultat == "plafond" else resultat

    patch.setattr(AgentService, "_suite", _sans_plafond)


def _casser_appels_par_tour(patch: pytest.MonkeyPatch) -> None:
    """Tous les appels demandes en un tour sont executes."""
    from aisecassist.agents import service as agent_service

    patch.setattr(agent_service, "APPELS_MAX_PAR_TOUR", 10_000)


def _casser_liste_blanche(patch: pytest.MonkeyPatch) -> None:
    """Un outil hors liste est execute au lieu d'etre refuse.

    On ne peut pas neutraliser une liste blanche en changeant une valeur :
    c'est du flot de controle. Le dictionnaire des outils EST la liste, et le
    refus vient de son `get()` qui rend `None`. On le remplace donc par un
    dictionnaire qui rend toujours quelque chose — ce qui revient exactement
    a ne plus verifier.
    """
    from typing import Any

    from aisecassist.agents.service import AgentService

    class _ToujoursUnOutil(dict[str, Any]):
        def get(self, cle: str, defaut: Any = None) -> Any:  # type: ignore[override]
            trouve = super().get(cle)
            if trouve is not None:
                return trouve
            return next(iter(self.values()), defaut)

    original = AgentService.__init__

    def _init(self: AgentService, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        self._outils = _ToujoursUnOutil(self._outils)

    patch.setattr(AgentService, "__init__", _init)


def _casser_longueur_question(patch: pytest.MonkeyPatch) -> None:
    """Le plafond de longueur d'une question disparait des deux portes."""
    from aisecassist.agents import service as agent_service
    from aisecassist.api import schemas
    from aisecassist.security import limits

    enorme = 10_000_000
    patch.setattr(limits, "MAX_QUESTION_LENGTH", enorme)
    # Importee par valeur dans le service d'agent : la seconde porte.
    patch.setattr(agent_service, "MAX_QUESTION_LENGTH", enorme)

    # Le schema pydantic a fige la contrainte a l'import : la reconstruire.
    champ = schemas.QueryRequest.model_fields["question"]
    champ.metadata = [
        contrainte for contrainte in champ.metadata if type(contrainte).__name__ != "MaxLen"
    ]
    schemas.QueryRequest.model_rebuild(force=True)


BARRIERES: tuple[Barriere, ...] = (
    Barriere(
        nom="format-cve",
        sec="SEC-05",
        ce_quelle_empeche="une charge arbitraire partirait vers le NIST",
        neutraliser=_casser_format_cve,
        tests=("tests/security/test_sec05_tool_arguments.py",),
    ),
    Barriere(
        nom="identifiant-requete",
        sec="SEC-12",
        ce_quelle_empeche="un saut de ligne fabriquerait une fausse ligne de journal",
        neutraliser=_casser_identifiant_requete,
        tests=("tests/security/test_sec12_log_leaks.py",),
    ),
    Barriere(
        nom="guardrail-sortie",
        sec="SEC-02",
        ce_quelle_empeche="un secret reconnaissable atteindrait le client",
        neutraliser=_casser_guardrail_sortie,
        tests=("tests/security/test_sec02_output_leak.py",),
    ),
    Barriere(
        nom="plafond-longueur",
        sec="SEC-10",
        ce_quelle_empeche="une generation emballee emettrait sans fin",
        neutraliser=_casser_plafond_longueur,
        tests=("tests/security/test_sec10_output_limits.py",),
    ),
    Barriere(
        nom="plafond-iterations",
        sec="SEC-06",
        ce_quelle_empeche="un agent qui ne trouve rien relancerait indefiniment",
        neutraliser=_casser_plafond_iterations,
        tests=("tests/security/test_sec06_agent_limits.py",),
    ),
    Barriere(
        nom="appels-par-tour",
        sec="SEC-06",
        ce_quelle_empeche="un modele detourne multiplierait les appels sortants",
        neutraliser=_casser_appels_par_tour,
        tests=("tests/security/test_sec06_agent_limits.py",),
    ),
    Barriere(
        nom="liste-blanche-outils",
        sec="SEC-06",
        ce_quelle_empeche="un outil hors perimetre serait execute",
        neutraliser=_casser_liste_blanche,
        tests=("tests/security/test_sec06_agent_limits.py",),
    ),
    Barriere(
        nom="longueur-question",
        sec="SEC-10",
        ce_quelle_empeche="une question demesuree gonflerait le prompt et le cout",
        neutraliser=_casser_longueur_question,
        tests=(
            "tests/security/test_sec10_output_limits.py",
            "tests/security/test_sec11_error_handling.py",
            "tests/unit/test_agent_service.py",
        ),
    ),
)

PAR_NOM = {barriere.nom: barriere for barriere in BARRIERES}
