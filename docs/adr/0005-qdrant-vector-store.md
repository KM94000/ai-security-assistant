# ADR-0005 : Qdrant comme base vectorielle

- Statut : accepté
- Date : 2026-08-05

## Contexte
Le RAG (ADR-0004) nécessite de stocker des embeddings et d'effectuer une
recherche par similarité. Le choix de la base influence la crédibilité "prod" du
projet et l'apprentissage visé.

## Décision
Utiliser **Qdrant**, conteneurisé via docker-compose, derrière l'interface
`VectorStore` (ADR-0002). Collection dimensionnée pour les embeddings MiniLM
(384), la dimension étant un paramètre de configuration.

## Alternatives envisagées
- **ChromaDB (embarqué)** : zéro infra, démarrage immédiat, mais perçu comme
  outil de prototype. Envisagé comme plan B pour démarrer sans Docker.
- **pgvector (Postgres + extension)** : approche "une seule base pour tout", très
  répandue en entreprise ; setup un peu plus lourd. Alternative valable.
- **FAISS (fichier local)** : simple mais bas niveau, pas un service/serveur.
  Écarté seul.

## Conséquences
- (+) Vraie base vectorielle "prod", dashboard de visualisation, scalable ;
  renforce la démonstration de conteneurisation attendue par les offres cibles.
- (+) Interchangeable via `VectorStore` si un autre backend s'impose.
- (−) Nécessite Docker (dépendance d'infra) — accepté, car l'apprentissage de la
  conteneurisation fait partie des objectifs.
- ⚠️ La dimension de la collection doit correspondre au modèle d'embeddings :
  changer de modèle impose de recréer la collection et de ré-ingérer.
