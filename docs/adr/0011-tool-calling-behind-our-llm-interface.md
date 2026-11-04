# ADR-0011 : Appels d'outils derrière notre interface LLM, orchestration LangGraph

- Statut : accepté
- Date : 2026-09-17

## Contexte

M3 introduit un agent : le modèle décide d'appeler un outil — la recherche dans
le corpus — puis répond à partir de son résultat. Deux besoins nouveaux
apparaissent.

**Un besoin technique.** Notre interface `LLMProvider` sait produire du texte
(`complete`, `stream`). Un agent a besoin d'autre chose : présenter des outils au
modèle et recevoir un **appel structuré** en retour. Ollama le permet via
`/api/chat`, et `llama3.1` sait s'en servir.

**Un besoin d'orchestration.** Enchaîner « décider → appeler → observer →
recommencer », avec une condition d'arrêt.

Deux chemins s'offraient : utiliser la liaison Ollama fournie par LangChain, que
LangGraph attend naturellement, ou étendre notre propre interface.

## Décision

**1. Une interface distincte, `ToolCallingProvider`.** Elle ajoute une méthode
`chat(messages, tools) -> ChatReply`, avec ses types (`ChatMessage`, `ToolSpec`,
`ToolCall`). `OllamaProvider` implémente les deux interfaces ; `/query` continue
de n'utiliser que `LLMProvider`.

Interface séparée plutôt qu'une méthode de plus sur `LLMProvider` : exiger
l'appel d'outils de tout fournisseur imposerait une capacité dont la moitié du
produit n'a pas l'usage, et que les doubles de test devraient simuler pour rien.

**2. Aucune liaison LangChain vers le modèle.** Le graphe appelle notre
interface. La règle du projet est que le métier ne dépend jamais d'une
implémentation concrète (ADR-0002) ; passer par `ChatOllama` aurait introduit un
second chemin vers le modèle, avec ses propres réglages de délai, d'erreurs et
de sérialisation — et deux comportements à tenir alignés.

**3. Le fournisseur traduit, il ne décide pas.** Il n'exécute aucun outil, n'en
refuse aucun, ne valide aucun argument. Ces décisions appartiennent à l'agent,
qui détient la liste blanche et les règles de validation (SEC-05, SEC-06). Un
appel d'outil malformé est écarté et compté, pas transformé en panne : c'est une
erreur du modèle, pas du serveur.

**4. LangGraph pour l'orchestration**, conformément à l'ADR-0001 et au plan de
build. Le graphe reste minuscule — trois nœuds — et il est le seul module à
dépendre du framework.

**5. Température nulle sur le chemin outillé.** Ollama échantillonne à 0,8 par
défaut. Mesuré : la même conversation donne un appel structuré une fois, et la
fois suivante un texte qui *décrit* l'appel en JSON — que le code refuse
d'interpréter, puisqu'il n'a pas transité par le canal prévu. Choisir un outil
n'appelle aucune créativité, et une décision reproductible est une décision
auditable.

## Alternatives envisagées

- **Boucle écrite à la main**, sans dépendance. Techniquement suffisante pour un
  agent à un outil : une cinquantaine de lignes. Écartée parce que la stack est
  figée par l'ADR-0001 et que les tickets suivants (outils multiples, exposition
  MCP) tirent vers un graphe. À rouvrir si LangGraph devenait un poids mort : le
  coût du retour arrière se limite à un module.
- **`ChatOllama` de LangChain comme modèle du graphe.** Écartée : deux chemins
  vers le même serveur, et notre abstraction contournée.
- **Ajouter `chat` à `LLMProvider`.** Écartée : voir ci-dessus.

## Réévaluation du 2026-09-25

L'ADR prévoyait de rouvrir la question « si LangGraph devenait un poids mort ».
Fait, avant d'ajouter Langfuse — il aurait été absurde d'installer un second SDK
de traçage à côté du `langsmith` inutilisé que LangGraph entraîne.

**Les mesures.** Douze paquets pour **un seul import** dans tout le code source.
Deux `Any` dans une base en `mypy --strict`, uniquement pour ce module. Et deux
tickets consécutifs qui n'en ont tiré aucun bénéfice : le ticket 20 a ajouté un
second outil sans que le graphe ne change d'une ligne, et le ticket 21 a dû
implémenter le budget de temps **en dehors** du graphe, qui ne savait pas
l'exprimer.

**Décision : garder, pour l'instant.** Non par conviction, mais par arbitrage de
calendrier. Le retrait est faisable — les quatre nœuds survivraient tels quels,
seule leur orchestration changerait — mais ce serait un troisième écart au plan
de build en une semaine, et M5 reste le jalon qui valide le titre du projet.
`langsmith` est par ailleurs inerte tant qu'aucune variable d'environnement ne
l'active : le coût est une surface de chaîne d'approvisionnement, pas un
comportement.

**À reprendre en M6**, avec la revue des dépendances et `uv lock`. Critère fixé
d'avance : remplacer le graphe par une boucle et vérifier que les tests passent
**sans modification**. S'il faut en retoucher un seul, le graphe apportait
quelque chose.

## Conséquences

- (+) Le métier ne connaît que nos types. Changer de fournisseur ou de framework
  d'orchestration reste un travail local.
- (+) Les tests d'agent tournent sans modèle : un double rejoue un script de
  réponses, y compris des réponses hostiles qu'un vrai modèle produirait
  rarement à la demande — outil inexistant, rafale d'appels, boucle sans fin.
- (−) **22 paquets transitifs** ajoutés par LangGraph, dont `langchain-core` et
  `langsmith`. C'est la dépendance la plus lourde du projet en nombre de
  paquets, donc en surface de chaîne d'approvisionnement (LLM03). Le traçage
  LangSmith est inactif tant qu'aucune variable d'environnement ne l'active ;
  notre observabilité passera par Langfuse en M4.
- (−) Deux interfaces à maintenir au lieu d'une, et `OllamaProvider` qui en
  implémente deux.
- (−) Un agent coûte plusieurs allers-retours avec le modèle là où `/query` n'en
  fait qu'un. Sur un modèle local exécuté sur CPU, la latence se compte en
  dizaines de secondes par tour. C'est acceptable en développement, et c'est une
  raison de plus pour que le plafond d'itérations soit bas.
