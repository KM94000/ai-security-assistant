"""Greffon pytest qui neutralise une barriere nommee par l'environnement.

Charge explicitement par le harnais, jamais par la suite ordinaire :

    AISECASSIST_MUTATION=format-cve pytest -p tests.mutation.plugin tests/security

**Pourquoi un sous-processus et un greffon, plutot qu'un monkeypatch en cours
de session.** Certaines barrieres sont figees a l'import — la contrainte de
longueur du schema pydantic est construite au moment ou la classe est definie.
Les muter apres coup ne changerait rien, et la barriere paraitrait survivre
alors qu'elle n'a jamais ete touchee. Un faux negatif y serait invisible.

`pytest_configure` s'execute avant la collecte, donc avant que les modules de
test n'importent quoi que ce soit : c'est le dernier moment ou la mutation est
encore sure de precéder ce qu'elle doit affecter.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from tests.mutation.barrieres import PAR_NOM

VARIABLE = "AISECASSIST_MUTATION"

_patch = pytest.MonkeyPatch()


def pytest_configure(config: Any) -> None:
    """Applique la mutation demandee, s'il y en a une."""
    nom = os.environ.get(VARIABLE, "").strip()
    if not nom:
        return

    barriere = PAR_NOM.get(nom)
    if barriere is None:
        connues = ", ".join(sorted(PAR_NOM))
        raise pytest.UsageError(f"Barriere inconnue : {nom!r}. Connues : {connues}.")

    barriere.neutraliser(_patch)


def pytest_unconfigure(config: Any) -> None:
    """Retire la mutation. Sans effet dans un sous-processus, mais correct."""
    _patch.undo()
