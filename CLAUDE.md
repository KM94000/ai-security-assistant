# CLAUDE.md — Manuel d'opération du projet

> Ce fichier est lu automatiquement par Claude Code. Il définit le contexte, les
> règles de travail et l'architecture. Les specs détaillées sont dans `docs/`.
> **À lire en entier avant toute action.**

---

## 1. Vue d'ensemble

**AI Security Assistant** : une plateforme **RAG + agents** qui répond à des
questions de **cybersécurité** à partir de sources de référence (OWASP, MITRE
ATT&CK/ATLAS, CVE/NVD, NIST), construite comme un **produit de production** et
**durcie contre les attaques propres aux LLM** (OWASP LLM Top 10 2025).

Particularité : la surface d'attaque du produit (injection indirecte via le
corpus ingéré, détournement d'outils par l'agent) est traitée comme un **cas
d'usage de sécurité de premier plan**, pas comme une couche annexe.

- **Utilisateurs** : analyste SOC N1, ingénieur AppSec, développeur.
- **Repo** : github.com/KM94000/ai-security-assistant
- **Package Python** : `aisecassist` · **Python** : >=3.11

---

## 2. Règles d'or (NON négociables)

1. **Un ticket = une branche = une PR.** Jamais de push direct sur `main`.
   Nom de branche : `feature/<n>-slug` ou `fix/<n>-slug`.
2. **Rien ne merge si la CI n'est pas verte** (ruff + black + mypy + pytest +
   scans sécu). La CI est la source de vérité de la qualité.
3. **Definition of Done** (voir §7) respectée pour CHAQUE ticket : code + tests
   + types + doc. Un ticket "codé mais pas testé" n'est PAS fini.
4. **Sécurité par défaut** (voir `docs/SECURITY.md`). Toute entrée est hostile
   jusqu'à preuve du contraire : sorties de LLM, documents ingérés, arguments
   d'outils d'agent, requêtes API. On ne délègue JAMAIS la sécurité au modèle.
5. **Aucun secret dans le code ni les commits.** Tout par variables
   d'environnement. `gitleaks` en CI bloque les fuites.
6. **Découplage par interfaces.** Le code métier dépend d'abstractions
   (`LLMProvider`, `VectorStore`, `Embedder`), jamais d'une implémentation
   concrète. Voir §4.
7. **Une décision d'architecture = un ADR** dans `docs/adr/` (format
   `docs/adr/0000-template.md`).
8. **Ne pas sur-concevoir.** On ajoute une capacité quand un ticket la demande,
   pas "au cas où". Pas de Kubernetes, pas de microservices : monolithe
   conteneurisé.

---

## 3. Stack technique (figée — voir ADR-0001)

| Rôle | Choix | Notes |
|---|---|---|
| API | **FastAPI** + Uvicorn | async, streaming SSE, OpenAPI auto |
| LLM (dev) | **Ollama** + `llama3.1` | local, gratuit, derrière `LLMProvider` |
| LLM (prod) | OpenAI / Azure | swappable sans toucher au métier |
| Embeddings | **sentence-transformers `all-MiniLM-L6-v2`** | **384 dimensions**, local |
| Base vectorielle | **Qdrant** (Docker) | derrière `VectorStore` |
| Agents | **LangGraph** | RAG exposé comme outil |
| Observabilité | **Langfuse** + `structlog` | tracing, tokens, coûts |
| Évaluation | **RAGAS** + `promptfoo` | qualité RAG + red team |
| Qualité | ruff · black · mypy(strict) · pytest · pre-commit | |
| CI/CD | **GitHub Actions** | lint + types + tests + scans sécu |
| Conteneurs | **Docker** + docker-compose | |
| Déploiement | **Render / Railway** | free tier |
| Scans sécu | bandit · pip-audit · gitleaks · Dependabot | en CI |

> ⚠️ **Cohérence dimension embeddings ↔ collection Qdrant** : la collection est
> créée pour 384 dim. Changer de modèle d'embeddings impose de recréer la
> collection et de ré-ingérer. La dimension est un paramètre de config, jamais
> une valeur en dur.

---

## 4. Architecture & interfaces

Flux principal :

```
Client ─HTTP─▶ API FastAPI ─▶ [Sécurité: validation/guardrails/authz]
                    │
                    ├─▶ POST /query  ─▶ Retrieval ─▶ Génération
                    │                     │              │
                    └─▶ POST /agent  ─▶ Agent (LangGraph)─┤
                                          │ (RAG comme outil + outils)
                                          ▼
        Ingestion ─▶ VectorStore(Qdrant) ◀── Retrieval
        Embedder(MiniLM) alimente ingestion ET retrieval
        Observabilité (tracing/tokens/coûts) enveloppe tout
```

