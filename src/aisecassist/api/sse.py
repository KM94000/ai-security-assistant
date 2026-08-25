"""Encodage des evenements Server-Sent Events.

Module minuscule et isole a dessein : le format SSE a une regle facile a
enfreindre — un saut de ligne brut dans le champ `data` termine l'evenement.
Emettre du texte de modele directement casserait donc le protocole des la
premiere reponse contenant un retour a la ligne, c'est-a-dire tout de suite.

Encoder la charge en JSON resout le probleme par construction : les sauts de
ligne y deviennent des sequences d'echappement, et la charge tient sur une
seule ligne quelle que soit son contenu.
"""

from __future__ import annotations

import json
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    """Encode un evenement SSE nomme, dont la charge utile est du JSON."""
    charge = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {charge}\n\n"
