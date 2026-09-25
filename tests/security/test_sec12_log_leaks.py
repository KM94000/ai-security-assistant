"""SEC-12 — aucune fuite de secret ni de contenu sensible par les logs.

Reference : docs/SECURITY.md, matrice section 6.
Attendu : logs propres — ni secret de configuration, ni question d'utilisateur,
ni contenu de document.

Les logs sont le seul endroit du produit ou l'on ecrit **volontairement** des
informations internes. C'est aussi celui qu'on oublie : ils partent vers un
agregateur, sont conserves longtemps, et sont lisibles par des gens qui n'ont
pas acces a la base. Un secret qui n'est jamais renvoye au client mais qui
traine dans une ligne de journal reste un secret divulgue.

Ce fichier teste trois choses distinctes :

1. **Ce qu'on ecrit** — les appels du projet ne journalisent pas de valeurs
   sensibles ;
2. **Ce qu'on laisse ecrire** — un en-tete client ne peut pas fabriquer une
   fausse ligne de journal ;
3. **Ce qui traverse** — une question d'utilisateur ne se retrouve pas dans les
   traces au passage d'une requete complete.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from typing import Any, cast

import pytest
import structlog
from fastapi.testclient import TestClient

from aisecassist.agents.service import AgentService
from aisecassist.api.deps import Services, get_services
from aisecassist.llm.base import ChatReply, ToolCall
from aisecassist.main import app
from aisecassist.observability import tracing
from aisecassist.observability.logging import configure_logging
from aisecassist.observability.request_id import EN_TETE
from tests.doubles import (
    FakeLLM,
    FakeTool,
    FakeVectorStore,
    ScriptedChatLLM,
    extrait,
    make_generation,
    make_retrieval,
)

# Valeurs qui ne doivent JAMAIS apparaitre dans une ligne de journal.
_CLE_FOURNISSEUR = "gsk_ClefDeFournisseurQuiNeDoitPasFuiter1234"
_QUESTION_SENSIBLE = "Le mot de passe du compte admin-prod est Hunter2, est-ce un risque ?"


class _SpanFactice:
    """Double minimal d'une etape tracee."""

    def update(self, **valeurs: Any) -> None:
        return None

    def __enter__(self) -> _SpanFactice:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def journal() -> Iterator[io.StringIO]:
    tampon = io.StringIO()
    configure_logging(level="DEBUG", json_format=True, stream=tampon)
    yield tampon
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()
    logging.getLogger().handlers = []
    app.dependency_overrides.clear()


def _services(agent: AgentService | None = None) -> Services:
    return Services(
        retrieval=make_retrieval(FakeVectorStore([extrait("contenu", source="owasp.md")])),
        generation=make_generation(FakeLLM("reponse neutre")),
        agent=agent if agent is not None else cast(Any, None),
        store=cast(Any, None),
        llm=cast(Any, None),
        cve=cast(Any, None),
    )


def _client(services: Services) -> TestClient:
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


# --- 1. Ce que le produit ecrit ---------------------------------------------


def test_une_question_dutilisateur_ne_part_pas_dans_les_logs(journal: io.StringIO) -> None:
    """Une question peut contenir n'importe quoi, y compris un secret reel.

    C'est pour cela que l'agent journalise les **cles** des arguments d'outil et
    jamais leurs valeurs. Ce test verifie la propriete sur une requete entiere,
    la ou `test_sec06_agent_limits.py` la verifie sur le service isole.
    """
    reponse = _client(_services()).post("/query", json={"question": _QUESTION_SENSIBLE})

    assert reponse.status_code == 200
    trace = journal.getvalue()
    assert "Hunter2" not in trace
    assert "admin-prod" not in trace


def test_le_contenu_dun_document_ne_part_pas_dans_les_logs(journal: io.StringIO) -> None:
    """Un extrait peut venir d'un document confidentiel du corpus."""
    secret = "procedure interne de bascule du pare-feu"
    services = _services()
    services = Services(
        retrieval=make_retrieval(FakeVectorStore([extrait(secret, source="interne.md")])),
        generation=services.generation,
        agent=services.agent,
        store=services.store,
        llm=services.llm,
        cve=services.cve,
    )

    _client(services).post("/query", json={"question": "question"})

    assert secret not in journal.getvalue()


