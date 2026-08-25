"""Tests de l'encodage Server-Sent Events."""

from __future__ import annotations

import json

from aisecassist.api.sse import sse_event


def test_encode_un_evenement_nomme() -> None:
    assert sse_event("token", {"text": "bonjour"}) == 'event: token\ndata: {"text": "bonjour"}\n\n'


def test_un_saut_de_ligne_dans_la_charge_ne_casse_pas_le_cadrage() -> None:
    """La regle du format SSE la plus facile a enfreindre.

    Un saut de ligne brut dans le champ `data` termine l'evenement. Emettre du
    texte de modele directement casserait donc le protocole des la premiere
    reponse contenant un retour a la ligne — c'est-a-dire tout de suite.
    L'encodage JSON le transforme en sequence d'echappement.
    """
    encode = sse_event("token", {"text": "premiere ligne\nseconde ligne"})

    corps = encode.removeprefix("event: token\ndata: ").removesuffix("\n\n")
    assert "\n" not in corps
    assert json.loads(corps)["text"] == "premiere ligne\nseconde ligne"


def test_les_accents_ne_sont_pas_echappes() -> None:
    """Sans `ensure_ascii=False`, une reponse en francais devient illisible dans le flux."""
    encode = sse_event("token", {"text": "sécurité"})

    assert "sécurité" in encode


def test_un_evenement_se_termine_par_une_ligne_vide() -> None:
    """C'est ce double saut de ligne qui signale la fin de l'evenement au client."""
    assert sse_event("done", {}).endswith("\n\n")
