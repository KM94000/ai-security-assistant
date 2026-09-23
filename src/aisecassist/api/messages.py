"""Messages d'erreur renvoyes au client.

Volontairement generiques, et regroupes ici pour que les deux chemins de sortie
— reponse JSON classique et flux SSE — disent exactement la meme chose. Le
detail technique part dans les logs, jamais dans la reponse : une trace exposee
renseigne un attaquant sur la pile, les chemins et les versions
(SECURITY.md, SEC-11).
"""

MESSAGE_INDISPONIBLE = "Le service est temporairement indisponible. Reessayez plus tard."
MESSAGE_INATTENDU = "Une erreur interne est survenue."
MESSAGE_AGENT_TROP_LONG = (
    "L'agent n'a pas abouti dans le temps imparti. Une question plus precise "
    "demande moins d'etapes."
)
"""Budget de temps epuise (504).

Le seul message d'erreur du produit qui donne une piste d'action a
l'utilisateur, parce que c'est le seul cas ou il en a une : ni une panne de
dependance ni une erreur interne ne se resolvent en reformulant. La piste ne
revele rien du fonctionnement interne — qu'un agent procede par etapes est
deja documente dans OpenAPI.
"""
