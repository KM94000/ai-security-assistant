# NIST AI Risk Management Framework

Synthese redigee pour ce projet. Referentiel : NIST AI RMF 1.0.

## Positionnement

Le cadre du NIST ne decrit pas des attaques mais une **methode de gestion du risque**.
Il est volontairement independant des technologies et des secteurs. Son apport est de
donner un vocabulaire commun entre les equipes techniques, juridiques et metier — ce
qui manque cruellement quand il faut arbitrer un risque lie a l'IA.

## Les quatre fonctions

**GOVERN.** Fonction transverse, presente dans les trois autres. Elle couvre les
politiques, les roles, les responsabilites et la culture. C'est la fonction la plus
souvent negligee et celle dont l'absence se paie le plus cher : sans responsable
identifie, les risques mesures ne sont jamais traites.

**MAP.** Etablir le contexte et identifier les risques. Quel est l'usage prevu ? Qui
sont les utilisateurs ? Quelles sont les hypotheses implicites ? Quels usages detournes
sont plausibles ? Cette phase repose sur des questions plus que sur des outils.

**MEASURE.** Analyser et suivre les risques identifies au moyen de metriques. Le cadre
insiste sur un point : ce qui n'est pas mesure ne peut pas etre gere, mais une mesure
mal choisie donne une fausse assurance. Un score de qualite eleve sur un jeu de test non
representatif ne dit rien du comportement en production.

**MANAGE.** Hierarchiser les risques et y repondre : reduire, transferer, accepter ou
eviter. Les ressources etant limitees, l'arbitrage explicite vaut mieux qu'une
couverture uniforme et superficielle.

## Caracteristiques d'une IA digne de confiance

Le cadre enumere des proprietes attendues : validite et fiabilite, securite au sens
safety, securite au sens security et resilience, redevabilite et transparence,
explicabilite et interpretabilite, respect de la vie privee, et equite avec maitrise des
biais.

Ces proprietes entrent regulierement en tension. Renforcer la confidentialite peut
degrader l'explicabilite ; accroitre la robustesse peut reduire la performance moyenne.
Le cadre ne tranche pas ces arbitrages : il demande qu'ils soient explicites et
documentes.

## Application a un assistant de securite fonde sur un RAG

**MAP** : l'usage prevu est la consultation de referentiels de securite. Un usage
detourne plausible est la demande d'aide a l'exploitation d'une faille. Les utilisateurs
sont supposes competents, ce qui reduit le risque de mauvaise interpretation mais
augmente l'impact d'une reponse fausse.

**MEASURE** : la fidelite des reponses au contexte recupere est plus pertinente que la
satisfaction declaree. Un utilisateur satisfait d'une remediation inventee est le pire
resultat possible.

**MANAGE** : le risque de desinformation se traite par le sourcing systematique et par
un refus explicite quand le corpus ne contient pas la reponse, plutot que par une
tentative d'eliminer l'hallucination — objectif hors d'atteinte.