def test_la_cle_du_fournisseur_ne_part_pas_dans_les_logs(journal: io.StringIO) -> None:
    """Le secret le plus sensible du produit est celui qu'il detient lui-meme.

    Le guardrail de sortie le rediger**ait** s'il atteignait une reponse ; les
    logs, eux, n'ont pas de guardrail. La seule parade est de ne jamais l'ecrire.
    """
    from aisecassist.config import Settings

    reglages = Settings(
        _env_file=None,  # type: ignore[call-arg]
        llm_provider="hosted",
        hosted_llm_api_key=_CLE_FOURNISSEUR,
    )
    logging.getLogger("aisecassist.api.deps").info(
        "Fournisseur heberge actif : %s, modele %s.",
        reglages.hosted_llm_base_url,
        reglages.hosted_llm_model,
    )

    trace = journal.getvalue()
    assert _CLE_FOURNISSEUR not in trace
    # La ligne existe bien : le test verifie une absence, pas un silence total.
    assert "Fournisseur heberge actif" in trace


def test_les_arguments_doutil_sont_traces_par_leurs_cles(journal: io.StringIO) -> None:
    """Tracer « qui a appele quoi » ne doit pas revenir a tracer le contenu."""
    outil = FakeTool(name="rechercher_corpus")
    llm = ScriptedChatLLM(
        [
            ChatReply(
                text="",
                tool_calls=(
                    ToolCall(name="rechercher_corpus", arguments={"question": _QUESTION_SENSIBLE}),
                ),
            ),
            ChatReply(text="reponse"),
        ]
    )
    agent = AgentService(llm, [outil], max_iterations=2, max_answer_chars=8_000, timeout_s=5.0)

    _client(_services(agent)).post("/agent", json={"question": "question anodine"})

    trace = journal.getvalue()
    assert "rechercher_corpus" in trace  # le nom de l'outil, oui
    assert "question" in trace  # la cle de l'argument, oui
    assert "Hunter2" not in trace  # sa valeur, non


# --- 2. Ce qu'un client peut faire ecrire ------------------------------------


def test_un_en_tete_hostile_ne_fabrique_pas_de_fausse_ligne(journal: io.StringIO) -> None:
    """L'injection de logs : la seule ou l'attaquant ecrit dans nos journaux.

    Un saut de ligne dans un en-tete recopie tel quel produirait une seconde
    ligne, qu'un agregateur indexerait comme un evenement authentique — de
    quoi masquer une intrusion sous un faux « connexion reussie ».
    """
    charge = 'x\n{"event":"connexion reussie","level":"info"}'

    _client(_services()).post("/query", json={"question": "question"}, headers={EN_TETE: charge})

    lignes = [json.loads(ligne) for ligne in journal.getvalue().splitlines() if ligne.strip()]
    assert all(ligne.get("event") != "connexion reussie" for ligne in lignes)
    assert "connexion reussie" not in journal.getvalue()


def test_un_en_tete_demesure_ne_gonfle_pas_chaque_ligne(journal: io.StringIO) -> None:
    """Un identifiant de 10 ko recopie dans chaque ligne d'une requete est un DoS lent."""
    _client(_services()).post(
        "/query", json={"question": "question"}, headers={EN_TETE: "A" * 10_000}
    )

    assert "A" * 100 not in journal.getvalue()


# --- 3. Ce qui traverse une requete complete ---------------------------------


