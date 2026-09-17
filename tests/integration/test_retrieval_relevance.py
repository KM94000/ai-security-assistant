"""Le seuil de pertinence tient-il sur le vrai corpus, avec le vrai modele ? (ADR-0010)

Deselectionne par defaut. Exige Qdrant demarre ; tourne en CI :

    docker compose -f docker/docker-compose.yml up -d qdrant
    pytest -m integration

`retrieval_min_score` n'a de sens que pour un modele, une revision et un
decoupage donnes : il a ete fixe par la mesure, pas au juge. Ce module rejoue
cette mesure a chaque execution. Si un changement deplace les scores, il echoue
en affichant chaque score — de quoi recalibrer plutot que deviner.

Deux jeux de questions, et la distinction compte :

- **calibrage** : ceux qui ont servi a choisir le seuil, au milieu entre le pire
  score des questions couvertes et le meilleur score des questions hors sujet ;
- **controle** : ecrits avant de connaitre les scores, et jamais utilises pour
  choisir. Un seuil qui ne tiendrait que sur ses propres questions de calibrage
  serait cale sur le test cense le verifier.

Pour recalibrer : ajuster le seuil sur le calibrage seul, verifier le controle,
et consigner les chiffres dans l'ADR. Ajuster sur le controle le transformerait
en calibrage, et il faudrait alors en ecrire un nouveau.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import anyio
import pytest
from qdrant_client import AsyncQdrantClient

from aisecassist.config import settings
from aisecassist.embeddings.sentence_transformer import SentenceTransformerEmbedder
from aisecassist.ingestion.pipeline import IngestionPipeline
from aisecassist.retrieval.service import RetrievalService
from aisecassist.vectorstore.qdrant import QdrantVectorStore

pytestmark = pytest.mark.integration

_CORPUS = Path(__file__).resolve().parents[2] / "data" / "corpus"

# Les questions anglaises sont voulues : le modele est multilingue, et un
# utilisateur anglophone doit etre servi par le meme corpus francais.
_CALIBRAGE_COUVERTES = (
    "Comment se defendre contre une injection de prompt indirecte ?",
    "Qu'est-ce que la divulgation d'informations sensibles par un LLM ?",
    "Quels risques pose la chaine d'approvisionnement d'un modele ?",
    "Comment un attaquant empoisonne-t-il les donnees d'entrainement ?",
    "Pourquoi valider les sorties d'un LLM avant de les utiliser ?",
    "Qu'est-ce que l'autonomie excessive d'un agent ?",
    "Comment eviter la fuite du prompt systeme ?",
    "Quelles faiblesses touchent les embeddings et les bases vectorielles ?",
    "Comment un LLM peut-il produire de la desinformation ?",
    "Comment limiter la consommation de ressources d'un LLM ?",
    "Que decrit le referentiel MITRE ATLAS ?",
    "Quelles tactiques d'attaque visent les systemes d'apprentissage automatique ?",
    "Comment un attaquant peut-il voler ou extraire un modele ?",
    "Quelles sont les fonctions du NIST AI RMF ?",
    "Comment gouverner les risques d'un systeme d'IA ?",
    "How do I mitigate prompt injection in a RAG application?",
    "What is excessive agency for LLM agents?",
)
_CALIBRAGE_HORS_SUJET = (
    "Quelle est la recette traditionnelle du cassoulet ?",
    "Qui a gagne la coupe du monde de football 2018 ?",
    "Quelle est la capitale de l'Australie ?",
    "Comment changer un pneu de voiture ?",
    "Quel temps fera-t-il demain a Paris ?",
    "Explique-moi la photosynthese.",
    "What is the best recipe for chocolate cake?",
    "Traduis bonjour en espagnol.",
    "Bonjour, comment vas-tu ?",
    "Ecris un poeme sur la mer.",
)
_CONTROLE_COUVERTES = (
    "Un document malveillant ajoute au corpus peut-il influencer les reponses ?",
    "Quels garde-fous poser sur les outils qu'un agent a le droit d'appeler ?",
    "Comment un attaquant reconstruit-il les consignes cachees d'un assistant ?",
    "A quoi sert la fonction MEASURE du cadre du NIST ?",
    "Pourquoi des messages d'erreur trop detailles aident-ils un attaquant ?",
    "Comment traiter le risque de reponses inventees par le modele ?",
    "Quelles proprietes doit avoir une IA digne de confiance ?",
    "Comment eviter qu'une requete fasse exploser le cout d'inference ?",
    "How can an attacker steal a machine learning model?",
    "Why should LLM output be treated as untrusted?",
)
_CONTROLE_HORS_SUJET = (
    "Combien de temps faut-il pour cuire des pates ?",
    "Quel film me conseilles-tu pour ce soir ?",
    "Comment planter des tomates dans mon jardin ?",
    "Quelle est la distance entre la Terre et la Lune ?",
    "Donne-moi des idees de cadeau d'anniversaire.",
    "Comment reussir une mayonnaise ?",
    "Quels sont les horaires du train pour Lyon ?",
    "How do I bake sourdough bread?",
    "Raconte-moi une blague.",
    "Quelle est la difference entre un crocodile et un alligator ?",
)

_COUVERTES = _CALIBRAGE_COUVERTES + _CONTROLE_COUVERTES
_HORS_SUJET = _CALIBRAGE_HORS_SUJET + _CONTROLE_HORS_SUJET


def _embedder() -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder(
        settings.embedding_model,
        settings.embedding_dimension,
        revision=settings.embedding_model_revision,
    )


def _store(collection: str) -> QdrantVectorStore:
    return QdrantVectorStore(
        settings.qdrant_url, collection, embedding_model=settings.embedding_model_id
    )


@pytest.fixture(scope="module")
def corpus_indexe() -> Iterator[str]:
    """Ingere le corpus une seule fois pour tout le module, dans une collection jetable."""
    nom = f"test_pertinence_{uuid.uuid4().hex[:8]}"

    async def _ingerer() -> None:
        async with _store(nom) as store:
            pipeline = IngestionPipeline(
                _embedder(),
                store,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
                max_document_bytes=settings.max_document_bytes,
            )
            await pipeline.ingest_directory(_CORPUS)

    async def _supprimer() -> None:
        client = AsyncQdrantClient(url=settings.qdrant_url)
        try:
            if await client.collection_exists(nom):
                await client.delete_collection(nom)
        finally:
            await client.close()

    anyio.run(_ingerer)
    try:
        yield nom
    finally:
        anyio.run(_supprimer)


@pytest.fixture(scope="module")
def meilleurs_scores(corpus_indexe: str) -> dict[str, float]:
    """Score du meilleur extrait pour chaque question, avant tout seuil."""

    async def _mesurer() -> dict[str, float]:
        embedder = _embedder()
        scores: dict[str, float] = {}
        async with _store(corpus_indexe) as store:
            for question in _COUVERTES + _HORS_SUJET:
                vecteur = (await embedder.embed([question]))[0]
                scores[question] = (await store.search(vecteur, k=1))[0].score
        return scores

    return anyio.run(_mesurer)


def _rapport(titre: str, fautives: dict[str, float], scores: dict[str, float]) -> str:
    """Message d'echec qui contient de quoi recalibrer, sans relancer quoi que ce soit."""
    seuil = settings.retrieval_min_score
    pire_couverte = min(scores[q] for q in _CALIBRAGE_COUVERTES)
    meilleure_hors_sujet = max(scores[q] for q in _CALIBRAGE_HORS_SUJET)
    lignes = [
        f"{titre} (seuil {seuil:.3f}, modele {settings.embedding_model_id}) :",
        *(f"  {score:.3f}  {question}" for question, score in sorted(fautives.items())),
        "",
        f"Calibrage : pire question couverte {pire_couverte:.3f}, "
        f"meilleure hors sujet {meilleure_hors_sujet:.3f}.",
    ]
    if pire_couverte > meilleure_hors_sujet:
        milieu = (pire_couverte + meilleure_hors_sujet) / 2
        lignes.append(f"Seuil au milieu, selon la regle de l'ADR-0010 : {milieu:.2f}.")
    else:
        lignes.append("Les deux se chevauchent : aucun seuil ne separe ce modele (ADR-0010).")
    lignes += ["", "Tous les scores :"]
    lignes += [f"  {score:.3f}  {question}" for question, score in sorted(scores.items())]
    return "\n".join(lignes)


