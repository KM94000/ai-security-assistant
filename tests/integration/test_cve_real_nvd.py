"""Test d'acceptation de l'outil CVE contre la vraie base du NIST (ticket 20).

Deselectionne par defaut, et **exclu de la CI** : il exige un acces sortant
vers un service tiers dont ni la disponibilite ni le quota ne dependent de
nous.

    pytest -m network

Les tests unitaires couvrent la boucle, les pannes et la validation avec un
transport factice. Celui-ci verifie la seule chose qu'un double ne peut pas
prouver : que le contrat qu'on suppose au NIST est bien le sien — le chemin,
le nom du parametre, et la forme de la reponse.

C'est precisement ce que ce test doit detecter le jour ou le NIST change son
API : un echec ici est une information, pas une gene.
"""

from __future__ import annotations

import anyio
import pytest

from aisecassist.agents.cve import CveLookupTool
from aisecassist.agents.tools import ToolResult
from aisecassist.config import settings

pytestmark = [pytest.mark.integration, pytest.mark.network]

# Log4Shell : publiee en 2021, notee 10/10, et suffisamment structurante pour
# qu'on puisse parier qu'elle ne disparaitra pas de la base.
_LOG4SHELL = "CVE-2021-44228"


def _consulter(identifiant: str) -> ToolResult:
    async def _executer() -> ToolResult:
        async with CveLookupTool(
            base_url=settings.nvd_base_url,
            timeout_s=settings.nvd_timeout_s,
            api_key=settings.nvd_api_key,
            description_max_chars=settings.cve_description_max_chars,
        ) as outil:
            return await outil.run({"identifiant": identifiant})

    return anyio.run(_executer)


def test_une_cve_reelle_est_decrite_avec_sa_gravite() -> None:
    """Le contrat suppose au NIST est verifie de bout en bout."""
    resultat = _consulter(_LOG4SHELL)

    assert _LOG4SHELL in resultat.observation
    assert "Gravite CVSS : 10.0/10 (CRITICAL)" in resultat.observation
    assert "Log4j" in resultat.observation
    assert resultat.sources == (f"https://nvd.nist.gov/vuln/detail/{_LOG4SHELL}",)


def test_un_identifiant_bien_forme_mais_inexistant_est_annonce_comme_tel() -> None:
    """L'absence est une reponse du service, pas une panne.

    Le NIST renvoie un 200 avec une liste vide. Confondre ce cas avec une
    indisponibilite ferait dire au modele « je n'ai pas pu verifier » la ou la
    reponse correcte est « cette CVE n'existe pas ».
    """
    resultat = _consulter("CVE-2000-9999")

    assert "Aucune vulnerabilite" in resultat.observation
    assert resultat.sources == ()
