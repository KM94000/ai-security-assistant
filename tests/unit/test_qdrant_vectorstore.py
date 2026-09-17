"""Tests de `QdrantVectorStore`.

Aucun conteneur : `AsyncQdrantClient(":memory:")` embarque le vrai moteur
Qdrant. On verifie donc le comportement reel de la base — creation de
collection, similarite, idempotence — et pas un double qui rejouerait nos
hypotheses.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from qdrant_client import AsyncQdrantClient, models

from aisecassist.vectorstore.base import (
    CollectionDimensionMismatchError,
    CollectionEmbeddingModelMismatchError,
    VectorStoreError,
)
from aisecassist.vectorstore.qdrant import QdrantVectorStore

pytestmark = pytest.mark.anyio

_COLLECTION = "test_collection"
_DIM = 4
_MODELE = "modele-a@rev-1"

_VEC_A = [1.0, 0.0, 0.0, 0.0]
_VEC_B = [0.0, 1.0, 0.0, 0.0]


@pytest.fixture
async def store() -> AsyncIterator[QdrantVectorStore]:
    client = AsyncQdrantClient(location=":memory:")
    try:
        yield QdrantVectorStore(
            url="", collection=_COLLECTION, embedding_model=_MODELE, client=client
        )
    finally:
        await client.close()


async def test_ensure_collection_cree_la_collection(store: QdrantVectorStore) -> None:
    await store.ensure_collection(_DIM)

    # La preuve qu'elle existe : on peut y chercher sans erreur.
    assert await store.search(_VEC_A, k=1) == []


async def test_ensure_collection_est_idempotent(store: QdrantVectorStore) -> None:
    """Rejouer l'initialisation ne doit rien detruire ni echouer."""
    await store.ensure_collection(_DIM)
    await store.add(["extrait"], [_VEC_A], ["owasp.md"])

    await store.ensure_collection(_DIM)

    assert len(await store.search(_VEC_A, k=5)) == 1


async def test_ensure_collection_refuse_une_dimension_differente(
    store: QdrantVectorStore,
) -> None:
    """Garde-fou : une collection de 4 ne doit pas accueillir des vecteurs de 8.

    Sans ce controle, la recherche continuerait de repondre en renvoyant des
    resultats incoherents, ce qui ressemble a un simple probleme de pertinence
    (SECURITY.md, SEC-08).
    """
    await store.ensure_collection(_DIM)

    with pytest.raises(CollectionDimensionMismatchError) as excinfo:
        await store.ensure_collection(8)

    assert "4" in str(excinfo.value)
    assert "8" in str(excinfo.value)


async def test_add_puis_search_renvoie_lextrait_avec_sa_provenance(
    store: QdrantVectorStore,
) -> None:
    await store.ensure_collection(_DIM)
    await store.add(["Valider les entrees."], [_VEC_A], ["owasp-llm-top10.md"])

    results = await store.search(_VEC_A, k=1)

    assert len(results) == 1
    assert results[0].text == "Valider les entrees."
    assert results[0].source == "owasp-llm-top10.md"
    assert results[0].score == pytest.approx(1.0)


async def test_search_ordonne_du_plus_proche_au_plus_loin(store: QdrantVectorStore) -> None:
    await store.ensure_collection(_DIM)
    await store.add(
        ["proche", "eloigne"],
        [_VEC_A, _VEC_B],
        ["a.md", "b.md"],
    )

    results = await store.search(_VEC_A, k=2)

    assert [r.text for r in results] == ["proche", "eloigne"]
    assert results[0].score > results[1].score


async def test_search_respecte_la_limite_k(store: QdrantVectorStore) -> None:
    await store.ensure_collection(_DIM)
    await store.add(["un", "deux"], [_VEC_A, _VEC_B], ["a.md", "b.md"])

    assert len(await store.search(_VEC_A, k=1)) == 1


