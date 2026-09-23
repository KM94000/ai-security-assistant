"""Outil de consultation d'une CVE dans la base du NIST (ticket 20, ADR-0012).

C'est le premier outil du projet qui **sort de la machine**. Trois proprietes
le distinguent de la recherche dans le corpus, et structurent ce module.

**1. Le modele choisit QUOI, jamais OU.** L'hote et le chemin viennent de la
configuration ; le modele ne fournit qu'un identifiant de CVE, valide par une
expression reguliere stricte avant tout appel, et transmis comme *parametre de
requete* — jamais concatene dans une URL. Un modele detourne ne peut donc pas
faire appeler un service tiers par le serveur (SSRF, SEC-06).

**2. La reponse est du contenu tiers.** Une description de CVE est du texte que
personne n'a ecrit pour nous : elle est plafonnee et assainie comme un extrait
du corpus avant d'entrer dans le prompt (SEC-01b, SEC-10).

**3. Une panne du service n'est pas une panne du produit.** Le NIST peut etre
injoignable, lent, ou refuser la requete pour cause de quota. Aucun de ces cas
ne fait tomber la requete : l'outil rend une observation explicite, et l'agent
repond en disant qu'il n'a pas pu verifier. Une reponse honnete vaut mieux
qu'une erreur 503, et bien mieux qu'une reponse qui tait l'echec.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from types import TracebackType
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from aisecassist.agents.tools import Tool, ToolArgumentError, ToolResult
from aisecassist.llm.base import ToolSpec
from aisecassist.security.prompt_sanitation import neutralize_markers

logger = logging.getLogger(__name__)

_CHEMIN = "/rest/json/cves/2.0"
_EN_TETE_CLE = "apiKey"

# Format officiel d'un identifiant CVE : annee sur 4 chiffres, sequence sur 4 a
# 7. L'ancrage aux deux extremites est ce qui compte : sans lui, "CVE-2021-4422
# &resultsPerPage=2000" passerait la validation.
_MOTIF_CVE = re.compile(r"^CVE-\d{4}-\d{4,7}$")

# Page publique correspondante, construite a partir de l'identifiant DEJA valide.
_DETAIL_URL = "https://nvd.nist.gov/vuln/detail/{identifiant}"

CVE_INCONNUE = "Aucune vulnerabilite {identifiant} dans la base du NIST."
"""Observation rendue quand l'identifiant est bien forme mais introuvable.

Le pendant, pour cet outil, de l'absence d'extrait pertinent : une phrase
explicite plutot qu'un resultat vide, pour que le modele puisse conclure.
"""

SERVICE_INDISPONIBLE = (
    "La base du NIST n'a pas repondu. Reponds sans cette verification, "
    "et precise que l'information n'a pas pu etre confirmee."
)
QUOTA_DEPASSE = (
    "La base du NIST a refuse la requete : trop d'appels en peu de temps. "
    "Reponds sans cette verification, et precise-le."
)


class _ArgumentsCve(BaseModel):
    """Forme exigee des arguments, quoi qu'annonce le modele.

    La validation ne se contente pas d'exiger une chaine : elle impose le
    **format exact** d'un identifiant CVE. C'est la seule barriere qui compte
    ici, puisque la valeur part ensuite vers un service externe.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Bornes exactes du format : "CVE-2021-4422" fait 13 caracteres,
    # "CVE-2021-1234567" en fait 16. Le motif ci-dessous reste le vrai controle.
    identifiant: str = Field(min_length=13, max_length=16)

    @field_validator("identifiant")
    @classmethod
    def _exiger_le_format_cve(cls, valeur: str) -> str:
        """Normalise la casse, puis refuse tout ce qui n'est pas un identifiant CVE.

        La mise en majuscules precede la verification : un modele ecrit
        volontiers `cve-2021-44228`, et le refuser n'apporterait aucune securite
        — la regle d'apres rejette de toute facon tout ce qui n'a pas la forme
        attendue.
        """
        normalise = valeur.upper()
        if not _MOTIF_CVE.match(normalise):
            raise ValueError("identifiant CVE attendu, de la forme CVE-AAAA-NNNN")
        return normalise


