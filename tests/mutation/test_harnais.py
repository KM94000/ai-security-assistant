"""Harnais de mutation : mes tests peuvent-ils echouer ? (ticket 27)

Une suite verte ne prouve rien par elle-meme. Un test passe parce que le code
est juste, ou parce qu'il ne verifie rien. Ce module pose la question inverse :

    **Si je desactive une barriere de securite, un test s'en apercoit-il ?**

Pour chaque barriere de `barrieres.py` : la neutraliser, relancer les tests
censes la couvrir, et verifier qu'au moins un rougit. Une barriere qui n'en
fait rougir aucun est une barriere que **personne ne teste** — la supprimer
passerait inapercu.

**Precedent concret.** Cette campagne, menee a la main au ticket 23, a revele
que la validation d'identifiant CVE ne tuait que 2 tests sur 12 : les huit
autres charges etaient arretees par le plafond de longueur de pydantic avant
d'atteindre l'expression reguliere. La couverture de ligne disait « couvert ».

C'est la difference que ce module industrialise : la couverture dit quelles
lignes se sont executees, la mutation dit si quelqu'un aurait remarque
qu'elles etaient fausses.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.mutation.barrieres import BARRIERES, Barriere
from tests.mutation.plugin import VARIABLE

pytestmark = pytest.mark.mutation

_RACINE = Path(__file__).resolve().parents[2]
_DELAI_MAX_S = 300.0
"""Une mutation qui pend est un echec, pas une attente."""

_MOTIF_ECHEC = re.compile(r"^FAILED (\S+)", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Resultat:
    """Ce qu'une barriere neutralisee a provoque."""

    barriere: Barriere
    tues: tuple[str, ...]
    """Identifiants des tests qui ont rougi. Vides = la barriere a survecu."""
    code_retour: int

    @property
    def survivante(self) -> bool:
        """Vrai si aucun test n'a vu la difference."""
        return not self.tues


def _executer(barriere: Barriere) -> Resultat:
    """Neutralise une barriere dans un sous-processus et releve les degats."""
    environnement = {**os.environ, VARIABLE: barriere.nom}
    commande = [
        sys.executable,
        "-m",
        "pytest",
        *barriere.tests,
        "-p",
        "tests.mutation.plugin",
        "-q",
        "--no-header",
        "--tb=no",
        # Liste les echecs par leur identifiant : c'est ce qui rend le
        # rapport actionnable plutot que seulement verdict.
        "-rf",
    ]

    acheve = subprocess.run(  # noqa: S603 — commande construite ici, pas d'entree externe
        commande,
        cwd=_RACINE,
        env=environnement,
        capture_output=True,
        text=True,
        timeout=_DELAI_MAX_S,
        check=False,
    )
    sortie = acheve.stdout + acheve.stderr
    return Resultat(
        barriere=barriere,
        tues=tuple(_MOTIF_ECHEC.findall(sortie)),
        code_retour=acheve.returncode,
    )


def _rapport(resultats: list[Resultat]) -> str:
    """Rapport lisible : ce qui manque, et ou.

    Un harnais dont l'echec dit « assertion failed » n'a pas de produit. Le
    produit, c'est de savoir quelle barriere n'est pas couverte et par quoi
    elle aurait du l'etre.
    """
    lignes = ["", "Campagne de mutation — une barriere neutralisee a la fois :", ""]
    for resultat in resultats:
        barriere = resultat.barriere
        marque = "SURVIT" if resultat.survivante else f"{len(resultat.tues):>2} tues"
        lignes.append(f"  [{marque:>8}] {barriere.nom:<22} {barriere.sec}")
        if resultat.survivante:
            lignes.append(f"             sans elle : {barriere.ce_quelle_empeche}")
            lignes.append(f"             auraient du couvrir : {', '.join(barriere.tests)}")
            if resultat.code_retour == 0:
                lignes.append("             (les tests sont passes malgre la mutation)")
            else:
                lignes.append(
                    f"             (code retour {resultat.code_retour} sans echec nomme "
                    "— la mutation a peut-etre casse la collecte)"
                )
    lignes.append("")
    return "\n".join(lignes)


def test_chaque_barriere_de_securite_fait_rougir_au_moins_un_test() -> None:
    """Aucune barriere ne doit pouvoir disparaitre en silence.

    Le seuil est volontairement a **un** test, pas a un pourcentage. Un score
    de mutation agrege se contemple ; « cette barriere n'est testee par rien »
    se corrige.
    """
    resultats = [_executer(barriere) for barriere in BARRIERES]
    survivantes = [resultat.barriere.nom for resultat in resultats if resultat.survivante]

    assert not survivantes, _rapport(resultats)


def test_une_barriere_inconnue_est_refusee() -> None:
    """Le harnais ne doit pas rendre un vert pour une barriere qui n'existe pas.

    Sans ce controle, une faute de frappe dans la table produirait une
    campagne qui ne mute rien et passe — le pire resultat possible pour un
    outil dont le role est de detecter l'absence de verification.
    """
    acheve = subprocess.run(  # noqa: S603 — commande construite ici
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/security/test_sec05_tool_arguments.py",
            "-p",
            "tests.mutation.plugin",
            "-q",
            "--no-header",
        ],
        cwd=_RACINE,
        env={**os.environ, VARIABLE: "barriere-qui-nexiste-pas"},
        capture_output=True,
        text=True,
        timeout=_DELAI_MAX_S,
        check=False,
    )

    assert acheve.returncode != 0
    assert "Barriere inconnue" in acheve.stdout + acheve.stderr