async def test_reindexer_le_meme_extrait_ne_cree_pas_de_doublon(
    store: QdrantVectorStore,
) -> None:
    """Re-ingerer un corpus ne doit pas dupliquer son contenu.

    Les identifiants de points sont derives de (source, texte). Sans cela, une
    seconde ingestion renverrait le meme passage plusieurs fois en reponse,
    gaspillant le budget de contexte du modele.
    """
    await store.ensure_collection(_DIM)
    for _ in range(3):
        await store.add(["meme extrait"], [_VEC_A], ["source.md"])

    assert len(await store.search(_VEC_A, k=10)) == 1


async def test_un_meme_texte_de_deux_sources_reste_deux_entrees(
    store: QdrantVectorStore,
) -> None:
    """La provenance fait partie de l'identite : deux sources, deux entrees."""
    await store.ensure_collection(_DIM)
    await store.add(["texte identique"], [_VEC_A], ["premiere.md"])
    await store.add(["texte identique"], [_VEC_A], ["seconde.md"])

    assert len(await store.search(_VEC_A, k=10)) == 2


async def test_add_refuse_des_sequences_desalignees(store: QdrantVectorStore) -> None:
    """Deux textes pour une seule source associerait un extrait a la mauvaise origine.

    L'erreur serait invisible : la reponse citerait une source qui ne contient
    pas ce qu'elle affirme.
    """
    await store.ensure_collection(_DIM)

    with pytest.raises(VectorStoreError):
        await store.add(["un", "deux"], [_VEC_A, _VEC_B], ["une-seule-source.md"])


async def test_add_sur_des_sequences_vides_ne_fait_rien(store: QdrantVectorStore) -> None:
    await store.ensure_collection(_DIM)

    await store.add([], [], [])

    assert await store.search(_VEC_A, k=1) == []


async def test_search_refuse_un_k_non_positif(store: QdrantVectorStore) -> None:
    await store.ensure_collection(_DIM)

    with pytest.raises(VectorStoreError):
        await store.search(_VEC_A, k=0)


async def test_un_point_sans_provenance_est_ecarte_sans_faire_echouer_la_recherche() -> None:
    """Un extrait sans source n'est jamais rendu, mais il ne fait pas tomber la requete.

    Une premiere version levait une erreur, ce qui transformait une seule donnee
    corrompue en panne totale : un point malforme proche du centre de l'espace
    vectoriel entrait dans le top-k de presque toutes les requetes, et /query
    renvoyait 503 pour tout le monde jusqu'a nettoyage manuel de la base.

    La propriete de securite est identique — aucun extrait sans provenance n'est
    rendu — mais la disponibilite ne depend plus de l'integrite de chaque point.
    """
    client = AsyncQdrantClient(location=":memory:")
    try:
        store = QdrantVectorStore(
            url="", collection=_COLLECTION, embedding_model=_MODELE, client=client
        )
        await store.ensure_collection(_DIM)
        await store.add(["extrait valide"], [_VEC_A], ["source.md"])
        await client.upsert(
            _COLLECTION,
            points=[models.PointStruct(id=1, vector=_VEC_A, payload={"text": "orphelin"})],
        )

        resultats = await store.search(_VEC_A, k=10)

        assert [r.text for r in resultats] == ["extrait valide"]
        assert all(r.source for r in resultats)

    finally:
        await client.close()


# --- Modele d'embeddings inscrit dans la collection (ADR-0010) ---------------


@pytest.fixture
async def client() -> AsyncIterator[AsyncQdrantClient]:
    client = AsyncQdrantClient(location=":memory:")
    try:
        yield client
    finally:
        await client.close()


def _store(client: AsyncQdrantClient, modele: str = _MODELE) -> QdrantVectorStore:
    return QdrantVectorStore(url="", collection=_COLLECTION, embedding_model=modele, client=client)


async def test_une_nouvelle_instance_du_meme_modele_reprend_la_collection(
    client: AsyncQdrantClient,
) -> None:
    """Le modele est relu dans la collection, pas deduit de l'instance qui l'a creee.

    C'est le cas du redemarrage de l'API : une nouvelle instance, une collection
    existante.
    """
    createur = _store(client)
    await createur.ensure_collection(_DIM)
    await createur.add(["extrait"], [_VEC_A], ["owasp.md"])

    assert len(await _store(client).search(_VEC_A, k=1)) == 1


