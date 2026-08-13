# 🛡️ AI Security Assistant

Plateforme **RAG + agents** qui repond a des questions de **cybersecurite** a
partir de sources de reference (OWASP, MITRE ATT&CK/ATLAS, CVE, NIST) —
construite comme un **produit de production** et **durcie contre les attaques
propres aux LLM** (sa propre surface d'attaque est traitee comme un cas d'usage).

> Statut : 🚧 M1 — le RAG repond. Ingestion d'un corpus, recherche vectorielle
> et `POST /query` avec reponse sourcee. La couverture securite est suivie
> ligne a ligne dans [`docs/SECURITY.md`](docs/SECURITY.md), colonne Statut.

## ⚡ Essayer

```bash
docker compose -f docker/docker-compose.yml up -d qdrant
ollama serve                                    # dans un autre terminal
python -m aisecassist.ingestion.pipeline data/corpus
uvicorn aisecassist.main:app --reload
```

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question":"Pourquoi l'"'"'injection indirecte est-elle plus dangereuse dans un RAG ?"}'
```

## 🎯 Ce que ce projet demontre
- Architecture RAG + agents pensee pour la production
- Ingenierie logicielle pro : tests, CI/CD, Docker, observabilite, ADR
- Securite IA native : durcissement OWASP LLM Top 10, defense injection

## 🧰 Stack
FastAPI · Ollama (dev) · Qdrant · LangGraph · RAGAS · Langfuse · Docker ·
GitHub Actions · Render/Railway

## 🚀 Demarrer en local
```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pre-commit install
uvicorn aisecassist.main:app --reload
```
Puis : http://localhost:8000/health  et la doc http://localhost:8000/docs

## 🐳 Avec Docker
```bash
docker compose -f docker/docker-compose.yml up --build
```

## ✅ Qualite
```bash
ruff check .      # lint
black --check .   # format
mypy src          # types
pytest            # tests
```

## 🗺️ Feuille de route (milestones)
| M | Contenu |
|---|---|
| **M0** | Fondations prod (ce commit) : /health, CI, Docker, ADR |
| M1 | RAG walking skeleton (ingestion → Qdrant → /query) |
| M2 | Qualite : async, streaming, tests d'integration |
| M3 | Agent (LangGraph) avec le RAG comme outil |
| M4 | Observabilite (tracing, tokens, couts) |
| M5 | Securite : defense injection, guardrails, threat model |
| M6 | Evaluation (RAGAS) & performance |
| M7 | Vitrine : demo, docs, article |

## 📐 Decisions d'architecture
Voir [`docs/adr/`](docs/adr/).

## ⚖️ Ethique
Les attaques de securite sont menees exclusivement sur cette plateforme
(mon propre systeme), a des fins d'apprentissage et de durcissement.