class CveLookupTool(Tool):
    """Consulte une CVE dans la base publique du NIST. Lecture seule.

    Le client httpx est injectable, comme pour `OllamaProvider` : les tests
    unitaires fournissent un transport factice et couvrent ainsi les pannes du
    service — quota, delai depasse, JSON illisible — sans reseau et sans
    dependre de la disponibilite d'un tiers (ADR-0002).
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float,
        *,
        api_key: str | None = None,
        description_max_chars: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._description_max = description_max_chars
        # Meme regle que pour le fournisseur LLM : on ne ferme que le client
        # qu'on a cree soi-meme.
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="consulter_cve",
            description=(
                "Consulte la base de vulnerabilites du NIST (NVD) pour un identifiant "
                "CVE precis, et renvoie sa description, sa date de publication et son "
                "score de gravite CVSS. A utiliser uniquement quand la question porte "
                "sur une CVE nommee. Pour une question de fond sur une categorie de "
                "risque ou une bonne pratique, utiliser la recherche dans le corpus."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "identifiant": {
                        "type": "string",
                        "description": "L'identifiant de la CVE, par exemple CVE-2021-44228.",
                    }
                },
                "required": ["identifiant"],
            },
        )

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            valides = _ArgumentsCve.model_validate(dict(arguments))
        except ValidationError as exc:
            raise ToolArgumentError(
                f"Arguments refuses : {exc.error_count()} champ(s) invalide(s). "
                "Un identifiant CVE de la forme CVE-AAAA-NNNN est attendu."
            ) from exc

        identifiant = valides.identifiant
        # L'identifiant est journalise : il est valide, donc sans surprise, et
        # savoir quelle CVE a ete consultee est utile. Aucune cle d'API ni
        # aucune URL complete n'apparait ici (SEC-12).
        logger.info("Consultation de %s dans la base du NIST.", identifiant)

        donnees = await self._interroger(identifiant)
        if isinstance(donnees, str):
            # Une panne du service : l'observation dit quoi faire au modele.
            return ToolResult(observation=donnees)

        return self._rendre(identifiant, donnees)

    async def aclose(self) -> None:
        """Libere le client HTTP si cet outil en est proprietaire."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> CveLookupTool:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # --- Appel au service -----------------------------------------------------

    async def _interroger(self, identifiant: str) -> dict[str, Any] | str:
        """Appelle le NIST, ou renvoie le message d'echec a rendre au modele.

        Le type de retour dit l'intention : un dictionnaire quand l'appel a
        abouti, une chaine quand il a echoue. Aucun de ces echecs n'est une
        exception, parce qu'aucun ne justifie de faire tomber la requete.
        """
        en_tetes = {_EN_TETE_CLE: self._api_key} if self._api_key else None
        try:
            # `params=` et non une URL assemblee a la main : httpx encode la
            # valeur, ce qui neutralise tout caractere de separation qui aurait
            # survecu a la validation.
            reponse = await self._client.get(
                _CHEMIN, params={"cveId": identifiant}, headers=en_tetes
            )
        except httpx.HTTPError as exc:
            logger.warning("Appel au NIST echoue pour %s (%s).", identifiant, type(exc).__name__)
            return SERVICE_INDISPONIBLE

        if reponse.status_code in (403, 429):
            # Le NIST limite a 5 requetes par 30 s sans cle d'API. Le cas est
            # donc attendu en usage normal, pas exceptionnel.
            logger.warning("Quota NIST depasse (HTTP %d).", reponse.status_code)
            return QUOTA_DEPASSE
        if reponse.status_code == 404:
            return CVE_INCONNUE.format(identifiant=identifiant)
        if reponse.status_code >= 400:
            logger.warning("Reponse inattendue du NIST : HTTP %d.", reponse.status_code)
            return SERVICE_INDISPONIBLE

        try:
            donnees: Any = reponse.json()
        except json.JSONDecodeError:
            logger.warning("Reponse du NIST illisible : JSON invalide.")
            return SERVICE_INDISPONIBLE

        if not isinstance(donnees, dict):
            logger.warning("Reponse du NIST inattendue : objet JSON attendu.")
            return SERVICE_INDISPONIBLE
        return donnees

    # --- Mise en forme --------------------------------------------------------

    def _rendre(self, identifiant: str, donnees: dict[str, Any]) -> ToolResult:
        """Extrait ce qui sert a repondre, en verifiant chaque forme."""
        cve = _premiere_cve(donnees)
        if cve is None:
            return ToolResult(observation=CVE_INCONNUE.format(identifiant=identifiant))

        lignes = [f"{identifiant} — base de vulnerabilites du NIST"]
        publiee = cve.get("published")
        if isinstance(publiee, str) and publiee:
            lignes.append(f"Publiee le : {publiee[:10]}")

        gravite = _gravite(cve)
        if gravite is not None:
            lignes.append(f"Gravite CVSS : {gravite}")

        lignes.append(f"Description : {self._description(cve)}")

        return ToolResult(
            observation="\n".join(lignes),
            sources=(_DETAIL_URL.format(identifiant=identifiant),),
        )

    def _description(self, cve: Mapping[str, Any]) -> str:
        """Rend la description anglaise, plafonnee et assainie."""
        texte = _description_anglaise(cve)
        if texte is None:
            return "(non fournie par le NIST)"
        if len(texte) > self._description_max:
            texte = texte[: self._description_max] + " […]"
        # Texte tiers : il ne doit pas pouvoir forger une cloture de contexte.
        return neutralize_markers(texte)


