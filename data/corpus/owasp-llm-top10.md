# OWASP Top 10 pour les applications a base de LLM (2025)

Synthese redigee pour ce projet. Referentiel : OWASP Top 10 for LLM Applications.

## LLM01 — Injection de prompt

Un attaquant formule une entree qui detourne le comportement du modele. L'injection
est **directe** quand elle vient de l'utilisateur, **indirecte** quand elle transite
par un contenu que le systeme ingere : page web, document, resultat d'outil.

L'injection indirecte est la plus dangereuse dans une architecture RAG, parce que la
charge n'agit pas au moment ou elle entre dans le systeme mais au moment ou elle est
recuperee, souvent bien plus tard et pour un autre utilisateur.

Remediation : separer structurellement les instructions du contenu recupere avec des
delimiteurs que le contenu ne peut pas forger ; assainir les documents a l'ingestion ;
ne jamais accorder a un texte recupere l'autorite d'une instruction systeme. Un prompt
systeme qui demande poliment d'ignorer les instructions du contexte n'est pas un
controle de securite : il est contournable.

## LLM02 — Divulgation d'informations sensibles

Le modele restitue des secrets, des donnees personnelles ou du contenu d'autres
utilisateurs. La fuite peut venir du prompt systeme, du corpus, ou de la memoire de
conversation.

Remediation : filtrage des sorties avant renvoi, moindre privilege sur les donnees
accessibles au retrieval, cloisonnement par utilisateur.

## LLM03 — Chaine d'approvisionnement

Les dependances, les modeles pre-entraines et les images de conteneurs sont autant de
points d'entree. Un modele telecharge depuis un depot public peut avoir ete altere.

Remediation : epingler les versions, verifier les sommes de controle, scanner les
dependances en integration continue, tracer la provenance des modeles.

## LLM04 — Empoisonnement des donnees et du modele

Un attaquant introduit du contenu malveillant dans les donnees d'entrainement ou dans
le corpus de recuperation. Dans un RAG, empoisonner le corpus est bien moins couteux
que d'empoisonner un entrainement.

Remediation : controler ce qui entre dans le corpus, conserver la provenance de chaque
fragment, assainir le texte ingere, pouvoir retirer une source et re-indexer.

## LLM05 — Traitement incorrect des sorties

La sortie du modele est traitee comme fiable par le code en aval : elle est affichee
sans echappement, executee, ou passee a un outil. C'est le pendant LLM des injections
classiques — la sortie du modele franchit une frontiere de confiance.

Remediation : traiter toute sortie de modele comme une entree utilisateur ; echapper
avant affichage, valider avant execution.

## LLM06 — Autonomie excessive

L'agent dispose de plus de pouvoir que necessaire : trop d'outils, des permissions trop
larges, pas de plafond d'iterations. Une injection reussie devient alors une execution
de code ou une exfiltration.

Remediation : liste blanche d'outils par requete, validation des arguments en dur cote
code, plafond d'iterations, journalisation de chaque appel d'outil.

## LLM07 — Fuite du prompt systeme

Le prompt systeme est extrait par l'utilisateur. Le probleme n'est pas tant la
divulgation du texte que ce qu'il revele : logique metier, noms d'outils, parfois des
identifiants places la par erreur.

Remediation : ne jamais placer de secret dans un prompt ; considerer le prompt systeme
comme public par construction.

## LLM08 — Faiblesses des vecteurs et des embeddings

Specifique au RAG. Un fragment peut etre concu pour dominer la recherche vectorielle et
s'inserer dans le contexte de nombreuses requetes sans rapport. Le cloisonnement entre
utilisateurs peut aussi etre absent de la base vectorielle.

Remediation : provenance verifiable sur chaque fragment, cloisonnement par utilisateur
ou par espace, surveillance des fragments anormalement souvent recuperes.

## LLM09 — Desinformation

Le modele produit des affirmations fausses mais plausibles. Dans un outil de securite,
c'est un risque metier direct : une remediation inventee peut ouvrir une faille.

Remediation : citer systematiquement les sources, mesurer la fidelite des reponses au
contexte recupere, prevoir un refus explicite quand le corpus ne contient pas la reponse.

## LLM10 — Consommation non bornee

Requetes tres longues, boucles d'agent, appels en rafale. L'impact est un cout financier
autant qu'un deni de service.

Remediation : limitation de debit, plafond de jetons par requete, plafond d'iterations
d'agent, surveillance des couts comme signal d'abus.
