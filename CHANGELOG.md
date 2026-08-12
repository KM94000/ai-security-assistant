# Changelog

## [Non publie] - M1, ticket 9 : base vectorielle Qdrant
### Ajoute
- Interface `VectorStore` (`ensure_collection`, `add`, `search`) et dataclass
  `SearchResult` {text, source, score}.
- Implementation `QdrantVectorStore`, client injectable.
- `ensure_collection` idempotent, qui leve `CollectionDimensionMismatchError`
  si la collection existe avec une autre dimension au lieu de degrader la
  recherche en silence.
- Provenance obligatoire : chaque point porte `text` et `source` en payload, et
  un point sans provenance exploitable est refuse a la lecture plutot que rendu
  avec des valeurs par defaut.
- Identifiants de points derives de (source, texte) : re-ingerer un corpus met
  a jour au lieu de dupliquer.
- Controle d'alignement dans `add` : des sequences de longueurs differentes
  associeraient un extrait a la provenance d'un autre.
- 12 tests unitaires sur un Qdrant en memoire, plus 2 tests d'integration
  contre le conteneur, dont la chaine complete MiniLM puis indexation puis
  recherche semantique.
- Parametres `qdrant_url` et `qdrant_collection`, refletes dans `.env.example`.

### Modifie
- `docker-compose.yml` : service Qdrant active, image epinglee en v1.18.3,
  healthcheck, `depends_on` conditionne a la sante du service, et bloc
  `volumes` remis en fin de fichier.

## [Non publie] - M1, ticket 8 : interfaces LLM et embeddings
### Ajoute
- Interface `LLMProvider` (`complete`, `stream`) et son implementation
  `OllamaProvider`, avec client HTTP injectable pour des tests sans reseau.
- Interface `Embedder` (`embed`, `dimension`) et son implementation
  `SentenceTransformerEmbedder` (all-MiniLM-L6-v2, chargement paresseux,
  vectorisation deportee hors de la boucle d'evenements).
- Garde-fou de dimension : un modele dont la dimension differe de la
  configuration leve `DimensionMismatchError` au lieu de degrader la recherche
  en silence.
- Erreurs typees `LLMError`, `EmbedderError` : les exceptions des bibliotheques
  tierces ne remontent pas au metier.
- Parametres de configuration pour Ollama et les embeddings, refletes dans
  `.env.example`.
- Marqueur pytest `integration`, exclu par defaut : tests contre le vrai serveur
  Ollama et le vrai modele MiniLM, lances avec `pytest -m integration`.
- ADR-0008 : interfaces asynchrones des M1.

### Modifie
- Plancher Python releve de 3.11 a 3.12 : les stubs de numpy, tire par
  sentence-transformers, exigent la syntaxe PEP 695.
- `httpx` passe des dependances de dev aux dependances d'execution.
- Tests reorganises en `tests/unit/` et `tests/integration/` (CLAUDE.md 5).
- CI : cache pip active, le telechargement de torch n'etant pas repete a chaque job.
- CI : gitleaks lance via son binaire epingle plutot que via gitleaks-action@v2,
  cassee par la migration forcee des runners GitHub de Node 20 vers Node 24.
  Meme binaire et meme version qu'en pre-commit, donc meme verdict des deux cotes.

## [Non publie] - Consolidation avant M1
### Ajoute
- Documentation de conception rapatriee dans le depot : ARCHITECTURE, BUILD_PLAN,
  DESIGN, SECURITY et ADR-0002 a ADR-0007 (les ADR sont desormais contigus 0000-0007).
- Scans securite en CI : gitleaks (secrets), pip-audit (dependances), bandit (SAST).
- gitleaks en pre-commit comme garde-fou local, conformement a ARCHITECTURE.md.
- Colonne "Statut" dans la matrice de tests de SECURITY.md : tableau de bord
  verifiable de la couverture securite, mis a jour par la PR qui implemente la barriere.

### Modifie
- Environnement de dev aligne sur la CI en Python 3.12 (via uv).
- Dockerfile : l'API ne s'execute plus en root (utilisateur `appuser`).
- pre-commit : retrait de `ruff-format`, black reste le seul formateur.
- Revisions pre-commit epinglees sur les versions courantes.

## [0.1.0] - M0 : fondations
- Squelette FastAPI avec endpoint /health
- Qualite : ruff, black, mypy, pre-commit
- CI GitHub Actions (lint + types + tests)
- Conteneurisation Docker + docker-compose
- ADR-0001 : choix de la stack technique