def _premiere_cve(donnees: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Extrait la premiere entree utilisable, ou None si la reponse est vide.

    Une requete sur un identifiant bien forme mais inexistant renvoie un 200
    avec une liste vide : l'absence est une reponse normale du service, pas une
    erreur.
    """
    vulnerabilites = donnees.get("vulnerabilities")
    if not isinstance(vulnerabilites, list) or not vulnerabilites:
        return None
    premiere = vulnerabilites[0]
    if not isinstance(premiere, dict):
        return None
    cve = premiere.get("cve")
    return cve if isinstance(cve, dict) else None


def _description_anglaise(cve: Mapping[str, Any]) -> str | None:
    """Choisit la description anglaise, a defaut la premiere disponible."""
    descriptions = cve.get("descriptions")
    if not isinstance(descriptions, list):
        return None

    repli: str | None = None
    for entree in descriptions:
        if not isinstance(entree, dict):
            continue
        valeur = entree.get("value")
        if not isinstance(valeur, str) or not valeur.strip():
            continue
        if entree.get("lang") == "en":
            return valeur.strip()
        repli = repli or valeur.strip()
    return repli


def _gravite(cve: Mapping[str, Any]) -> str | None:
    """Rend le score CVSS v3.1 sous une forme lisible, ou None s'il est absent.

    Seule la v3.1 est lue. La v2 existe encore dans la base pour les CVE
    anciennes, mais ses scores ne sont pas comparables a ceux de la v3 : les
    melanger dans une meme phrase induirait le modele en erreur.
    """
    metriques = cve.get("metrics")
    if not isinstance(metriques, dict):
        return None
    liste = metriques.get("cvssMetricV31")
    if not isinstance(liste, list) or not liste:
        return None
    premiere = liste[0]
    if not isinstance(premiere, dict):
        return None
    donnees = premiere.get("cvssData")
    if not isinstance(donnees, dict):
        return None

    score = donnees.get("baseScore")
    severite = donnees.get("baseSeverity")
    if not isinstance(score, (int, float)):
        return None
    if isinstance(severite, str) and severite:
        return f"{score}/10 ({severite})"
    return f"{score}/10"
