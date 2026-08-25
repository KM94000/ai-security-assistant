"""Messages d'erreur renvoyes au client.

Volontairement generiques, et regroupes ici pour que les deux chemins de sortie
— reponse JSON classique et flux SSE — disent exactement la meme chose. Le
detail technique part dans les logs, jamais dans la reponse : une trace exposee
renseigne un attaquant sur la pile, les chemins et les versions
(SECURITY.md, SEC-11).
"""

MESSAGE_INDISPONIBLE = "Le service est temporairement indisponible. Reessayez plus tard."
MESSAGE_INATTENDU = "Une erreur interne est survenue."