**Interfaces abstraites (à définir tôt, tout le métier en dépend) :**

- `LLMProvider` : `complete(prompt) -> str`, `stream(prompt) -> Iterator[str]`.
  Implémentations : `OllamaProvider` (dev), `OpenAIProvider` (prod).
- `VectorStore` : `ensure_collection(dimension)`, `add(texts, vectors, sources)`,
  `search(query_vector, k) -> list[SearchResult]`. Impl : `QdrantVectorStore`.
- `Embedder` : `embed(texts) -> list[list[float]]`, propriété `dimension`.
  Impl : `SentenceTransformerEmbedder`.

`SearchResult` = dataclass `{text, source, score}`.

---

## 5. Carte des modules (`src/aisecassist/`)

| Module | Responsabilité | NE fait PAS |
|---|---|---|
| `config.py` | Settings via env (pydantic-settings) | contenir des secrets en dur |
| `api/` | Routes FastAPI, schémas pydantic, auth | logique métier |
| `llm/` | Interface `LLMProvider` + impls | connaître le RAG |
| `embeddings/` | Interface `Embedder` + impl MiniLM | parler à Qdrant |
| `vectorstore/` | Interface `VectorStore` + impl Qdrant | fabriquer des embeddings |
| `ingestion/` | load → clean → chunk → embed → index | répondre aux requêtes |
| `retrieval/` | recherche vectorielle top-k (+ rerank plus tard) | appeler le LLM |
| `generation/` | prompt templates + appel LLM | faire la recherche |
| `agents/` | agent LangGraph + outils | bypass des contrôles sécu |
| `security/` | validation, guardrails, authz, sanitation | logique métier |
| `observability/` | logging, tracing, métriques | modifier le comportement |

Tests : `tests/unit/` (isolés) et `tests/integration/` (chaîne complète).
Évaluation : `eval/` (harness RAGAS + jeux de test).

---

## 6. Conventions de code

- **Typage strict** partout (`mypy --strict`). Toute fonction publique typée.
- **Pydantic** pour les schémas d'API et la validation d'entrée.
- **Async** pour les I/O (API, appels LLM, Qdrant).
- **Docstrings** sur les modules, classes et fonctions publiques.
- **Pas de logique dans les routes** : la route valide, délègue à un service,
  formate la réponse.
- **Erreurs** : jamais de `except: pass`. Erreurs typées, messages clairs, codes
  HTTP corrects. Ne jamais fuiter de stack trace ni de détail interne au client.
- **Logs structurés** (structlog), un `request_id` par requête. Ne jamais logger
  de secret, de token, ni le contenu sensible d'un document.

---

## 7. Definition of Done (par ticket)

- [ ] Code écrit, typé, conforme ruff/black.
- [ ] Tests unitaires du comportement (cas nominal + cas d'erreur).
- [ ] Si le ticket touche une surface d'attaque : test(s) sécu associés (voir
      `docs/SECURITY.md`, colonne "Test ID").
- [ ] `mypy src` sans erreur.
- [ ] Doc à jour (docstring, et README/ADR si pertinent).
- [ ] CI verte sur la PR.
- [ ] CHANGELOG mis à jour pour les changements notables.

---

## 8. Commandes

```bash
# Installation dev — Python 3.12 comme la CI (uv gère sa propre installation,
# le Python système n'est pas touché). Un venv sur une autre version expose à
# des écarts de wheels (notamment torch pour sentence-transformers).
uv python install 3.12
uv venv --python 3.12 && source .venv/bin/activate   # Win: .venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
pre-commit install

# Qualité (identique à la CI)
ruff check . && black --check . && mypy src && pytest

# Scans sécurité (identiques à la CI)
pip-audit --skip-editable && bandit -r src -c pyproject.toml

# Lancer l'API
uvicorn aisecassist.main:app --reload      # http://localhost:8000/docs

# Services (Qdrant, plus tard Langfuse)
docker compose -f docker/docker-compose.yml up -d qdrant
```

---

## 9. Où trouver quoi

- **Plan de build détaillé (M0→M7, tickets, critères)** → `docs/BUILD_PLAN.md`
- **Sécurité (threat model, OWASP LLM, matrice de tests)** → `docs/SECURITY.md`
- **Conception produit (design doc, décisions, trade-offs)** → `docs/DESIGN.md`
- **Décisions d'architecture** → `docs/adr/`

## 10. Ordre de travail recommandé pour l'agent

Suivre `docs/BUILD_PLAN.md` milestone par milestone, ticket par ticket, dans
l'ordre. Ne pas démarrer un milestone tant que le précédent n'a pas atteint son
"Livrable". M0 est fait. Milestone courant : **M1**.
