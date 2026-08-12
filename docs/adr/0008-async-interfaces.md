# ADR-0008 : Interfaces asynchrones dès M1

- Statut : accepté
- Date : 2026-08-07

## Contexte

`CLAUDE.md` §4 décrit `LLMProvider` avec une signature synchrone
(`complete(prompt) -> str`, `stream(prompt) -> Iterator[str]`), et `Embedder`
avec `embed(texts) -> list[list[float]]`.

Or `CLAUDE.md` §6 impose par ailleurs « async pour les I/O (API, appels LLM,
Qdrant) », et le ticket 14 (M2) prévoit le streaming SSE de `/query`. Ces deux
exigences sont incompatibles avec des interfaces synchrones : un appel bloquant
dans une route FastAPI fige la boucle d'événements et donc toutes les requêtes
concurrentes, et SSE suppose de produire des fragments au fil de l'eau.

La question s'est posée dès le ticket 8, puisque c'est lui qui fige ces
interfaces dont tout le métier va dépendre.

## Décision

Poser les interfaces en **asynchrone dès M1** :

- `LLMProvider.complete` est `async def ... -> str`
- `LLMProvider.stream` renvoie un `AsyncIterator[str]`
- `Embedder.embed` est `async def ... -> list[list[float]]`

La vectorisation n'est pas une I/O mais un calcul CPU bloquant. Elle est donc
déportée dans un thread (`anyio.to_thread.run_sync`) plutôt qu'exécutée
directement : le résultat est attendu de façon asynchrone, sans figer la boucle.

## Alternatives envisagées

- **Suivre CLAUDE.md à la lettre, migrer en M2.** Écarté. Les deux interfaces
  sont, par construction, les plus dépendues du projet : au moment de la
  migration, `retrieval/`, `generation/`, `ingestion/` et `api/` en dépendraient
  déjà. Le coût de la bascule croît à chaque ticket, et une migration de ce type
  se fait au pire moment — sous la pression d'une fonctionnalité à livrer.
- **Doubler l'interface (variantes sync et async).** Écarté : deux chemins de
  code à tester et à maintenir, pour un besoin synchrone qui n'existe nulle part
  dans le produit.
- **Rendre `Embedder.embed` synchrone**, la vectorisation étant du CPU. Écarté
  pour l'uniformité des appelants : `retrieval/` orchestre un embed suivi d'une
  recherche Qdrant asynchrone, et mélanger les deux styles dans une même
  fonction est une source classique de blocage accidentel.

## Conséquences

- (+) Le streaming SSE de M2 se branche sans retoucher les interfaces.
- (+) Aucun appel bloquant ne peut figer l'API, y compris la vectorisation.
- (−) `CLAUDE.md` §4 décrit désormais des signatures obsolètes. Cette ADR fait
  foi ; §4 sera aligné lors de la mise à jour documentaire de M1.
- (−) Les tests doivent tourner sous une boucle d'événements. Traité par le
  plugin pytest d'anyio, déjà présent en dépendance transitive, avec un fixture
  `anyio_backend` limitant l'exécution à asyncio.
