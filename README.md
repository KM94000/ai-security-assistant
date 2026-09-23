# 🛡️ AI Security Assistant

Plateforme **RAG + agents** qui repond a des questions de **cybersecurite** a
partir de sources de reference (OWASP, MITRE ATT&CK/ATLAS, CVE, NIST) —
construite comme un **produit de production** et **durcie contre les attaques
propres aux LLM** (sa propre surface d'attaque est traitee comme un cas d'usage).

> Statut : ✅ M3 — l'agent est en place. Le RAG repond : ingestion d'un corpus,
> recherche vectorielle avec seuil de pertinence, `POST /query` sourcee et
> streamee. `POST /agent` laisse le modele choisir ses outils — chercher dans le
> corpus, consulter une CVE dans la base du NIST — sous quatre plafonds imposes
> par le code. Prochaine etape : l'observabilite (M4). La couverture securite
> est suivie ligne a ligne dans [`docs/SECURITY.md`](docs/SECURITY.md),
> colonne Statut.

## ⚡ Essayer

```bash
docker compose -f docker/docker-compose.yml up -d qdrant
ollama serve                                    # dans un autre terminal
python -m aisecassist.ingestion.pipeline data/corpus
uvicorn aisecassist.main:app --reload
```

La documentation interactive est sur <http://localhost:8000/docs>.

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question":"Pourquoi l'"'"'injection indirecte est-elle plus dangereuse dans un RAG ?"}'
```

Et la meme reponse, emise au fil de la generation (`-N` desactive le tampon de
curl, sans quoi tout s'affiche d'un coup a la fin) :

```bash
curl -N -X POST http://localhost:8000/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"Qu'"'"'est-ce que l'"'"'autonomie excessive d'"'"'un agent ?"}'
```

Et la voie de l'agent, qui choisit ses outils au lieu de chercher une fois :

```bash
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"question":"Que decrit la CVE-2021-44228 ?"}'
```

## 💬 A quoi ca ressemble vraiment

Echanges reels, captures le 23 septembre 2026 sur un portable sans carte
graphique — les durees sont celles d'un modele local sur processeur.

### Refuser plutot que supposer

C'est le comportement dont je suis le plus satisfait, et le plus rare dans une
demo de RAG.

```jsonc
POST /query   {"question": "Quelle est la recette traditionnelle du cassoulet ?"}
// 200, 8,3 s
{
  "answer": "Le corpus ne contient aucun extrait pertinent pour cette question.
             Je prefere ne pas repondre plutot que de supposer.",
  "sources": []
}
```

Le modele n'a **pas** ete appele : aucun extrait n'ayant atteint le seuil de
pertinence, la question s'arrete avant lui. Sans ce seuil, la recherche aurait
renvoye ses cinq extraits les moins mauvais et le modele aurait brode
(ADR-0010).

### L'agent choisit ses outils

```jsonc
POST /agent   {"question": "Que decrit la CVE-2021-44228, et a quelle categorie
                            du OWASP LLM Top 10 ce type de faille se rattache-t-il ?"}
// 200, 28,4 s
{
  "answer": "La CVE-2021-44228 est une faille de securite dans le composant Log4j2
             d'Apache, qui permet a un attaquant d'executer du code arbitraire si
             les messages de journalisation contiennent des informations controlees
             par l'attaquant. [...]",
  "sources": ["https://nvd.nist.gov/vuln/detail/CVE-2021-44228"],
  "iterations": 1
}
```

**Ce que cette reponse montre, y compris ses limites.** L'agent a consulte la
base du NIST — la source le prouve — et sa description de la faille en vient.
Mais `iterations: 1` dit qu'il n'a fait **qu'un** tour : la seconde moitie de la
question, le rattachement au OWASP LLM Top 10, il y a repondu de memoire, sans
consulter le corpus. Et sa reponse sur ce point est approximative.

C'est exactement pour cela que `sources` et `iterations` sont renvoyes. Un
lecteur voit ce qui a ete verifie et ce qui ne l'a pas ete, au lieu d'avoir a
faire confiance a un texte assure de lui.

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
| M0 ✅ | Fondations prod : /health, CI, Docker, ADR |
| M1 ✅ | RAG walking skeleton (ingestion → Qdrant → /query) |
| M2 ✅ | Qualite : async, streaming, tests d'integration |
| M3 ✅ | Agent (LangGraph) : le RAG et la base du NIST comme outils |
| **M4** | Observabilite (tracing, tokens, couts) — en cours |
| M5 | Securite : defense injection, guardrails, threat model |
| M6 | Evaluation (RAGAS) & performance |
| M7 | Vitrine : demo, docs, article |

## 📐 Decisions d'architecture
Voir [`docs/adr/`](docs/adr/).

## ⚖️ Ethique
Les attaques de securite sont menees exclusivement sur cette plateforme
(mon propre systeme), a des fins d'apprentissage et de durcissement.
