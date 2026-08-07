# ARCHITECTURE.md — Architecture du produit

> Formalise l'architecture de l'AI Security Assistant en trois couches :
> **runtime** (le voyage d'une requête), **composants** (qui fait quoi), et
> **workflow de développement** (le voyage du code). À lire avec `CLAUDE.md`
> (règles), `docs/BUILD_PLAN.md` (plan), `docs/SECURITY.md` (menaces),
> `docs/DESIGN.md` (conception).

Principes directeurs :
1. **Pipeline à responsabilité unique** — une requête traverse des étapes
   indépendantes ; chaque composant fait UNE chose.
2. **Découplage par interfaces** — la logique dépend d'abstractions
   (`LLMProvider`, `VectorStore`, `Embedder`), jamais d'implémentations.
3. **Défense en profondeur** — la sécurité est distribuée à chaque frontière,
   pas concentrée en un point.
4. **API mince** — les routes valident/délèguent/formatent ; aucune logique
   métier dans les routes.

---

## Couche 1 — Runtime : le voyage d'une requête

Flux `/query` (RAG), pour une question comme « Comment mitiger une injection
de commande OS ? ». Neuf actions, quatre points de sécurité (🔐).

| # | Action | Composant | Sécurité |
|---|---|---|---|
| 1 | Réception + validation (forme, authz) + `request_id` | API | 🔐 SEC-11, SEC-14 |
| 2 | Question → vecteur (384 dim) | Embedder | — |
| 3 | Recherche top-k des chunks | VectorStore → Qdrant | — |
| 4 | Sanitation du contexte récupéré | Security | 🔐 SEC-01b, SEC-04 |
| 5 | Assemblage du prompt `[système][contexte][question]` séparés | Generation | 🔐 SEC-01 |
| 6 | Génération token par token | LLMProvider | — |
| 7 | Guardrails de sortie (anti-fuite) sur le flux | Security | 🔐 SEC-02, SEC-03 |
| 8 | Réponse en streaming SSE + sources citées | API | — |
| 9 | Log métriques (tokens, latence, coût) sans données sensibles | Observability | 🔐 SEC-12 |

```
question → [valider] → [vectoriser] → [chercher] → [sécuriser contexte]
         → [assembler prompt] → [générer] → [filtrer sortie] → [streamer] → [logger]
```

**Points clés :**
- Le LLM n'intervient qu'à l'action 6 ; tout le reste est du code maîtrisé.
- Le moment le plus sensible est 4→5 : des **données externes** (chunks,
  potentiellement empoisonnés) rencontrent l'**instruction**. La séparation
  stricte du prompt (action 5) est la barrière anti-injection indirecte.
- Le streaming impose des guardrails **sur le flux**, pas sur un texte fini.

### Variante `/agent` (M3)

Entre l'action 1 et le retrieval s'intercale une **décision** : l'agent
(LangGraph) choisit quels outils appeler.

```
API → Agent ─┬─▶ outil RAG (le flux ci-dessus)
             ├─▶ outil lookup CVE      (lecture seule)
             └─▶ outil mapping ATT&CK  (lecture seule)
             ▼
        synthèse → guardrails → réponse
```

🔐 Chaque outil valide ses arguments **en dur** (SEC-05) et respecte le moindre
privilège (SEC-06). **Lecture seule** : aucun effet de bord destructif.

---

## Couche 2 — Composants et frontières

Chaque composant sert un objectif produit explicite.

| Objectif produit | Composant(s) |
|---|---|
| Répondre sourcé | Retrieval + Generation |
| Ne pas halluciner | Generation (prompt contraint) + Éval (mesure) |
| Agir / croiser (lecture seule) | Agent + outils |
| Être sécurisé | Security (transverse) |
| Vrai service | API |
| Observable | Observability (transverse) |

```
                      ┌─────────────┐
     Utilisateur ────▶│    API      │  porte mince : valide, authz, trace, délègue
                      └──────┬──────┘
              ┌──────────────┼──────────────┐
              ▼                             ▼
        Service RAG (/query)         Service Agent (/agent)
              │                             │ décide des outils
        ┌─────┼─────┐               ┌───────┼────────┐
        ▼     ▼     ▼               ▼       ▼        ▼
   Retrieval Génér. Security   outil RAG  CVE   ATT&CK (lecture seule)
        │     │
   via interfaces
        ▼     ▼
   Embedder  LLMProvider          Observability ◀── enveloppe TOUT (transverse)
        │    (Ollama→OpenAI)
        ▼
   VectorStore ──▶ Qdrant
```

### Règles de frontière (responsabilité unique)
- `Retrieval` cherche, **n'appelle pas** le LLM.
- `Generation` génère, **ne cherche pas**.
- `Embedder` fabrique des vecteurs, **ne parle pas** à Qdrant.
- `VectorStore` stocke/cherche, **ne fabrique pas** d'embeddings.
- `API` ne contient **aucune** logique métier.
- `Security` et `Observability` sont **transverses**, pas des étapes traversées.

### Interfaces (contrats)
- `LLMProvider` : `complete(prompt)`, `stream(prompt)`. Impl : Ollama (dev),
  OpenAI/Azure (prod).
- `VectorStore` : `ensure_collection(dimension)`, `add(texts, vectors, sources)`,
  `search(query_vector, k) -> list[SearchResult]`. Impl : Qdrant.
- `Embedder` : `embed(texts) -> vectors`, `dimension`. Impl : MiniLM (384).
- `SearchResult` : dataclass `{text, source, score}`.

### Validation d'entrée — trois niveaux (défense en profondeur)
| Niveau | Responsable | Teste | Échec |
|---|---|---|---|
| 1. Forme | pydantic (auto) | types, structure | 422 |
| 2. Règles | field_validator / service | limites, cohérence (taille…) | 400 |
| 3. Sécurité | module `security` | intention hostile (injection) | rejet/log |

Toujours **côté serveur** ; ne jamais faire confiance à une validation client.

---

## Couche 3 — Workflow de développement (CI/CD)

Le voyage d'un changement de code, du ticket à la production.

```
1. TICKET (issue GitHub + critère d'acceptation)
2. BRANCHE  feature/<n>-slug   (main reste déployable)
3. DEV local
     ├─ pre-commit : ruff + black + gitleaks   🔐 garde-fou LOCAL
     └─ local : ruff / black / mypy / pytest
4. PUSH + PULL REQUEST
5. CI (GitHub Actions)   🤖 garde-fou CENTRAL (source de vérité)
     ├─ ruff, black, mypy, pytest
     └─ bandit + pip-audit + gitleaks          🔐 DevSecOps
        ❌ rouge → corriger → repush ; ✅ vert → mergeable
6. REVIEW + MERGE (Definition of Done cochée) → branche supprimée
7. CD : Render détecte main → rebuild image Docker → redéploie
8. VÉRIFICATION : /health répond, feature live
```

**Distinctions clés :**
- **CI** (vérifier le code) ≠ **CD** (déployer automatiquement).
- **Deux garde-fous** : pre-commit (local, rapide) + CI (central, exhaustif).
- **Sécurité dans le pipeline** : bandit (code), pip-audit (deps), gitleaks
  (secrets) — un code vulnérable ne peut pas atteindre `main`.

**Cadence :** une issue → une branche → une PR → CI verte → merge. Grouper
2-3 petits tickets liés dans une même PR est acceptable ; l'important est un
workflow visible et cohérent (signal de maturité pour un recruteur), pas une PR
par ticket de façon dogmatique.

---

## Synthèse

- **Runtime** : pipeline de 9 étapes, sécurité distribuée (défense en profondeur).
- **Composants** : API mince + composants à responsabilité unique + interfaces
  qui isolent les choix techniques.
- **Workflow** : ticket → branche → CI/CD, sécurité automatisée à chaque PR.

L'ensemble vise un dépôt qui, à lui seul, démontre une conception et une
exécution de niveau professionnel.