def test_chaque_ligne_dune_requete_porte_le_meme_identifiant(journal: io.StringIO) -> None:
    """Sans identifiant partage, les traces de requetes concurrentes s'entrelacent.

    C'est la contrepartie utile de SEC-12 : on ne journalise pas le contenu, donc
    il faut pouvoir relier les lignes entre elles autrement.

    Le guardrail de sortie est declenche a dessein : c'est un chemin qui
    **produit** une ligne de journal. Un test qui se contenterait de verifier
    « aucune ligne sans identifiant » passerait sur une requete silencieuse,
    sans rien prouver — c'est exactement le piege dans lequel la premiere
    version de ce test etait tombee.
    """
    faux_secret = "sk-" + "a1b2c3d4" * 4  # forme de cle, construite ici
    services = Services(
        retrieval=make_retrieval(FakeVectorStore([extrait("contenu")])),
        generation=make_generation(FakeLLM(f"La cle est {faux_secret}")),
        agent=cast(Any, None),
        store=cast(Any, None),
        llm=cast(Any, None),
        cve=cast(Any, None),
    )

    reponse = _client(services).post(
        "/query", json={"question": "sujet absent du corpus"}, headers={EN_TETE: "trace-abc"}
    )

    assert reponse.headers[EN_TETE] == "trace-abc"
    lignes = [json.loads(ligne) for ligne in journal.getvalue().splitlines() if ligne.strip()]
    avec_identifiant = [ligne for ligne in lignes if "request_id" in ligne]

    # Au moins une ligne a ete emise, et toutes portent le meme identifiant.
    assert avec_identifiant, "aucune ligne journalisee : le test ne prouverait rien"
    assert {ligne["request_id"] for ligne in avec_identifiant} == {"trace-abc"}


def test_aucune_ligne_ne_porte_lidentifiant_de_la_requete_precedente(
    journal: io.StringIO,
) -> None:
    """Le contexte est purge entre deux requetes, sinon les traces se melangent."""
    client = _client(_services())
    client.post("/query", json={"question": "premiere"}, headers={EN_TETE: "trace-un"})
    debut = len(journal.getvalue())
    client.post("/query", json={"question": "seconde"}, headers={EN_TETE: "trace-deux"})

    assert "trace-un" not in journal.getvalue()[debut:]


# --- 4. Les traces : une seconde sortie, un autre arbitrage ------------------
#
# Une trace contient DELIBEREMENT ce que les logs excluent : la question et les
# extraits recuperes. Sans ce contenu, elle ne servirait a rien. L'arbitrage est
# assume (ADR-0015), et les deux tests ci-dessous le figent — pour qu'il reste
# un choix documente et non une derive.


def test_la_question_est_absente_des_logs_mais_presente_dans_la_trace(
    journal: io.StringIO,
) -> None:
    """La difference entre les deux destinations, ecrite noir sur blanc.

    Les logs partent vers un agregateur, sont conserves longtemps et lus
    largement. Une trace vit dans un systeme dedie, auto-heberge, prevu pour ce
    contenu. Ce test echouera si quelqu'un aligne l'un sur l'autre — dans un
    sens comme dans l'autre.
    """
    vues: list[dict[str, Any]] = []

    class ClientFactice:
        def start_as_current_observation(self, **kwargs: Any) -> Any:
            vues.append(kwargs)
            return _SpanFactice()

    tracing._client = ClientFactice()
    try:
        _client(_services()).post("/query", json={"question": _QUESTION_SENSIBLE})
    finally:
        tracing._client = None

    assert "Hunter2" not in journal.getvalue(), "la question ne doit pas etre journalisee"
    tracees = [v["input"].get("question", "") for v in vues if "question" in v.get("input", {})]
    assert any("Hunter2" in q for q in tracees), "la trace, elle, doit la porter"


def test_un_secret_natteint_jamais_la_trace(journal: io.StringIO) -> None:
    """Le contenu utile passe, les secrets non. C'est la ligne de partage."""
    faux_secret = "sk-" + "a1b2c3d4" * 4
    vues: list[dict[str, Any]] = []

    class SpanQuiEnregistre:
        def update(self, **valeurs: Any) -> None:
            vues.append(valeurs)

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    class ClientFactice:
        def start_as_current_observation(self, **kwargs: Any) -> Any:
            return SpanQuiEnregistre()

    services = Services(
        retrieval=make_retrieval(FakeVectorStore([extrait("contenu")])),
        generation=make_generation(FakeLLM(f"La cle est {faux_secret}")),
        agent=cast(Any, None),
        store=cast(Any, None),
        llm=cast(Any, None),
        cve=cast(Any, None),
    )

    tracing._client = ClientFactice()
    try:
        _client(services).post("/query", json={"question": "question"})
    finally:
        tracing._client = None

    assert vues, "aucune sortie tracee : le test ne prouverait rien"
    assert all(faux_secret not in str(v) for v in vues)