async def test_lingestion_refuse_une_collection_indexee_par_un_autre_modele(
    client: AsyncQdrantClient,
) -> None:
    """A dimension egale, le controle de dimension ne voit rien : c'est ce test qui compte.

    Le message nomme les deux modeles, pour que la panne se diagnostique sans
    lire le code.
    """
    await _store(client, "modele-a@rev-1").ensure_collection(_DIM)

    with pytest.raises(CollectionEmbeddingModelMismatchError) as excinfo:
        await _store(client, "modele-b@rev-1").ensure_collection(_DIM)

    assert "modele-a@rev-1" in str(excinfo.value)
    assert "modele-b@rev-1" in str(excinfo.value)


async def test_une_autre_revision_du_meme_modele_est_refusee(client: AsyncQdrantClient) -> None:
    """Deux revisions des memes poids ne produisent pas des vecteurs identiques."""
    await _store(client, "modele-a@rev-1").ensure_collection(_DIM)

    with pytest.raises(CollectionEmbeddingModelMismatchError):
        await _store(client, "modele-a@rev-2").ensure_collection(_DIM)


async def test_la_recherche_refuse_une_collection_indexee_par_un_autre_modele(
    client: AsyncQdrantClient,
) -> None:
    """Le chemin de l'API : il ne passe jamais par `ensure_collection`.

    Sans ce controle a la lecture, la requete repondrait normalement, avec des
    extraits choisis au hasard.
    """
    createur = _store(client, "modele-a@rev-1")
    await createur.ensure_collection(_DIM)
    await createur.add(["extrait"], [_VEC_A], ["owasp.md"])

    with pytest.raises(CollectionEmbeddingModelMismatchError):
        await _store(client, "modele-b@rev-1").search(_VEC_A, k=1)


async def test_lecriture_refuse_une_collection_indexee_par_un_autre_modele(
    client: AsyncQdrantClient,
) -> None:
    """Ecrire est pire que lire : le melange des deux espaces resterait en base."""
    await _store(client, "modele-a@rev-1").ensure_collection(_DIM)
    intrus = _store(client, "modele-b@rev-1")

    with pytest.raises(CollectionEmbeddingModelMismatchError):
        await intrus.add(["extrait"], [_VEC_A], ["owasp.md"])

    assert await _store(client, "modele-a@rev-1").search(_VEC_A, k=10) == []


async def test_une_collection_qui_ne_declare_aucun_modele_est_refusee(
    client: AsyncQdrantClient,
) -> None:
    """Le cas des collections creees avant l'ADR-0010.

    Rien ne dit avec quel modele leurs vecteurs ont ete produits. Les supposer
    compatibles reviendrait exactement au defaut que ce controle corrige.
    """
    await client.create_collection(
        _COLLECTION,
        vectors_config=models.VectorParams(size=_DIM, distance=models.Distance.COSINE),
    )

    with pytest.raises(CollectionEmbeddingModelMismatchError):
        await _store(client).search(_VEC_A, k=1)
    with pytest.raises(CollectionEmbeddingModelMismatchError):
        await _store(client).ensure_collection(_DIM)


async def test_une_collection_recreee_est_acceptee_sans_redemarrage(
    client: AsyncQdrantClient,
) -> None:
    """Un refus n'est pas memorise : seule une verification reussie l'est.

    La remediation — recreer la collection et re-ingerer — doit suffire. Une API
    qui continuerait de refuser jusqu'au redemarrage transformerait une
    correction en panne prolongee.
    """
    await _store(client, "ancien-modele@rev-1").ensure_collection(_DIM)
    store = _store(client)
    with pytest.raises(CollectionEmbeddingModelMismatchError):
        await store.search(_VEC_A, k=1)

    await client.delete_collection(_COLLECTION)
    await _store(client).ensure_collection(_DIM)

    assert await store.search(_VEC_A, k=1) == []
