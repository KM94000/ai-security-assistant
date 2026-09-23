"""Tests de l'agent (ticket 19).

Aucun modele ne tourne : le fournisseur est un double qui rejoue un script. Ce
qui est verifie ici, c'est la boucle et ce qu'elle transmet — pas la qualite des
decisions du modele, qui n'est pas testable de facon deterministe.
"""

from __future__ import annotations

import pytest

from aisecassist.agents.service import (
    MESSAGE_SANS_REPONSE,
    AgentError,
    AgentService,
)
from aisecassist.llm.base import ChatReply, ToolCall
from tests.doubles import FakeTool, ScriptedChatLLM

pytestmark = pytest.mark.anyio


def _agent(
    llm: ScriptedChatLLM,
    *outils: FakeTool,
    max_iterations: int = 3,
    max_answer_chars: int = 8_000,
) -> AgentService:
    return AgentService(
        llm,
        outils or (FakeTool(),),
        max_iterations=max_iterations,
        max_answer_chars=max_answer_chars,
    )


def _appel(question: str = "injection de prompt", nom: str = "rechercher_corpus") -> ChatReply:
    return ChatReply(text="", tool_calls=(ToolCall(name=nom, arguments={"question": question}),))


async def test_sans_appel_doutil_la_reponse_du_modele_est_rendue() -> None:
    """Toutes les questions ne meritent pas une recherche : l'agent peut repondre seul."""
    llm = ScriptedChatLLM([ChatReply(text="Bonjour, que puis-je pour vous ?")])
    service = _agent(llm)

    resultat = await service.answer("bonjour")

    assert resultat.answer == "Bonjour, que puis-je pour vous ?"
    assert resultat.iterations == 0
    assert resultat.sources == ()


async def test_lagent_appelle_loutil_puis_repond_avec_ses_sources() -> None:
    outil = FakeTool(observation="Un extrait.", sources=("owasp-llm-top10.md",))
    llm = ScriptedChatLLM([_appel(), ChatReply(text="Voici la reponse.")])
    service = _agent(llm, outil)

    resultat = await service.answer("Comment se defendre contre une injection ?")

    assert resultat.answer == "Voici la reponse."
    assert resultat.sources == ("owasp-llm-top10.md",)
    assert resultat.iterations == 1
    assert outil.arguments_recus == [{"question": "injection de prompt"}]


async def test_lobservation_de_loutil_est_transmise_au_modele() -> None:
    """Sans cela, l'agent appellerait l'outil sans jamais lire son resultat."""
    llm = ScriptedChatLLM([_appel(), ChatReply(text="fini")])
    service = _agent(llm, FakeTool(observation="LLM01 parle de delimiteurs."))

    await service.answer("question")

    second_tour = llm.conversations[1]
    messages_outil = [m for m in second_tour if m.role == "tool"]
    assert [m.content for m in messages_outil] == ["LLM01 parle de delimiteurs."]
    assert messages_outil[0].tool_name == "rechercher_corpus"


async def test_la_demande_doutil_reste_dans_lhistorique() -> None:
    """Le resultat d'outil doit arriver precede de la demande qui l'a provoque.

    Sans elle, le modele voit une observation surgie de nulle part, et peut
    redemander la meme chose indefiniment.
    """
    llm = ScriptedChatLLM([_appel(), ChatReply(text="fini")])
    service = _agent(llm)

    await service.answer("question")

    assistants = [m for m in llm.conversations[1] if m.role == "assistant"]
    assert assistants[0].tool_calls[0].name == "rechercher_corpus"


async def test_les_outils_sont_presentes_au_modele() -> None:
    llm = ScriptedChatLLM([ChatReply(text="ok")])
    service = _agent(llm, FakeTool(name="rechercher_corpus"))

    await service.answer("question")

    assert [spec.name for spec in llm.outils_presentes] == ["rechercher_corpus"]


async def test_plusieurs_tours_sont_possibles_sous_le_plafond() -> None:
    """Un agent utile peut chercher, lire, puis chercher a nouveau."""
    llm = ScriptedChatLLM([_appel("premiere"), _appel("seconde"), ChatReply(text="synthese")])
    outil = FakeTool()
    service = _agent(llm, outil, max_iterations=3)

    resultat = await service.answer("question complexe")

    assert resultat.answer == "synthese"
    assert resultat.iterations == 2
    assert [a["question"] for a in outil.arguments_recus] == ["premiere", "seconde"]


