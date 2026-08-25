"""SEC-10 — consommation non bornee, volet longueur de reponse.

Reference : docs/SECURITY.md, matrice section 6.

**Portee exacte.** Ce fichier couvre le plafond de longueur applique a la
generation. Il ne couvre ni la limitation de debit, ni un plafond de jetons
cote fournisseur, ni le plafond d'iterations d'agent — qui relevent de M2 pour
le premier et de M3/M4 pour les autres.

Le plafond est applique **cote serveur**. C'est le seul endroit ou il protege :
en streaming, une generation qui part en boucle emettrait des fragments
indefiniment, et rien du cote client ne l'arreterait.
"""

from __future__ import annotations

import pytest

from aisecassist.generation.service import MARQUEUR_TRONCATURE
from tests.doubles import FakeLLM, StreamingLLM, extrait, make_generation

pytestmark = pytest.mark.anyio


async def test_le_streaming_sarrete_au_plafond() -> None:
    """Une generation qui part en boucle doit etre coupee par le serveur."""
    boucle = StreamingLLM(["x" * 100] * 50)
    service = make_generation(boucle, max_answer_chars=120)

    fragments = [f async for f in service.stream_answer("question", [extrait("contenu")])]
    texte = "".join(fragments)

    assert texte.endswith(MARQUEUR_TRONCATURE)
    assert len(texte.removesuffix(MARQUEUR_TRONCATURE)) == 120


async def test_le_plafond_est_cumulatif_et_non_par_fragment() -> None:
    """Un plafond applique fragment par fragment ne plafonnerait rien du tout."""
    service = make_generation(StreamingLLM(["12345", "67890", "abcde"]), max_answer_chars=8)

    texte = "".join([f async for f in service.stream_answer("q", [extrait("c")])])

    assert texte.removesuffix(MARQUEUR_TRONCATURE) == "12345678"


async def test_une_reponse_exactement_a_la_limite_nest_pas_annoncee_tronquee() -> None:
    """Annoncer une troncature qui n'a pas eu lieu serait un mensonge a l'utilisateur."""
    service = make_generation(StreamingLLM(["12345"]), max_answer_chars=5)

    texte = "".join([f async for f in service.stream_answer("q", [extrait("c")])])

    assert texte == "12345"
    assert MARQUEUR_TRONCATURE not in texte


async def test_une_reponse_sous_le_plafond_est_intacte() -> None:
    service = make_generation(StreamingLLM(["court"]), max_answer_chars=1_000)

    texte = "".join([f async for f in service.stream_answer("q", [extrait("c")])])

    assert texte == "court"


async def test_le_plafond_sapplique_aussi_hors_streaming() -> None:
    """Le chemin non streame ne doit pas etre une porte de sortie du plafond."""
    service = make_generation(FakeLLM("y" * 5_000), max_answer_chars=100)

    resultat = await service.answer("question", [extrait("contenu")])

    assert resultat.answer.endswith(MARQUEUR_TRONCATURE)
    assert len(resultat.answer.removesuffix(MARQUEUR_TRONCATURE)) == 100
