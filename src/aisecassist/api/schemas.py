"""Schemas d'entree et de sortie de l'API.

Premiere barriere de la chaine : toute requete est hostile jusqu'a preuve du
contraire (CLAUDE.md, regle d'or 4). Ce qui ne passe pas ces schemas n'atteint
jamais le metier.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Plafond de longueur d'une question. Limite de securite plus que de confort :
# une question tres longue gonfle le prompt, donc le cout et la latence
# (SECURITY.md, SEC-10). Volontairement non configurable par environnement, au
# meme titre que la liste blanche d'extensions a l'ingestion.
MAX_QUESTION_LENGTH = 2_000


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

    source: str
    score: float


class QueryResponse(BaseModel):
    """Reponse du systeme, accompagnee de ses sources."""

    answer: str
    sources: list[SourceRef]
