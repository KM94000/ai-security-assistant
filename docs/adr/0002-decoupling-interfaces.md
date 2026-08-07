# ADR-0002 : Découplage par interfaces (LLMProvider, VectorStore, Embedder)

- Statut : accepté
- Date : 2026-08-05

## Contexte
Le produit dépend de trois briques externes susceptibles de changer : le LLM
(Ollama en dev, potentiellement OpenAI/Azure en prod), la base vectorielle
(Qdrant), et le modèle d'embeddings (MiniLM, peut-être mpnet plus tard). Il faut
aussi pouvoir tester la logique métier sans dépendre d'un vrai LLM ou d'une
vraie base.

## Décision
Introduire des interfaces abstraites (`LLMProvider`, `VectorStore`, `Embedder`).
Le code métier ne dépend que de ces abstractions ; les implémentations concrètes
(Ollama, Qdrant, sentence-transformers) sont interchangeables. Principe
d'inversion de dépendance.

## Alternatives envisagées
- **Appels directs aux libs partout** : plus rapide à écrire, mais couplage fort
  → tout changement devient un chantier, et les tests dépendraient de services
  réels (lents, coûteux, non déterministes). Écarté.
- **Framework tout-en-un (LangChain de bout en bout)** : moins de code, mais
  perte de contrôle/compréhension et couplage au framework. Écarté comme couche
  universelle ; LangGraph est utilisé de façon ciblée pour l'agent uniquement.

## Conséquences
- (+) Implémentations remplaçables sans toucher au métier ; tests via doubles.
- (+) Choix techniques (modèle, base) documentés et réversibles.
- (−) Un peu plus de code initial (les interfaces). Compromis assumé : le coût
  est faible face au gain de liberté et de testabilité, cohérent avec l'objectif
  de démontrer une conception maîtrisée.
