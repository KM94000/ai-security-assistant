# ADR-0004 : RAG plutôt que fine-tuning

- Statut : accepté
- Date : 2026-08-05

## Contexte
L'assistant doit répondre à des questions de cybersécurité en s'appuyant sur des
sources de référence (OWASP au départ), et surtout **citer ses sources** sans
halluciner. Deux grandes approches : adapter le modèle (fine-tuning) ou lui
fournir le contexte au moment de la requête (RAG).

## Décision
Adopter le **RAG** (Retrieval-Augmented Generation) : indexer le corpus dans une
base vectorielle et fournir au LLM les passages pertinents à chaque question.
Pas de fine-tuning.

## Alternatives envisagées
- **Fine-tuning** : adapte le modèle au domaine, mais coûteux (GPU, données
  d'entraînement), complexe, et n'apporte pas le sourcing des réponses. Souvent
  survendu par rapport à sa valeur réelle. Écarté (voir aussi non-objectifs).
- **Prompt engineering seul, sans récupération** : simple, mais le modèle ne
  connaît pas les documents de référence → hallucinations. Écarté.

## Conséquences
- (+) Réponses fondées et **sourçables** ; corpus modifiable sans réentraîner ;
  coût quasi nul.
- (+) La qualité devient mesurable (RAGAS : faithfulness, context precision).
- (−) La qualité dépend de la récupération (chunking, embeddings, top-k) — d'où
  l'importance de l'évaluation (M6) et de la conception du pipeline d'ingestion.