def test_les_questions_couvertes_par_le_corpus_atteignent_le_seuil(
    meilleurs_scores: dict[str, float],
) -> None:
    """Un refus a tort n'est pas sans consequence : c'est une reponse utile perdue."""
    refusees = {
        question: meilleurs_scores[question]
        for question in _COUVERTES
        if meilleurs_scores[question] < settings.retrieval_min_score
    }

    assert not refusees, _rapport("Questions couvertes refusees", refusees, meilleurs_scores)


def test_les_questions_hors_sujet_restent_sous_le_seuil(
    meilleurs_scores: dict[str, float],
) -> None:
    """Le defaut que le seuil corrige : des extraits sans rapport envoyes au modele."""
    admises = {
        question: meilleurs_scores[question]
        for question in _HORS_SUJET
        if meilleurs_scores[question] >= settings.retrieval_min_score
    }

    assert not admises, _rapport("Questions hors sujet admises", admises, meilleurs_scores)


def test_le_service_ne_renvoie_rien_hors_sujet_et_des_extraits_sinon(corpus_indexe: str) -> None:
    """Les scores ne suffisent pas : le service doit reellement appliquer le seuil.

    C'est ce que l'agent de M3 consommera — une liste vide pour dire « je n'ai
    rien », plutot que k extraits sans rapport.
    """

    async def _interroger() -> tuple[int, list[float]]:
        async with _store(corpus_indexe) as store:
            service = RetrievalService(
                _embedder(),
                store,
                settings.retrieval_top_k,
                min_score=settings.retrieval_min_score,
            )
            hors_sujet = await service.retrieve(
                "Quelle est la recette traditionnelle du cassoulet ?"
            )
            couverte = await service.retrieve("Comment eviter la fuite du prompt systeme ?")
        return len(hors_sujet), [resultat.score for resultat in couverte]

    nb_hors_sujet, scores_couverte = anyio.run(_interroger)

    assert nb_hors_sujet == 0
    assert scores_couverte
    assert all(score >= settings.retrieval_min_score for score in scores_couverte)
