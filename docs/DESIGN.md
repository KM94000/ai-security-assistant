# DESIGN.md — Document de conception (design doc)

> Ce document présente la conception du produit **avant** son implémentation,
> comme le ferait une équipe d'ingénierie avant de lancer un projet en
> production : problème, utilisateurs, objectifs, décisions d'architecture et
> leurs compromis, sécurité, et critères de succès. Il sert de contexte partagé
> et de trace de la démarche.

---

## 1. Problème

La connaissance en cybersécurité est vaste et éparpillée : OWASP, MITRE
ATT&CK/ATLAS, bases CVE/NVD, guidelines NIST, politiques internes, retours
d'incidents. Un analyste SOC ou un ingénieur AppSec perd un temps considérable à
retrouver l'information fiable au bon moment (« ce pattern est-il vulnérable ? »,
« comment mitiger cette technique ? »).

Un LLM seul ne résout pas ce problème : il **hallucine** sur les points précis et
ne connaît pas les sources à jour. Il faut un système qui **fonde ses réponses
sur des sources de référence** — et, s'agissant d'un outil de sécurité,
lui-même **résistant aux attaques**.

## 2. Utilisateurs & cas d'usage

- **Analyste SOC N1** : trier une alerte, la relier à une technique
  ATT&CK/ATLAS, obtenir une reco de réponse sourcée.
- **Ingénieur AppSec / développeur** : vérifier un point de sécurité, comprendre
  une classe de vulnérabilité et sa mitigation.

Requête type : « Quelle est la mitigation recommandée pour une injection de
commande OS ? » → réponse sourcée + éventuellement un outil (lookup CVE, mapping
ATT&CK).

## 3. Objectifs / Non-objectifs

**Objectifs**
- Réponses de cybersécurité **fondées et sourcées** (RAG sur corpus de référence).
- Capacités **agentiques** (outils : recherche, lookup CVE, mapping ATT&CK).
- **Qualité de production** : API, tests, CI/CD, conteneurisation, observabilité,
  déploiement réel.
- **Sécurité native** : durcissement OWASP LLM Top 10, la propre surface
  d'attaque du produit étant traitée comme un cas d'usage.

**Non-objectifs (assumés)**
- Pas de fine-tuning (coût/complexité disproportionnés ; le RAG couvre le besoin).
- Pas de Kubernetes ni de microservices (monolithe conteneurisé suffisant en solo).
- Pas de couverture exhaustive de tout le corpus mondial : un corpus ciblé et
  maîtrisé, gage de qualité mesurable.

## 4. Vue d'ensemble de l'architecture

Chaîne RAG classique (ingestion → base vectorielle → retrieval → génération),
exposée en API, étendue par une couche agentique (le RAG devient un outil parmi
d'autres), le tout enveloppé d'observabilité et de contrôles de sécurité.
Schéma et détails : `CLAUDE.md` §4, specs par module `docs/BUILD_PLAN.md`.

## 5. Décisions de conception clés & compromis

| Décision | Choix | Compromis assumé |
|---|---|---|
| Découplage | Interfaces `LLMProvider` / `VectorStore` / `Embedder` | un peu plus de code, mais liberté de swap et testabilité (inversion de dépendance) |
| LLM en dev | Ollama local | gratuit et privé, au prix d'une qualité moindre que les API — sans impact grâce à l'abstraction |
| Embeddings | `all-MiniLM-L6-v2` (384 dim) | léger/rapide ; qualité supérieure possible (mpnet 768) évaluée en M6 |
| Base vectorielle | Qdrant conteneurisé | vraie base "prod" plutôt qu'un embarqué ; nécessite Docker |
| Orchestration | Docker Compose, pas K8s | plus simple, suffisant en solo ; K8s documenté mais non déployé (ADR-0001) |
| Sécurité | dans le code, pas dans le prompt | plus d'effort d'ingénierie, mais barrières fiables (le prompt est contournable) |
| Sujet | corpus cybersécurité maîtrisé | domaine où l'auteur juge la qualité des réponses ; l'ingénierie reste réutilisable pour tout corpus |

Les décisions structurantes sont tracées comme **ADR** dans `docs/adr/`.

## 6. Sécurité — approche

Le produit est un outil de sécurité : sa crédibilité dépend de sa propre
robustesse. L'approche est « sécurité par conception » — la surface d'attaque
(injection directe/indirecte, excessive agency, fuite du prompt système,
faiblesses vecteurs/embeddings) est modélisée dès la conception, et chaque
module embarque ses contrôles. Le threat model complet (STRIDE + OWASP LLM Top
10 2025) et la matrice de tests sont dans `docs/SECURITY.md`. Principe directeur :
**aucune sécurité déléguée au modèle** ; les barrières sont dans le code et
vérifiées par des tests automatisés + du red teaming (promptfoo/garak).

## 7. Plan de livraison (milestones)

Approche incrémentale « walking skeleton » : une tranche fine déployée tôt, puis
épaississement. M0 (fondations) → M1 (RAG) → M2 (qualité, **1er point
présentable**) → M3 (agent) → M4 (observabilité) → M5 (**sécurité**, le
différenciateur) → M6 (évaluation/perf) → M7 (vitrine). Détail :
`docs/BUILD_PLAN.md`.

## 8. Critères de succès

- **Fonctionnel** : `/query` et `/agent` répondent, sourcé, déployé et accessible.
- **Qualité** : CI verte, tests unitaires + intégration, types stricts.
- **Performance** : métriques RAGAS (faithfulness, context precision) mesurées ;
  latence benchmarkée (M6).
- **Sécurité** : matrice de tests P0 passée, threat model documenté, writeup
  d'attaques/mitigations publié.
- **Process** : historique de PRs avec CI verte, ADR à jour — démonstration
  d'une démarche d'équipe.

## 9. Méthode de travail

Chaque incrément suit le cycle **issue → branche → PR → CI verte → merge**, avec
Definition of Done (code + tests + types + doc + sécu). Les choix d'architecture
sont documentés en ADR au fil de l'eau. Objectif : que le dépôt raconte, à lui
seul, une conception et une exécution de niveau professionnel.
