# MITRE ATLAS — tactiques adverses contre les systemes d'IA

Synthese redigee pour ce projet. Referentiel : MITRE ATLAS (Adversarial Threat
Landscape for Artificial-Intelligence Systems).

## Ce qu'apporte ATLAS

ATLAS transpose la logique de MITRE ATT&CK aux systemes d'apprentissage automatique.
La difference avec un catalogue de vulnerabilites est importante : ATLAS decrit des
**enchainements** d'actions adverses, pas des defauts isoles. Une attaque reelle
combine plusieurs techniques a travers plusieurs tactiques.

## Tactiques principales

**Reconnaissance.** L'attaquant identifie le modele utilise, ses versions, ses jeux de
donnees publics, la documentation de l'API. Les messages d'erreur trop bavards et les
pages de statut y contribuent plus qu'on ne le pense.

**Acces au modele.** Acces via API, via une application qui l'embarque, ou par
recuperation des poids. Le niveau d'acces determine les techniques disponibles : un
acces boite noire limite a l'interrogation, un acces aux poids ouvre bien davantage.

**Preparation de l'attaque.** L'adversaire construit un substitut du modele cible, ou
elabore des exemples adverses hors ligne avant de les employer. Cette phase se deroule
entierement chez l'attaquant et reste donc invisible cote defense.

**Execution.** Injection de prompt, exemples adverses, detournement d'outils. Dans les
systemes agentiques, l'execution passe de plus en plus par les outils du modele plutot
que par le modele lui-meme.

**Persistance.** Empoisonner un corpus de recuperation offre une persistance a faible
cout : la charge reste en base et se declenche a chaque recuperation, sans nouvelle
intrusion.

**Exfiltration.** Extraction de donnees d'entrainement par interrogation repetee, vol de
modele par distillation, fuite via les sorties.

**Impact.** Degradation de la qualite, erosion de la confiance, cout d'inference, ou
consequences metier des decisions erronees.

## Techniques particulierement pertinentes pour un RAG

**Empoisonnement du corpus.** Introduire un document concu pour etre recupere
frequemment et pour influencer les reponses. Peu couteux, difficile a detecter sans
suivi de provenance.

**Injection indirecte.** Placer une instruction dans un contenu que le systeme ingere.
La separation temporelle entre l'introduction et le declenchement complique
l'attribution.

**Extraction du prompt systeme.** Reconstruire les consignes par interrogation
methodique, souvent en plusieurs tours.

## Utilite defensive

ATLAS sert surtout a batir un modele de menace : partir des tactiques pour identifier
les etapes ou l'on peut interrompre l'enchainement. Bloquer une seule etape d'une chaine
suffit souvent a en annuler l'effet, ce qui oriente l'effort de defense vers les points
de passage obliges plutot que vers les techniques individuelles.
