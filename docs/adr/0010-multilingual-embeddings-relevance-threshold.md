# ADR-0010 : Embeddings multilingues et seuil de pertinence du retrieval

- Statut : accepté
- Date : 2026-09-17
- Remplace : ADR-0006

## Contexte

La recherche top-k renvoyait toujours ses k extraits, même pour une question
sans aucun rapport avec le corpus. Le refus prévu par la génération (« le corpus
ne contient aucun extrait pertinent ») ne se déclenchait donc jamais : le modèle
était interrogé avec un contexte hors sujet. L'agent de M3, qui consommera le
retrieval comme un outil, n'aurait eu aucun moyen d'apprendre qu'il n'y a rien.

La correction attendue — un score minimal — s'est heurtée au modèle
d'embeddings. `all-MiniLM-L6-v2` (ADR-0006) est un modèle anglais, alors que le
corpus et les questions sont en français. Sur six phrases sans rapport entre
elles, il mesure une similarité moyenne de **0,42 en français contre 0,07 en
anglais** : il encode la langue plus fort que le sens. Chaque score part d'un
plancher, et le sujet n'ajoute que quelques centièmes.

### Méthode

Corpus réel (`data/corpus`, 16 extraits de 800 caractères), 47 questions en
deux jeux :

- **calibrage** (17 couvertes, dont 2 en anglais ; 10 hors sujet) : sert à
  choisir le seuil, au milieu entre le pire score couvert et le meilleur score
  hors sujet ;
- **contrôle** (10 + 10) : écrit avant de connaître les scores, il ne sert qu'à
  compter les erreurs du seuil ainsi choisi.

Deux critères, parce qu'un modèle peut réussir l'un et échouer l'autre :

- **séparation** : le score du meilleur extrait sépare-t-il les questions
  couvertes des questions hors sujet ?
- **classement** : le passage qui répond, repéré par une phrase-témoin tirée du
  corpus, figure-t-il parmi les 5 extraits envoyés au modèle ? Mesuré en MRR@5
  sur les 27 questions couvertes (1 si toujours premier, 0 si jamais dans le
  top 5).

### Résultats

| Modèle (extraits) | Écart au calibrage | Contrôle au seuil | 1ᵉʳ | Top 3 | Top 5 | MRR@5 |
|---|---|---|---|---|---|---|
| all-MiniLM-L6-v2 (800) | −0,10, chevauchement | — | 15 | 18 | 21 | 0,63 |
| paraphrase-multilingual-MiniLM-L12-v2 (400) | +0,27 | 0 erreur à 0,31 | 10 | 18 | 20 | 0,53 |
| multilingual-e5-small (800) | −0,03, chevauchement | — | 15 | 24 | 25 | 0,70 |
| **granite-embedding-107m-multilingual (800)** | **+0,06** | **0 erreur à 0,64** | **17** | **24** | **25** | **0,77** |

Filtrer extrait par extrait plutôt que sur le seul meilleur score ne change pas
le classement de granite (MRR identique) et retire en moyenne un extrait hors
sujet sur cinq.

## Décision

1. **Modèle** : `ibm-granite/granite-embedding-107m-multilingual`, 384
   dimensions, fenêtre de 512 tokens (215 tokens au plus pour nos extraits,
   aucune troncature). Poids en safetensors, aucun code distant à exécuter,
   licence Apache 2.0, ~220 Mo. **Révision épinglée** : `d6cffd33…`.
2. **Seuil** : `retrieval_min_score = 0.64`, appliqué extrait par extrait dans
   `RetrievalService`. Une liste vide signifie « le corpus ne couvre pas la
   question ».
3. **Garde-fou d'espace vectoriel** : le store inscrit `modèle@révision` dans
   les métadonnées de la collection qu'il crée, et refuse de lire ou d'écrire
   dans une collection qui en déclare un autre, ou aucun. Le contrôle de
   dimension ne suffisait plus : l'ancien et le nouveau modèle ont tous deux 384
   dimensions, et une collection indexée par l'un aurait répondu au hasard aux
   requêtes de l'autre, sans erreur.
