# Durcir un RAG et ses agents — pratiques

Synthese redigee pour ce projet. Elle applique aux architectures RAG et agentiques
les principes de l'OWASP Top 10 pour LLM, de MITRE ATLAS et du NIST AI RMF, traites
chacun dans leur propre document. Les recommandations ci-dessous sont des pratiques
d'ingenierie, non un referentiel normatif.

## Le principe directeur

**On ne delegue jamais la securite au modele.** Un prompt systeme qui demande
poliment d'ignorer les instructions trouvees dans le contexte est une aide, pas un
controle : il est contournable, et sa fiabilite varie d'un modele a l'autre et d'une
generation a l'autre. Les barrieres doivent etre des conditions dans le code, dont
on peut prouver qu'elles s'appliquent toujours.

Corollaire utile en revue : pour chaque protection annoncee, demander *ou est la
ligne de code qui la rend impossible a contourner*. Si la reponse est « le prompt le
demande », ce n'est pas une protection.

## Structurer le prompt pour resister a l'injection indirecte

Le moment dangereux d'un RAG est la rencontre entre les **donnees recuperees** et
les **instructions**. Trois mesures, par ordre d'efficacite :

**Delimiteurs imprevisibles.** Encadrer le contexte et la question par un marqueur
contenant une valeur aleatoire tiree a chaque requete. Un contenu empoisonne ne peut
pas fermer une cloture dont il ignore le marqueur, ni en forger une credible. Un
delimiteur fixe, lui, finit par etre connu.

**Assainissement du contenu recupere.** Retirer des extraits tout ce qui a la
*forme* d'un delimiteur, ainsi que les caracteres invisibles, les marques
bidirectionnelles et les caracteres de controle — autant de moyens de dissimuler une
charge a la lecture humaine sans la cacher au modele.

**Separation par roles.** Rendre les resultats d'outils dans un message de role
distinct plutot que concatenes au texte de l'utilisateur. La separation est alors
structurelle et non typographique.

Ce que ces mesures garantissent : un extrait ne peut pas **se faire passer** pour une
instruction. Ce qu'elles ne garantissent pas : que le modele n'**obeisse** pas a un
texte qu'il lit comme du contenu. C'est une limite a enoncer, pas a masquer.

## Concevoir un outil d'agent

Chaque outil est une surface d'attaque supplementaire. Les regles qui tiennent :

**Le modele choisit quoi, jamais ou.** L'hote et le chemin d'un appel sortant
viennent de la configuration. Le modele ne fournit qu'un parametre, valide contre une
forme stricte, transmis comme parametre de requete et jamais concatene dans une URL.
Sans cela, l'outil devient une primitive de falsification de requete cote serveur.

**Valider les arguments dans l'outil, en dur.** Un schema strict qui refuse les
champs inattendus, borne les longueurs et impose le format attendu. Ancrer les
expressions regulieres aux deux extremites : sans ancrage, une valeur valide suivie
d'une charge passe la validation.

**Lecture seule par defaut.** Un outil qui modifie un etat demande une justification
separee et des garanties supplementaires.

**Un refus est une observation, pas une panne.** Un outil inconnu ou des arguments
invalides sont des erreurs du modele, pas du systeme. Les rendre au modele sous forme
d'observation lui laisse une chance de se corriger ; lever une exception ferait
tomber la requete pour une erreur rattrapable.

## Borner une boucle d'agent

Quatre plafonds, et ils ne sont pas redondants :

| Plafond | Ce qu'il borne | Ce qu'il ne borne pas |
|---|---|---|
| Liste blanche d'outils | ce qui peut s'executer | combien de fois |
| Iterations | le nombre de tours | la duree d'un tour |
| Appels par tour | les appels sortants simultanes | le nombre de tours |
| Budget de temps total | **la duree, quoi qu'il arrive** | — |

Le budget de temps est le seul qui tienne face a un appel unique qui ne revient
jamais : les plafonds de comptage n'avancent plus, donc ne declenchent plus. Dans un
environnement asynchrone, l'annulation est une operation de premiere classe, ce qui
rend ce plafond implementable proprement.

## Savoir repondre « je ne trouve rien »

Une recherche vectorielle renvoie toujours les k plus proches voisins, pertinents ou
non. Sans **seuil de similarite minimal**, le systeme construit un contexte hors
sujet et demande au modele d'y repondre — c'est-a-dire de repondre de memoire, le
mode de defaillance exact qu'un RAG est cense supprimer.

Le seuil se fixe par la mesure, pas au jugement : sur un jeu de questions couvertes
et un jeu de questions hors sujet, il se place entre le pire score couvert et le
meilleur score hors sujet. Il depend du modele d'embeddings **et** de sa revision :
en changer impose de recalibrer.

Deux limites a connaitre. Le seuil separe le **pertinent du hors-sujet**, pas le
**couvert du non-couvert** : une question du domaine a laquelle le corpus ne repond
pas franchira quand meme le seuil. Et un document empoisonne concu pour ressembler
aux questions courantes le franchira **par construction**.

## Proteger le corpus

Le corpus est une entree hostile **differee** : un document empoisonne agit au moment
de la recuperation, pas de l'ingestion, souvent pour un autre utilisateur.

**Ne jamais ecrire dans le corpus a l'execution.** Le contenu renvoye par un outil
tiers est une observation ephemere, consommee puis jetee. L'ingerer ferait determiner
le contenu de la base par les questions posees — une injection indirecte dotee d'une
primitive d'ecriture.

**Conserver la provenance de chaque fragment**, refuser a la lecture un point qui
n'en porte pas, et pouvoir retirer une source puis re-indexer.

**Verifier l'integrite** des documents ingeres par des empreintes commitees, et
traiter les fichiers de corpus comme du code en revue : la prose se relit moins
attentivement que le code, et c'est precisement ce sur quoi compte un attaquant.

**Le mensonge plausible ne se defend pas par du code.** Aucun garde-fou ne distingue
un conseil de securite juste d'un conseil faux. La parade est la curation : une liste
blanche de documents d'autorites connues, ou ajouter une source est une decision.

## Journaux et traces : deux destinations, deux regles

Les journaux partent vers un agregateur, sont conserves longtemps et lus largement.
Ils ne doivent jamais contenir la question de l'utilisateur, le contenu d'un
document, ni une cle. Les arguments d'outils s'y tracent **par leurs cles, jamais par
leurs valeurs**.

Les traces d'execution, elles, contiennent deliberement ce contenu — sans lui elles
ne serviraient a rien. L'arbitrage n'est acceptable qu'a une condition : que la
destination reste maitrisee, et soit traitee comme un depot de donnees sensibles.

Un identifiant par requete relie les deux, et toute valeur fournie par le client et
recopiee dans un journal doit etre validee contre une forme stricte, sous peine
d'injection de journaux.

## Guardrail de sortie : utile, et incomplet par construction

Filtrer les secrets reconnaissables avant de renvoyer une reponse est une derniere
ligne de defense. Trois points a tenir :

Un filtre par motifs attrape des **formes connues**, pas « tout ce qui est secret » ;
un mot de passe en clair au milieu d'une phrase passera. Le presenter comme une
garantie serait un mensonge.

En **streaming**, un secret coupe entre deux fragments est recompose par le client :
il faut retenir une fenetre dimensionnee sur la plus longue correspondance possible,
ce qui impose des quantificateurs bornes dans les motifs.

Si le filtre declenche, **une barriere en amont a deja cede** : l'evenement merite un
avertissement, pas un silence satisfait.
