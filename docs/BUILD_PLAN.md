# BUILD_PLAN.md — Plan de construction (M0 → M7)

Plan d'exécution détaillé. Chaque milestone : **objectif**, **livrable
vérifiable**, **tickets** (avec critères d'acceptation), **specs par module**,
**sécurité intégrée**. L'agent suit l'ordre et respecte la Definition of Done
(voir `CLAUDE.md` §7). Les IDs de tests sécu (SEC-xx) renvoient à
`docs/SECURITY.md`.

Principe transverse : **walking skeleton** — on fait circuler une tranche fine
de bout en bout tôt, puis on épaissit. M2 est le premier point d'arrêt
présentable (API RAG déployée, testée, CI verte).

---

## M0 — Fondations prod ✅ (fait)

**Livrable :** service `/health` déployable, CI verte, Docker, ADR-0001.
Déjà en place : squelette FastAPI, ruff/black/mypy/pre-commit, `ci.yml`,
Dockerfile + compose, tests. Reste optionnel : déploiement Render.

---

## M1 — RAG walking skeleton

**Objectif :** une question traverse toute la chaîne RAG sur un petit corpus.
**Livrable :** `POST /query` renvoie une réponse fondée sur des documents réels.

| # | Ticket | Critère d'acceptation | Sécu |
|---|---|---|---|
| 8 | Interface `LLMProvider` + `OllamaProvider` | un appel LLM passe par l'abstraction ; testé avec un double | — |
| — | Interface `Embedder` + `SentenceTransformerEmbedder` | `embed(["x"])` renvoie un vecteur de dim 384 ; `dimension == 384` | — |
| 9 | Qdrant dans docker-compose | conteneur `Up`, dashboard `:6333/dashboard` accessible | volume persistant |
| — | Interface `VectorStore` + `QdrantVectorStore` | `ensure_collection(384)` idempotent ; `add` puis `search` renvoie le point inséré | SEC-08 |
| 10 | Pipeline d'ingestion (load→clean→chunk→embed→index) | un doc de test est chunké et indexé ; nb de points cohérent | SEC-04, SEC-13 |
| 11 | Module retrieval (top-k) | une requête renvoie k `SearchResult` triés par score | — |
| 12 | Module génération (prompt + LLM) | réponse construite à partir des chunks récupérés | SEC-07 |
| 13 | Endpoint `POST /query` | question → réponse ; chunks sources renvoyés dans la réponse | SEC-01, SEC-11 |

**Specs modules :**
- **`ingestion`** : `chunk` par fenêtre glissante (taille + overlap en config).
  Chaque chunk garde sa `source`. Fonctions pures, testables sans I/O.
- **`retrieval`** : `retrieve(question, k)` = `embed(question)` → `store.search`.
  `k` par défaut en config.
- **`generation`** : template de prompt EXPLICITE qui **délimite clairement** le
  contexte récupéré des instructions système (voir SEC-01). Ne jamais
  concaténer question + contexte sans séparation structurée.

**Sécurité intégrée M1 :** dès l'ingestion, considérer les documents comme
entrée hostile (SEC-04). Le template de génération doit être conçu pour
résister à l'injection indirecte (SEC-01) — même si le durcissement complet
vient en M5, la structure du prompt est posée maintenant.

---

## M2 — Qualité & robustesse (premier point présentable)

**Objectif :** transformer le skeleton en service robuste et testé.
**Livrable :** API RAG async, streamée, avec tests d'intégration verts en CI.

| # | Ticket | Critère d'acceptation | Sécu |
|---|---|---|---|
| 14 | API async + streaming SSE | la réponse s'affiche token par token | SEC-10 |
| 15 | Schémas pydantic + gestion d'erreurs | entrée invalide → 4xx clair, sans stack trace | SEC-02, SEC-11 |
| 16 | Doc OpenAPI soignée | `/docs` présentable, exemples fournis | — |
| 17 | Tests unitaires (chunking, retrieval, provider) | modules clés couverts | — |
| 18 | Tests d'intégration `/query` | test bout-en-bout vert en CI (Qdrant de test) | SEC-01 (test) |

**Sécurité intégrée M2 :** validation stricte des entrées API (longueur, type,
encodage). Limite de taille de requête (amorce SEC-10). Aucune fuite d'erreur
interne (SEC-11).

---

## M3 — Agent

**Objectif :** un agent qui décide et utilise des outils, dont le RAG.
**Livrable :** `POST /agent` répond à une question complexe via un raisonnement
multi-outils.

| # | Ticket | Critère d'acceptation | Sécu |
|---|---|---|---|
| 19 | Agent LangGraph, RAG exposé comme outil | l'agent choisit d'appeler le RAG quand pertinent | SEC-06 |
| 20 | 1-2 outils supplémentaires (ex. lookup CVE) | l'agent sélectionne le bon outil ; args validés | SEC-05, SEC-06 |
| 21 | Endpoint `POST /agent` | question complexe → réponse multi-étapes tracée | SEC-01, SEC-06 |
| 22 | (option) exposer un outil en MCP | conforme au protocole | SEC-06 |

**Sécurité intégrée M3 (critique) :** chaque outil valide ses arguments **côté
code** (SEC-05). Principe de **moindre privilège** : un outil ne peut faire que
ce pour quoi il est prévu ; aucun outil n'exécute de commande OS ni n'accède au
FS hors périmètre (SEC-06). Les appels d'outils sont tracés (qui, quoi, args).

---

## M4 — Observabilité

**Objectif :** voir ce qui se passe en production.
**Livrable :** chaque requête est traçable, avec coût/latence.

| # | Ticket | Critère d'acceptation | Sécu |
|---|---|---|---|
| 23 | Logs structurés + `request_id` | chaque requête corrélable de bout en bout | SEC-12 |
| 24 | Tracing Langfuse | une requête RAG/agent apparaît dans Langfuse | SEC-12 |
| 25 | Métriques tokens / coût / latence | exposées par requête | SEC-10 |

**Sécurité intégrée M4 :** les logs et traces **ne contiennent jamais** de
secret, de token, ni de contenu sensible brut (SEC-12). Les métriques de
consommation servent aussi de signal d'abus (SEC-10).

---

## M5 — Sécurité (durcissement — le module différenciant)

**Objectif :** durcir la plateforme contre l'OWASP LLM Top 10 et documenter.
**Livrable :** défenses actives + threat model + writeup d'attaques menées sur
la plateforme elle-même.

| # | Ticket | Critère d'acceptation | Test |
|---|---|---|---|
| 26 | Validation stricte des entrées + limites | entrées malveillantes rejetées | SEC-02, SEC-11 |
| 27 | Défense injection directe | prompt d'injection connu neutralisé | SEC-01 |
| 28 | Défense injection **indirecte** (sanitation du contexte récupéré) | doc empoisonné n'altère pas le comportement | SEC-01, SEC-04 |
| 29 | Guardrails de sortie (anti-fuite, filtrage) | fuite de secret/PII bloquée | SEC-02, SEC-03 |
| 30 | Auth API + moindre privilège des outils | accès non autorisé refusé ; outil hors périmètre bloqué | SEC-06, SEC-14 |
| 31 | Scans sécu en CI (bandit, pip-audit, gitleaks) + Dependabot | CI échoue sur vulné/secret/dépendance risquée | SEC-15 |
| 32 | Threat model STRIDE documenté | les 6 catégories couvertes (voir SECURITY.md) | — |
| 33 | Writeup d'attaques + mitigations | document publiable (avant/après) | tous |

**Sécurité intégrée M5 :** c'est LE milestone sécurité. Toutes les défenses des
milestones précédents sont vérifiées par la matrice complète de
`docs/SECURITY.md`. Rien ne compte sur le comportement "poli" du modèle : les
barrières sont dans le code.

---

## M6 — Évaluation & performance

**Objectif :** mesurer la qualité et la performance ("RAG performant").
**Livrable :** métriques RAGAS + benchmarks, présentés dans le README.

| # | Ticket | Critère d'acceptation | Sécu |
|---|---|---|---|
| 34 | Harness RAGAS (faithfulness, context precision) | scores calculés sur un jeu de test | — |
| 35 | Benchmark latence + cache (sémantique si possible) | avant/après mesuré | SEC-10 (cache) |
| 36 | Tableau de résultats dans le README | chiffres présentés proprement | — |

**Note :** M6 est le bon moment pour l'expérience "MiniLM (384) vs mpnet (768)"
— comparer qualité/latence, documenter la décision.

---

## M7 — Vitrine

**Objectif :** rendre le travail lisible et vendeur.
**Livrable :** README final + démo + docs, projet présentable à un recruteur.

| # | Ticket | Critère d'acceptation |
|---|---|---|
| 37 | README final (schéma d'archi + GIF démo + résultats) | lisible en 2 min |
| 38 | ADR complets + CHANGELOG | décisions et historique documentés |
| 39 | (option) Article de conception & de sécurisation | publié |

---

## Points d'arrêt présentables

- **Fin M2** : API RAG déployée, testée, CI verte → déjà une pièce de portfolio.
- **Fin M5** : le différenciateur sécu est en place → candidatures ciblées.
- **Fin M7** : vitrine complète.
