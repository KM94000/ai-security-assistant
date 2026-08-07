# ADR-0006 : Embeddings sentence-transformers all-MiniLM-L6-v2

- Statut : accepté
- Date : 2026-08-05

## Contexte
Le RAG a besoin de transformer texte (chunks et questions) en vecteurs. Le choix
du modèle d'embeddings arbitre entre qualité sémantique, vitesse, coût et
confidentialité des données.

## Décision
Utiliser **`all-MiniLM-L6-v2`** (sentence-transformers), en local, produisant des
vecteurs de **384 dimensions**, derrière l'interface `Embedder` (ADR-0002).

## Alternatives envisagées
- **all-mpnet-base-v2 (768 dim)** : meilleure qualité, mais ~2× plus lourd et
  plus lent. Sera évalué en M6 (comparaison qualité/latence via RAGAS) et adopté
  si les chiffres le justifient.
- **Embeddings via API** : qualité élevée, mais coût et externalisation des
  données. Écarté (cohérence avec ADR-0003).

## Conséquences
- (+) Léger, rapide sur CPU, gratuit, données locales.
- (+) Choix réversible : swap vers mpnet possible (recréer la collection + ré-
  ingérer, cf. ADR-0005).
- (−) Qualité de récupération potentiellement inférieure à un modèle plus gros —
  assumé pour démarrer ; décision guidée par la mesure, pas par l'intuition
  (ne pas sur-optimiser avant d'avoir des données).
