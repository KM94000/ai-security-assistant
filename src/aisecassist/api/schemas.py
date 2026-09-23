"""Schemas d'entree et de sortie de l'API.

Premiere barriere de la chaine : toute requete est hostile jusqu'a preuve du
contraire (CLAUDE.md, regle d'or 4). Ce qui ne passe pas ces schemas n'atteint
jamais le metier.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aisecassist.security.limits import MAX_QUESTION_LENGTH


class QueryRequest(BaseModel):
    """Question posee au systeme."""

    # extra="forbid" : un champ inattendu fait echouer la requete au lieu d'etre
    # ignore en silence. Ignorer masque autant les fautes de frappe d'un client
    # legitime que les tentatives de passer des parametres non prevus.
    # str_strip_whitespace : sans lui, une question faite de trois espaces
    # satisferait min_length=1 et arriverait vide jusqu'au retrieval.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_LENGTH,
        description="Question de cybersecurite, en langage naturel.",
        examples=["Comment se defendre contre une injection de prompt indirecte ?"],
    )


class SourceRef(BaseModel):
    """Extrait ayant alimente la reponse.

    Renvoye systematiquement : une reponse de securite sans provenance n'est pas
    verifiable, et une reponse non verifiable est inutilisable (LLM09).
    """

    model_config = ConfigDict(
        json_schema_extra={"example": {"source": "owasp-llm-top10.md", "score": 0.58}}
    )

    source: str = Field(description="Nom du document dont l'extrait provient.")
    score: float = Field(description="Similarite entre la question et l'extrait, de 0 a 1.")


class QueryResponse(BaseModel):
    """Reponse du systeme, accompagnee de ses sources."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "answer": (
                    "L'injection indirecte transite par un document ingere par le "
                    "systeme. La charge n'agit pas au moment ou elle entre, mais au "
                    "moment ou elle est recuperee, souvent pour un autre utilisateur."
                ),
                "sources": [
                    {"source": "owasp-llm-top10.md", "score": 0.58},
                    {"source": "mitre-atlas.md", "score": 0.54},
                ],
            }
        }
    )

    answer: str = Field(
        description=(
            "Reponse construite a partir du contexte. Si le corpus ne permet pas de "
            "repondre, contient un refus explicite plutot qu'une supposition."
        )
    )
    sources: list[SourceRef] = Field(
        description="Extraits reellement recuperes, du plus pertinent au moins pertinent."
    )


class AgentResponse(BaseModel):
    """Reponse de l'agent, avec de quoi la verifier et comprendre son cheminement.

    Les sources sont ici de simples chaines, sans score, la ou `/query` renvoie
    un score par extrait. Ce n'est pas un oubli : l'agent peut citer des
    provenances qui ne viennent pas d'une recherche vectorielle — la fiche
    publique d'une CVE, par exemple — et un score de similarite n'y aurait
    aucun sens.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "answer": (
                    "La CVE-2021-44228 (Log4Shell) permet l'execution de code a distance "
                    "via une requete JNDI dans un message journalise. Sa gravite CVSS est "
                    "de 10/10. Le corpus la rattache a la categorie « supply chain » du "
                    "OWASP LLM Top 10."
                ),
                "sources": [
                    "https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
                    "owasp-llm-top10.md",
                ],
                "iterations": 2,
            }
        }
    )

    answer: str = Field(description="Reponse finale, apres d'eventuels appels d'outils.")
    sources: list[str] = Field(
        description=(
            "Provenances citees par les outils reellement executes. Une liste vide "
            "signifie que l'agent a repondu sans consulter aucune source."
        )
    )
    iterations: int = Field(
        description=(
            "Nombre de tours d'outils effectues. Zero signifie que le modele a repondu "
            "directement, sans rien consulter."
        )
    )