async def test_les_sources_ne_sont_pas_dupliquees_entre_les_tours() -> None:
    llm = ScriptedChatLLM([_appel("a"), _appel("b"), ChatReply(text="fini")])
    service = _agent(llm, FakeTool(sources=("owasp.md", "atlas.md")))

    resultat = await service.answer("question")

    assert resultat.sources == ("owasp.md", "atlas.md")


async def test_une_reponse_vide_du_modele_donne_un_message_explicite() -> None:
    """Une chaine vide renvoyee au client ressemblerait a une panne silencieuse."""
    llm = ScriptedChatLLM([ChatReply(text="   ")])
    service = _agent(llm)

    assert (await service.answer("question")).answer == MESSAGE_SANS_REPONSE


@pytest.mark.parametrize("question", ["", "   ", "\n\t "])
async def test_une_question_vide_est_refusee_sans_appeler_le_modele(question: str) -> None:
    llm = ScriptedChatLLM([ChatReply(text="ne doit pas etre appele")])
    service = _agent(llm)

    with pytest.raises(AgentError):
        await service.answer(question)

    assert llm.appels == 0


async def test_un_agent_sans_outil_est_refuse_a_la_construction() -> None:
    """Un agent sans outil est un modele qui repond de memoire, donc sans source."""
    with pytest.raises(AgentError):
        AgentService(
            ScriptedChatLLM([ChatReply(text="ok")]),
            [],
            max_iterations=3,
            max_answer_chars=8_000,
        )


# --- Plusieurs outils (ticket 20) ---------------------------------------------


async def test_avec_deux_outils_seul_celui_demande_est_execute() -> None:
    """Le critere d'acceptation du ticket 20, cote aiguillage.

    Que le modele choisisse *bien* n'est pas testable ici — c'est l'objet du
    test contre le vrai modele. Ce qui l'est, et qui doit l'etre : quand il
    designe un outil, c'est celui-la qui s'execute, et lui seul.
    """
    corpus = FakeTool(name="rechercher_corpus", observation="extrait", sources=("owasp.md",))
    cve = FakeTool(name="consulter_cve", observation="CVE-2021-44228", sources=("nvd",))
    llm = ScriptedChatLLM(
        [
            ChatReply(
                text="",
                tool_calls=(
                    ToolCall(name="consulter_cve", arguments={"identifiant": "CVE-2021-44228"}),
                ),
            ),
            ChatReply(text="Log4Shell permet l'execution de code a distance."),
        ]
    )

    resultat = await _agent(llm, corpus, cve).answer("Que fait CVE-2021-44228 ?")

    assert cve.arguments_recus == [{"identifiant": "CVE-2021-44228"}]
    assert corpus.arguments_recus == []
    assert resultat.sources == ("nvd",)


async def test_les_deux_outils_sont_presentes_au_modele() -> None:
    """Un outil absent de la declaration est un outil que le modele n'appellera pas."""
    corpus = FakeTool(name="rechercher_corpus")
    cve = FakeTool(name="consulter_cve")
    llm = ScriptedChatLLM([ChatReply(text="reponse directe")])

    await _agent(llm, corpus, cve).answer("question")

    assert sorted(spec.name for spec in llm.outils_presentes) == [
        "consulter_cve",
        "rechercher_corpus",
    ]


async def test_les_sources_de_plusieurs_outils_sont_cumulees_sans_doublon() -> None:
    """Une reponse peut s'appuyer sur le corpus et sur le NIST a la fois."""
    corpus = FakeTool(name="rechercher_corpus", sources=("owasp.md", "nist.md"))
    cve = FakeTool(name="consulter_cve", sources=("nist.md", "nvd/CVE-2021-44228"))
    rafale = ChatReply(
        text="",
        tool_calls=(
            ToolCall(name="rechercher_corpus", arguments={"question": "log4j"}),
            ToolCall(name="consulter_cve", arguments={"identifiant": "CVE-2021-44228"}),
        ),
    )
    llm = ScriptedChatLLM([rafale, ChatReply(text="synthese")])

    resultat = await _agent(llm, corpus, cve).answer("question")

    assert resultat.sources == ("owasp.md", "nist.md", "nvd/CVE-2021-44228")
