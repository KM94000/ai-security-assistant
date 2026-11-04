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

---

## Réévaluation du 2026-11-04 — le découpage faisait le seuil (ticket 41)

**Déclencheur.** Le corpus est passé de 10 443 à 30 396 caractères pour qu'une
démonstration ne bute plus sur la première question spontanée. Le calibrage
s'est effondré : écart **+0,060 → +0,000**. Plus aucun seuil ne séparait.

**Diagnostic.** Pas le corpus — le **découpage**. La fenêtre glissante coupait
au milieu des mots et produisait des fragments à cheval sur deux sections, donc
des moyennes sémantiques de deux sujets. Une moyenne se place près du centre de
l'espace vectoriel, c'est-à-dire près de n'importe quel texte générique. La
salutation « Bonjour, comment vas-tu ? » atteignait **0,651**, au-dessus de la
plus faible question couverte — en s'accrochant à un extrait sur l'élévation de
privilèges, sans le moindre rapport sémantique.

C'est l'avertissement du docstring de `chunker.py`, écrit au ticket 10, qui se
réalise : *« un mauvais découpage ne plante pas, il dégrade silencieusement la
pertinence »*. Le défaut était invisible à 16 fragments ; il est devenu bloquant
à 50.

### Six stratégies mesurées, mêmes 47 questions

| Stratégie | frags | moy. couverte | écart |
|---|---|---|---|
| fenêtre glissante 800/120 (en place) | 50 | 0,728 | **+0,000** |
| phrases seules, sans sections | 49 | 0,734 | **−0,021** |
| sections nues | 57 | **0,763** | −0,001 |
| sections + titre du document | 57 | 0,736 | **+0,025** |
| sections courtes + titre | 75 | 0,735 | +0,020 |
| *small-to-big* (indexer petit, rendre grand) | 132 | **0,742** | **+0,029** |

Deux effets distincts, et il faut les deux. **Découper par section** améliore la
recherche (0,728 → 0,763) : un fragment est alors un sujet, pas une moyenne.
**Préfixer du titre du document** crée la séparation (meilleure hors-sujet
0,651 → 0,609) : chaque fragment commence par un texte fortement marqué, ce qui
éloigne tout le corpus du français générique.

« Phrases seules » le prouve a contrario : supprimer les coupes au milieu des
mots **sans** respecter les sections dégrade l'écart. C'est la pureté
thématique qui compte, pas la propreté typographique.

### Décision

`chunk_document` : une section de niveau 2 est une unité, préfixée du titre du
document, coupée sur des frontières de phrase seulement si elle déborde.
`chunk_text` reste, comme repli pour les documents sans structure.

Mesuré sur l'implémentation réelle : écart de calibrage **+0,066**, soit
davantage que les +0,060 du corpus d'origine — **trois fois plus de contenu, et
une séparation meilleure qu'elle ne l'a jamais été**.

Le *small-to-big* est écarté **de cette étape seulement** : il exige que le
texte indexé diffère du texte rendu, donc un changement de payload et une
déduplication des parents au retrieval. Il fait l'objet d'un ticket distinct.

**Taille de fragment inchangée à 800.** Mesurée à 800, 1 100 et 1 400 : moyenne
des questions couvertes de 0,734 à 0,736, écarts indiscernables du bruit sur
47 questions. Faute de preuve, on ne touche pas.

### Le seuil : 0,64 → 0,63, et pourquoi pas 0,65

La règle du milieu appliquée au **calibrage seul** donne 0,65. Le jeu de
contrôle d'origine montre qu'à 0,65 une question légitime est refusée : *« Pourquoi
des messages d'erreur trop détaillés aident-ils un attaquant ? »*, à 0,635.

**0,63 est la valeur qui ne commet aucune erreur sur les 67 questions** des
trois jeux.

L'écart entre 0,65 et 0,63 n'est pas un défaut de seuil mais une **lacune de
corpus** : le sujet des messages d'erreur bavards n'est couvert que par une
incise dans deux documents, jamais traité par une section. C'est consigné ici
plutôt que corrigé — corriger le corpus en réponse à une question de contrôle
reviendrait à enseigner au test.

### Un jeu de contrôle étendu, et pourquoi

Avoir consulté le contrôle d'origine pour constater ce conflit le rapproche d'un
jeu de calibrage. La règle du module impose alors d'en écrire un nouveau :
**10 questions couvertes et 10 hors-sujet, rédigées avant toute mesure et
mesurées une seule fois.** Résultat : **zéro erreur à 0,62, 0,63, 0,64 et 0,65**.

Deux précisions sur sa composition. Il couvre la sécurité web et MITRE ATT&CK,
absents du corpus quand le contrôle d'origine a été écrit — celui-ci ne
vérifiait donc plus la moitié de ce que le système prétend savoir. Et il
**conserve une salutation** (« Salut, tu vas bien ? », mesurée à 0,603) :
écarter le cas qui avait fait échouer la séparation, parce qu'il était
difficile, aurait été déplacer le poteau de but.

Aucune question n'a été retirée d'aucun jeu.

### Conséquences

- (+) Corpus trois fois plus grand, séparation meilleure qu'à l'origine.
- (+) Les fragments ne commencent plus au milieu d'un mot : ce qui est cité à
  l'utilisateur comme source est désormais lisible.
- (−) La réserve de l'ADR tient toujours, et s'alourdit : **67 questions sur un
  corpus, des écarts de l'ordre de 0,02 à 0,07.** Un indicateur, pas un banc
  d'essai. Le signe est constant sur six stratégies et le mécanisme s'explique,
  mais on ne survendra pas trois centièmes.
- (−) Le découpage devient un **troisième** paramètre dont dépend le seuil, à
  côté du modèle et de sa révision. Le test de calibrage le dit désormais.