4. **Calibrage rejoué en CI** : `tests/integration/test_retrieval_relevance.py`
   vérifie les 47 questions contre le vrai Qdrant. En cas d'échec, il affiche
   chaque score et le seuil que donnerait la règle.

## Alternatives envisagées

- **Garder MiniLM-L6 avec un seuil** : aucun seuil ne sépare. Un seuil calé sur
  les questions de test aurait été calé sur le test censé le vérifier.
- **paraphrase-multilingual-MiniLM-L12-v2** : sépare nettement, mais classe
  moins bien que le modèle actuel. Il est entraîné à rapprocher deux phrases qui
  disent la même chose, pas une question du passage qui y répond : la
  remédiation OWASP à l'injection indirecte sortait du top 5. Sa fenêtre de 128
  tokens imposait en outre de couper les extraits à 400 caractères.
- **multilingual-e5-small** : bon classement, mais des scores tassés entre 0,80
  et 0,84 pour toutes les questions ; aucun seuil possible. Il exige aussi des
  préfixes `query:` / `passage:`, donc une interface `Embedder` asymétrique.
- **Traduire la question en anglais avant vectorisation** : même avec une
  traduction parfaite faite à la main, chevauchement (−0,05) et classement
  dégradé (MRR 0,56), le corpus restant en français. Traduire aussi le corpus
  ajouterait un appel au modèle par question — latence, scores non
  reproductibles — et placerait le LLM **avant** le retrieval, où une question
  piégée pourrait orienter la recherche.
- **Reranker multilingue** (cross-encoder) : traiterait classement et
  pertinence ensemble, au prix d'une étape, d'une interface et d'une latence de
  plus. Reporté en M6, où RAGAS permettra de le mesurer sur un jeu plus large.

## Conséquences

- (+) Le retrieval sait dire « je n'ai rien » : une question hors sujet reçoit
  le refus explicite, sans appel au modèle. Vérifié de bout en bout en CI.
- (+) Meilleur classement sur le jeu mesuré (MRR 0,63 → 0,77), et les questions
  en anglais sont servies par le corpus français.
- (+) Poids épinglés : une mise à jour du dépôt ne peut plus déplacer les scores
  en silence. C'est aussi une protection de la chaîne d'approvisionnement
  (LLM03).
- (−) **Marge étroite** : 0,652 pour la pire question couverte, 0,613 pour la
  meilleure hors sujet, tous jeux confondus. Des erreurs sont attendues sur des
  formulations inédites, dans les deux sens. À 0,64, le refus à tort est le plus
  proche, et c'est assumé : mieux vaut refuser que supposer (LLM09).
- (−) Le seuil sépare le pertinent du hors-sujet, **pas le couvert du non
  couvert**. Cinq questions de sécurité absentes du corpus sur dix le franchissent
  (injection SQL, rançongiciel, DDoS…). Pour elles, le modèle reste le dernier
  filtre, ce qui n'est pas une garantie.
- (−) Ce n'est **pas un contrôle de sécurité** : un document conçu pour
  ressembler aux questions courantes franchit le seuil par construction
  (SEC-08).
- (−) 47 questions sur 16 extraits : un indicateur, pas un benchmark. Le seuil
  est à recalibrer quand le corpus grandira, car plus il y a d'extraits, plus une
  question hors sujet a de chances de trouver un voisin proche.
- (−) Toute collection existante doit être recréée puis ré-ingérée ; le
  garde-fou le signale au premier accès.
- (−) Modèle plus lourd (~220 Mo contre ~90) et vectorisation d'une question
  plus lente (~18 ms contre ~11), négligeable devant la génération.
- Écart assumé au BUILD_PLAN, qui plaçait la comparaison de modèles en M6 : elle
  est avancée parce que l'agent de M3 dépend d'un retrieval capable de dire
  « rien ».
