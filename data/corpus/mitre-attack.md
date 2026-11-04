# MITRE ATT&CK — tactiques et techniques adverses

Synthese redigee pour ce projet. Referentiel : MITRE ATT&CK, matrice Enterprise.
Ce document ne reproduit pas le texte source ; il en restitue la substance dans les
mots du projet. Le pendant pour les systemes d'IA est traite dans `mitre-atlas.md`.

## Ce qu'est ATT&CK, et ce qu'il n'est pas

ATT&CK est une base de connaissances de comportements adverses observes dans des
intrusions reelles. Ce n'est **ni un catalogue de vulnerabilites** comme les CVE,
**ni une liste de controles** comme un referentiel de conformite.

La distinction structure tout le reste : une CVE decrit un defaut dans un produit ;
une technique ATT&CK decrit ce qu'un adversaire **fait**, independamment du defaut
qu'il exploite. Un attaquant peut obtenir une execution de code par une CVE, par un
mot de passe vole ou par un macro Office — la technique d'execution est la meme, et
la detection qu'on y oppose aussi.

Trois niveaux : les **tactiques** disent *pourquoi* (l'objectif de l'etape), les
**techniques** disent *comment*, les **procedures** decrivent une mise en oeuvre
precise par un groupe identifie.

## Les tactiques de la matrice Enterprise

**Reconnaissance.** L'adversaire collecte des informations sur la cible avant toute
interaction avec ses systemes : noms et fonctions des employes, domaines et
sous-domaines, technologies exposees sur Internet, identifiants ayant fuite dans des
breches anterieures. Cette tactique se deroule largement hors du perimetre defendu,
ce qui la place hors de portee de la detection : on ne voit pas quelqu'un lire une
page publique.

**Developpement de ressources.** L'adversaire batit l'infrastructure de l'intrusion :
enregistrement de domaines proches de ceux de la cible, creation de comptes de
messagerie, achat de certificats, mise en place de serveurs de commande. Egalement
invisible depuis la cible, mais parfois detectable par veille sur les enregistrements
de domaines.

**Acces initial.** Le premier pied dans le systeme d'information cible. Les vecteurs
dominants sont l'hameconnage avec piece jointe ou lien, l'exploitation d'une
vulnerabilite sur un service expose — passerelle VPN, serveur de messagerie,
application web — et l'usage d'identifiants valides obtenus par achat, par fuite ou
par pulverisation de mots de passe. La compromission d'un fournisseur de logiciel
atteint le meme objectif en contournant le perimetre.

**Execution.** Faire executer du code adverse sur un systeme de la cible :
interpreteur de commandes systeme ou PowerShell, macro de document bureautique,
tache planifiee, ou detournement d'un outil d'administration legitime deja installe.
Cette derniere forme, dite usage d'outils vivant sur le terrain, complique la
detection parce que le binaire employe est legitime et signe.

**Persistance.** Conserver l'acces malgre un redemarrage, une rotation de mot de
passe ou une reinstallation partielle : service systeme installe, cle de registre de
demarrage automatique, compte local cree, tache recurrente, implant dans le
micrologiciel. Sans persistance, l'adversaire perd son acces au premier incident
d'exploitation.

**Elevation de privileges.** Obtenir des droits superieurs a ceux du compte initial,
typiquement administrateur local puis administrateur de domaine. Les voies usuelles
sont l'exploitation d'une vulnerabilite du noyau ou d'un pilote, un service dont les
permissions de fichier sont trop larges, et le vol d'un jeton d'acces appartenant a
un processus plus privilegie.

**Evasion des defenses.** Echapper aux mecanismes de detection : desactiver la
journalisation ou l'antivirus, effacer les journaux d'evenements, signer un binaire
malveillant avec un certificat vole, chiffrer la charge, ou s'executer entierement en
memoire sans jamais ecrire sur le disque.

**Acces aux identifiants.** Recuperer mots de passe, empreintes et jetons
d'authentification : extraction depuis la memoire du processus d'authentification,
lecture de fichiers de configuration contenant des identifiants en clair,
interception de trafic d'authentification, attaque par force brute ou par
pulverisation. C'est la tactique charniere : elle transforme un acces isole en acces
generalise.

**Decouverte.** Cartographier l'environnement depuis l'interieur : enumeration des
comptes et des groupes, des partages reseau, des machines du domaine, des relations
d'approbation, et des produits de securite installes. L'adversaire cherche a savoir
ou il est avant de decider ou aller.

**Mouvement lateral.** Se deplacer d'un systeme a l'autre a l'aide d'identifiants
valides, en empruntant les memes protocoles que l'administration legitime : bureau a
distance, partage administratif, execution distante, gestion a distance. La
legitimite apparente de ce trafic est precisement ce qui rend cette tactique
difficile a distinguer de l'activite normale.

**Collecte.** Rassembler les donnees visees avant de les sortir : fichiers de
partages, boites de messagerie, captures d'ecran, frappes clavier, bases de donnees.
L'etape d'archivage et de chiffrement prealable est souvent le dernier signal
observable avant l'exfiltration.

**Commande et controle.** Maintenir un canal de pilotage avec l'exterieur, dissimule
dans du trafic banal : HTTPS vers un domaine anodin, requetes DNS encodant les
donnees, abus d'un service infonuagique legitime. Les implants modernes espacent
leurs contacts et ajoutent du bruit temporel pour echapper a la detection par
periodicite.

**Exfiltration.** Sortir les donnees du perimetre, parfois lentement et par fragments
pour rester sous les seuils d'alerte volumetriques, souvent par le meme canal que la
commande et le controle, ou vers un service de partage de fichiers grand public.

**Impact.** Atteindre l'objectif final au detriment de la cible : chiffrement des
donnees contre rancon, destruction de sauvegardes, falsification de donnees
financieres, ou interruption de service. C'est la seule tactique dont les effets sont
immediatement visibles de la victime.

## Pourquoi l'enchainement compte plus que la technique

Une intrusion reelle traverse plusieurs tactiques. L'interet defensif d'ATT&CK n'est
pas de dresser la liste exhaustive des techniques a bloquer — elle est trop longue et
elle evolue — mais d'identifier les **points de passage obliges**.

Bloquer ou detecter une seule etape suffit souvent a annuler la chaine. Investir sur
l'acces aux identifiants et le mouvement lateral rapporte generalement davantage que
de multiplier les regles sur l'acces initial, parce que presque toutes les chaines y
passent alors que les portes d'entree sont innombrables.

## Usages pratiques

**Couverture de detection.** Projeter les regles existantes sur la matrice fait
apparaitre les zones aveugles. Attention a l'illusion inverse : une case coloree ne
dit pas que la detection est fiable, seulement qu'une regle existe.

**Emulation adverse.** Rejouer les procedures d'un groupe connu pour pertinent dans
son secteur, et mesurer ce qui est detecte. Plus informatif qu'un test de penetration
generique, parce que le scenario est realiste.

**Langage commun.** Decrire un incident en tactiques et techniques permet a des
equipes differentes de parler du meme evenement sans ambiguite.

## Lien avec les CVE et avec ATLAS

Une **CVE** nomme un defaut precis dans un produit precis, avec un score CVSS qui
estime sa gravite intrinseque. ATT&CK nomme un comportement. Les deux se combinent :
une CVE d'execution de code a distance est un moyen parmi d'autres d'atteindre la
tactique d'acces initial.

**ATLAS** transpose la demarche aux systemes d'apprentissage automatique, avec des
tactiques propres — acces au modele, empoisonnement, extraction — qui n'ont pas
d'equivalent dans la matrice Enterprise.
