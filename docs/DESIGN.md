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
| Embeddings | `granite-embedding-107m-multilingual` (384 dim) | multilingue et entraîné pour la recherche, choisi sur mesure contre trois autres modèles (ADR-0010) ; seuil de pertinence à marge étroite, à recalibrer quand le corpus grandira |
| Base vectorielle | Qdrant conteneurisé | vraie base "prod" plutôt qu'un embarqué ; nécessite Docker |
| Orchestration | Docker Compose, pas K8s | plus simple, suffisant en solo ; K8s documenté mais non déployé (ADR-0001) |
| Sécurité | dans le code, pas dans le prompt | plus d'effort d'ingénierie, mais barrières fiables (le prompt est contournable) |
| Sujet | corpus cybersécurité maîtrisé | domaine où l'auteur juge la qualité des réponses ; l'ingénierie reste réutilisable pour tout corpus |

Les décisions structurantes sont tracées comme **ADR** dans `docs/adr/`.

### Stratégie RAG : ce qu'on retient, ce qu'on écarte

Le RAG mis en place est **volontairement simple** — découpage à fenêtre
glissante, embeddings denses, recherche des k plus proches — augmenté de deux
contrôles qui, eux, ne sont pas optionnels : un **seuil de pertinence**, sans
lequel la recherche renvoie toujours k extraits et ne sait jamais dire « le
corpus ne couvre pas cette question », et un **garde-fou d'espace vectoriel**,
qui refuse une collection indexée par un autre modèle (ADR-0010).

Les stratégies avancées ne sont pas adoptées parce qu'elles sont réputées
efficaces, mais quand elles battent cette base **sur notre banc de mesure** :
47 questions, en jeux de calibrage et de contrôle, avec deux critères — écarter
le hors-sujet, et placer le bon passage dans les extraits envoyés au modèle
(MRR@5). C'est ce banc qui a écarté deux modèles d'embeddings pourtant
plausibles (ADR-0010), et il tourne en CI.

| Stratégie | Décision | Raison |
|---|---|---|
| **Agentic RAG** | **M3** | Le RAG devient un outil que l'agent choisit d'appeler. Le seuil en était le prérequis : un outil incapable de répondre « rien » fait boucler l'agent sur des extraits hors sujet. |
| **Découpage sémantique** | Après M3 | Nos extraits coupent en plein mot. Le corpus est structuré en sections : découper dessus est déterministe, sans modèle ni dépendance. |
| **Reranking** (cross-encoder) | M6 | Seule réponse sérieuse à l'angle mort mesuré : 5 questions de sécurité hors corpus sur 10 franchissent le seuil. Coût à mesurer : une étape et de la latence par requête. |
| **Recherche hybride** (dense + BM25) | M6 | Les embeddings denses sont mauvais sur les identifiants exacts, or le produit doit répondre sur des CVE nommées. Qdrant gère les vecteurs creux nativement. |
| **RAG hiérarchique** | M6, après mesure | Chercher petit, transmettre le passage parent. Vise le même défaut que le découpage sémantique : on tranchera sur les chiffres, pas sur les deux. |
| **Graphes de connaissance** | M7, optionnel | MITRE ATLAS *est* un graphe de tactiques et de techniques, mais c'est une base de plus à héberger. À rouvrir si les questions de mise en relation deviennent centrales. |
| **Self-reflective RAG** | M3/M4, sous plafond | L'agent juge sa propre récupération et relance. Utile, à condition d'un plafond d'itérations : sans lui, la boucle devient un déni de service auto-infligé (SEC-06). |
| **Expansion de requête / multi-requête** | Dans l'agent, pas avant | Hors agent, cela place un appel au modèle **avant** la recherche : latence, scores non reproductibles alors que le seuil suppose l'inverse, et une question piégée pourrait orienter la recherche. Dans l'agent, c'est un appel d'outil tracé, aux arguments validés en dur. |
| **Contextual retrieval** | Écarté à ce stade | Faire résumer chaque extrait par un modèle **à l'ingestion** revient à laisser un document hostile rédiger sa propre description pour se faire récupérer plus souvent : un amplificateur d'empoisonnement (SEC-04, SEC-08), en plus du coût. À rouvrir en M5, avec des garde-fous. |
| **Late chunking** | Non applicable | Exige un modèle à très long contexte ; le nôtre plafonne à 512 tokens. |
| **Embeddings fine-tunés** | Non | Demanderait un jeu annoté du domaine, que nous n'avons pas. |

Deux constantes dans ce tri. D'abord, **une stratégie qui insère le modèle avant
ou pendant la récupération ajoute une surface d'injection** : elle n'est
acceptée que dans l'agent, où l'appel est tracé et ses arguments validés par du
code. Ensuite, **à bénéfice comparable, on préfère le déterministe** : un
découpage structurel coûte moins cher et se teste mieux qu'un enrichissement
généré.

### Quand un outil sort de la machine : le cas du NIST

Le corpus ne peut pas tout couvrir. Une question sur une vulnérabilité nommée
appelle une source à jour, ce qu'un corpus figé n'est pas. D'où un second outil,
qui interroge la base publique du NIST (ADR-0012) — et qui change la nature du
problème, puisque c'est le premier à quitter la machine.

**Ce qui a été écarté, et pourquoi.** Un instantané local de la base CVE aurait
supprimé le réseau, le quota et l'intermittence : plusieurs gigaoctets, périmés
en quelques jours, et surtout une façon d'esquiver la question plutôt que d'y
répondre. OSV.dev, plus rapide et sans quota, est centré sur les paquets open
source : moins canonique pour une CVE isolée. Une interface abstraite sur la
source de données, enfin, aurait été une supposition sur un besoin futur : le
client HTTP injectable suffit aux tests, et l'abstraction se posera le jour où
une seconde source existera.

**La règle qui en sort, et qui vaudra pour tout outil futur.** Le modèle choisit
*quoi*, le code choisit *où*. La destination ne doit être dérivable d'aucun
argument — et la preuve attendue n'est pas qu'un argument malformé soit refusé,
mais qu'**aucune requête ne parte**. Corollaire sur les pannes : un tiers
indisponible ne fait pas tomber la requête, mais l'échec remonte formulé jusqu'à
l'utilisateur. Dégrader en silence produirait une réponse assurée sur une
vérification qui n'a pas eu lieu — pire que l'erreur qu'on cherchait à éviter.

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
