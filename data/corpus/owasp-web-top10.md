# OWASP Top 10 — applications web (2021)

Synthese redigee pour ce projet. Referentiel : OWASP Top 10 for Web Applications,
edition 2021. Ce document ne reproduit pas le texte source ; il en restitue la
substance dans les mots du projet.

## Pourquoi ce referentiel dans un assistant d'IA

Une application a base de LLM reste une application web. Elle expose une API, parle
a une base de donnees, rend du contenu a un navigateur. Les categories ci-dessous
s'y appliquent integralement, et plusieurs ont un cousin direct cote LLM : une
injection SQL et une injection de prompt partagent le meme defaut de conception —
des donnees non fiables melees a des instructions.

## A01 — Controle d'acces defaillant

La categorie la plus repandue. L'application verifie l'authentification mais pas
l'autorisation : savoir **qui** est l'appelant ne dit pas **ce qu'il a le droit de
faire**. Les formes courantes sont l'acces direct a un objet par son identifiant,
l'elevation de privilege par un parametre de requete, et les controles appliques
cote client seulement.

Remediation : refuser par defaut, verifier l'autorisation cote serveur a chaque
acces a une ressource, ne jamais deduire les droits d'une valeur fournie par le
client. Les identifiants imprevisibles ne sont pas un controle d'acces.

## A02 — Defaillances cryptographiques

Donnees sensibles transmises ou stockees sans protection adequate : absence de TLS,
algorithmes obsoletes, cles codees en dur, mots de passe haches avec une fonction
rapide. Le defaut d'origine est souvent de ne pas avoir classe les donnees : on ne
protege pas ce qu'on n'a pas identifie comme sensible.

Remediation : chiffrer en transit et au repos, utiliser une fonction de derivation
lente pour les mots de passe, sortir les secrets du code et les gerer par
l'environnement ou un coffre.

## A03 — Injection

Des donnees non fiables sont interpretees comme du code ou une commande. La famille
couvre l'injection SQL, l'injection de commande systeme, l'injection LDAP et le XSS.

**Injection SQL.** La requete est construite par concatenation de chaines, et une
valeur fournie par l'utilisateur en modifie la structure. La parade n'est pas
l'echappement manuel mais les **requetes parametrees** : la structure de la requete
est fixee par le code, les valeurs circulent dans un canal separe qui ne peut pas
la modifier.

**Injection de commande.** Une entree atteint un shell. La parade est de ne pas
invoquer de shell : passer les arguments sous forme de liste a l'appel systeme, et
valider chaque argument contre une forme attendue stricte plutot que contre une
liste de caracteres interdits.

**XSS.** Du contenu non fiable est rendu dans une page et execute par le navigateur.
Trois contextes a distinguer : corps HTML, attribut, et code JavaScript — chacun
exige un echappement different. Une politique de securite de contenu limite les
degats sans remplacer l'echappement.

Le principe commun : **separer structurellement les donnees des instructions**,
plutot que de tenter de reconnaitre les donnees dangereuses. C'est exactement le
raisonnement qui s'applique a l'injection de prompt.

## A04 — Conception non securisee

Un defaut de conception, pas d'implementation. Aucune quantite de code correct ne
rattrape une architecture qui, par exemple, fait confiance a un systeme tiers sans
verification, ou ne prevoit aucune limite de debit sur une operation couteuse.

Remediation : modelisation de menace en amont, scenarios d'abus ecrits a cote des
scenarios d'usage, limites de ressources prevues des la conception.

## A05 — Mauvaise configuration de securite

Comptes par defaut, pages d'erreur bavardes, services d'administration exposes,
droits trop larges sur un service de stockage, en-tetes de securite absents. La
cause la plus frequente est l'ecart entre l'environnement de developpement, ou tout
est ouvert pour aller vite, et la production.

Remediation : configuration durcie par defaut, environnements construits par la
meme procedure, verification automatisee de la configuration.

## A06 — Composants vulnerables et obsoletes

Une dependance connue vulnerable reste en production parce que personne ne suit son
cycle de vie. La difficulte n'est pas technique mais organisationnelle : savoir ce
qui est installe, et avoir un chemin de mise a jour praticable.

Remediation : inventaire des dependances, analyse automatisee en integration
continue, mise a jour reguliere plutot qu'en urgence.

## A07 — Defaillances d'identification et d'authentification

Mots de passe faibles autorises, absence de limitation des tentatives, jetons de
session previsibles ou jamais invalides, recuperation de compte plus faible que la
connexion elle-meme.

Remediation : authentification multifacteur, limitation des tentatives, rotation et
invalidation des sessions, traiter le parcours de recuperation avec la meme
exigence que le parcours de connexion.

## A08 — Defaut d'integrite des donnees et du logiciel

Le code ou les donnees proviennent de sources dont l'integrite n'est pas verifiee :
mise a jour automatique non signee, dependance tiree d'un depot non fiable,
deserialisation d'un objet fourni par le client.

Remediation : signatures et sommes de controle, epinglage des versions, ne jamais
deserialiser un format capable d'instancier des objets arbitraires depuis une
entree non fiable.

## A09 — Carences de journalisation et de supervision

L'attaque reussit et personne ne le voit. Les evenements de securite ne sont pas
journalises, ou le sont sans contexte exploitable, ou partent dans un flux que
personne ne lit.

Un sous-cas souvent neglige : **l'injection de journaux**. Une valeur fournie par
l'utilisateur et recopiee telle quelle dans une ligne de journal permet, via un
saut de ligne, de fabriquer une fausse entree qu'un agregateur indexera comme un
evenement authentique.

Remediation : journaliser les evenements d'authentification et d'autorisation, un
identifiant de correlation par requete, valider strictement toute valeur cliente
recopiee dans un journal, et ne jamais y ecrire de secret.

## A10 — Falsification de requete cote serveur (SSRF)

L'application emet une requete vers une destination que l'attaquant controle, en
tout ou partie. Le serveur se trouve souvent a l'interieur du perimetre : il atteint
le service de metadonnees de l'hebergeur, les interfaces d'administration internes,
ou des services ecoutant sur la boucle locale.

Remediation : ne jamais construire une destination a partir d'une entree non fiable.
L'hote et le chemin viennent de la configuration ; l'entree ne fournit au mieux
qu'un parametre, valide contre une forme stricte et transmis comme parametre de
requete, jamais concatene dans une URL. Restreindre les sorties reseau du service et
n'autoriser que les verbes necessaires.

## Correspondances avec les risques propres aux LLM

| Risque web | Cousin cote LLM |
|---|---|
| Injection SQL / commande | Injection de prompt — donnees melees aux instructions |
| XSS | Traitement incorrect des sorties du modele |
| Controle d'acces defaillant | Autonomie excessive d'un agent |
| SSRF | Outil d'agent dont la destination depend du modele |
| Carences de journalisation | Absence de trace des appels d'outils |

La lecon transversale : les defauts propres aux LLM ne sont pas une famille nouvelle,
ce sont des defauts connus qui reapparaissent a une frontiere de confiance nouvelle.
