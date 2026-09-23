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

Echanges reels, captures le 23 septembre 2026. Les durees sont celles du mode
heberge (`LLM_PROVIDER=hosted`) ; le meme code en local sur processeur repond
entre dix et trente fois plus lentement, comparaison chiffree plus bas.

### Refuser plutot que supposer

C'est le comportement dont je suis le plus satisfait, et le plus rare dans une
demo de RAG.

```jsonc
POST /query   {"question": "Quelle est la recette traditionnelle du cassoulet ?"}
// 200, 0,3 s
{
  "answer": "Le corpus ne contient aucun extrait pertinent pour cette question.
             Je prefere ne pas repondre plutot que de supposer.",
  "sources": []
}
```

Le modele n'a **pas** ete appele — d'ou les 0,3 s. Aucun extrait n'ayant atteint
le seuil de pertinence, la question s'arrete avant lui. Sans ce seuil, la
recherche aurait renvoye ses cinq extraits les moins mauvais et le modele aurait
brode (ADR-0010).

### L'agent choisit ses outils, et en enchaine plusieurs

```jsonc
POST /agent   {"question": "Que decrit la CVE-2021-44228, et a quelle categorie
                            du OWASP LLM Top 10 ce type de faille se rattache-t-il ?"}
// 200, 17,4 s
{
  "answer": "**CVE-2021-44228 (Log4Shell)** [...] Un attaquant qui peut controler
             le texte journalise peut injecter une reference JNDI qui declenche une
             recherche d'objet a distance [...] Score CVSS : 10.0 (CRITICAL) [...]",
  "sources": [
    "https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
    "owasp-llm-top10.md"
  ],
  "iterations": 3
}
```

**Deux sources de nature differente** — une base de vulnerabilites interrogee en
direct, et le corpus indexe — dans une seule reponse. C'est ce que l'agent
apporte par rapport a `/query`, qui ne cherche qu'une fois, au meme endroit.

### Ce que ces indicateurs servent a voir

Ils ne sont pas decoratifs : ils servent a reperer ce qui cloche. Ici, la
reponse rattache Log4Shell a la categorie « injection de prompt » du OWASP LLM
Top 10 — **ce qui est faux**. Log4Shell est une execution de code a distance
classique, sans rapport avec un LLM.

La partie verifiee est juste, parce qu'elle vient du NIST. L'analogie, elle, est
une construction du modele. Un lecteur qui voit `sources` et `iterations` peut
faire cette distinction ; devant un texte assure de lui et sans provenance, il ne
le pourrait pas.

C'est aussi la raison d'etre du jalon M6 : mesurer la fidelite des reponses aux
sources, au lieu de la supposer.

### Le meme code, deux fournisseurs

Le basculement se fait par une variable d'environnement (ADR-0013) ; aucun module
metier ne change.

| Requete | Local (`llama3.1`, CPU) | Heberge (`gpt-oss-120b`) |
|---|---|---|
| `/query` — question de fond | 97,8 s | **3,4 s** |
| `/agent` — question croisant deux sources | 28,4 s, 1 tour | **17,4 s, 3 tours** |
| `/query` — hors corpus (refus) | 8,3 s | 0,3 s |

La ligne de l'agent est la plus parlante : **trois fois plus de travail en 40 %
de temps en moins.** Le modele local s'arretait au premier outil et repondait de
memoire pour le reste.

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
