# ADR-0014 : Logs structurés en enveloppant `logging`, contexte par `ContextVar`

- Statut : accepté
- Date : 2026-09-24

## Contexte

Le projet comptait **vingt-cinq appels** au module `logging` standard répartis
dans dix modules, et **aucune configuration**. Concrètement : rien n'était
horodaté, rien n'indiquait le module d'origine, et les messages partaient dans
la configuration par défaut de Python — c'est-à-dire, en production, nulle part.

Deux besoins convergent.

**Un besoin de sécurité.** SEC-12 (*fuite via les logs*) est classé P1 et restait
en ⬜. Depuis le ticket 26, le produit détient une clé d'API : l'enjeu a cessé
d'être théorique.

**Un besoin d'exploitation.** Sans identifiant par requête, les traces de trois
requêtes concurrentes s'entrelacent dans le même flux, et plus personne ne sait
quelle recherche a précédé quelle génération.

## Décision

**1. `structlog` branché *en aval* de `logging`, pas à sa place.** La
configuration installe un `ProcessorFormatter` dont la `foreign_pre_chain`
traite les enregistrements venus du module standard. Conséquence directe : les
vingt-cinq appels existants — et ceux des bibliothèques tierces — traversent la
même chaîne et ressortent au même format, **sans qu'une seule ligne de métier ne
soit réécrite**.

**2. L'identifiant de requête voyage par `ContextVar`, jamais en paramètre.**
Ajouter `request_id` aux signatures aurait propagé la modification à toute la
chaîne d'appel, jusqu'aux doubles de test — exactement la migration virale que
l'ADR-0008 décrit pour l'asynchrone. Une variable de contexte est portée par la
tâche asyncio courante : chaque requête a la sienne, sans qu'aucun code
intermédiaire n'ait à la connaître.

**3. Intergiciel ASGI écrit à la main, pas `BaseHTTPMiddleware`.** Ce dernier
exécute la suite du traitement dans une tâche distincte, ce qui **casse la
propagation des variables de contexte** — c'est-à-dire précisément la mécanique
dont dépend la décision 2.

**4. Un `X-Request-ID` client est accepté, mais strictement validé.** La
corrélation doit pouvoir traverser les frontières de service, donc on reprend la
valeur fournie. Mais elle atterrit dans chaque ligne de journal de la requête,
ce qui ouvre deux portes :

- **l'injection de logs** — un saut de ligne, et l'attaquant fabrique une ligne
  entière qu'un agrégateur indexera comme un événement authentique, de quoi
  masquer une intrusion sous un faux « connexion réussie » ;
- **le gonflement** — dix kilo-octets recopiés dans chaque ligne, multipliés par
  le nombre de requêtes.

D'où `^[A-Za-z0-9_-]{1,64}$`. Une valeur non conforme est **ignorée sans erreur**
et remplacée : refuser la requête punirait un client mal configuré pour un
détail de confort.

**5. JSON par défaut**, console lisible en développement. Et une sortie
injectable, pour que les tests lisent ce qui a été émis sans dépendre du
mécanisme de capture de pytest, qui s'interpose entre `logging` et la sortie
standard.

## Alternatives envisagées

- **Réécrire les vingt-cinq appels avec l'API native de structlog.** Plus
  idiomatique, et l'appel gagnerait des champs nommés plutôt qu'un message
  interpolé. Écartée : vingt-cinq modifications pour un gain de forme, et les
  bibliothèques tierces continueraient de contourner la chaîne. À reprendre
  appel par appel, quand l'un d'eux aura besoin de champs structurés.
- **`logging` seul avec un formateur JSON.** Une dépendance en moins. Écartée :
  il aurait fallu écrire à la main l'intégration avec les variables de contexte,
  c'est-à-dire la seule partie non triviale.
- **Passer `request_id` en paramètre.** Explicite, traçable à la lecture.
  Écartée : voir décision 2.
- **`BaseHTTPMiddleware` de Starlette.** Plus court à écrire. Écartée : voir
  décision 3.

## Conséquences

- (+) **Vingt-cinq appels instrumentés sans en éditer un seul.** Le bénéfice est
  immédiat et vérifié par test : un `logging.warning` inchangé ressort en JSON,
  horodaté, avec le module d'origine et l'identifiant de la requête.
- (+) Le volet **logs** de SEC-12 est fermé et testé, y compris l'injection de
  logs. Vérifié par mutation : désactiver la validation fait rougir neuf tests.
- (+) Le client reçoit l'identifiant en en-tête de réponse, et peut donc le
  citer en signalant une panne.
- (−) **SEC-12 n'est fermé qu'à moitié.** Sa formulation dit « logs *et* traces »
  ; les traces arrivent au ticket 24. Le statut reste 🟡, et le dire est le
  seul moyen de garder la matrice crédible.
- (−) La double configuration structlog + `logging` est subtile. Quelqu'un qui
  découvre le fichier doit comprendre à quoi sert `foreign_pre_chain` — d'où le
  commentaire qui le désigne comme la pièce maîtresse.
- (−) Une dépendance de plus, et un intergiciel écrit à la main plutôt qu'emprunté
  au cadre.
