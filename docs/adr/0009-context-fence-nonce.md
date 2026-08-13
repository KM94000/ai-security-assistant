# ADR-0009 : Délimitation du contexte par nonce généré côté serveur

- Statut : accepté
- Date : 2026-08-12

## Contexte

Dans un RAG, le contexte injecté dans le prompt provient du corpus, c'est-à-dire
d'une entrée hostile différée (`SECURITY.md`, frontière 5). Un document
empoisonné n'agit pas à l'ingestion mais au moment où il est récupéré, souvent
bien plus tard et pour un autre utilisateur.

Le risque concret est qu'un extrait se fasse passer pour une instruction
système. Si le contexte est délimité par un marqueur fixe — `---CONTEXTE---`,
`<context>`, ou tout autre motif figé dans le code — un attaquant qui lit le
dépôt, ou qui devine la convention, écrit ce marqueur dans son document. Le
prompt assemblé contient alors une clôture prématurée, et le texte qui suit se
retrouve, structurellement, au même niveau que les instructions.

La question s'est posée au ticket 12, qui construit le prompt.

## Décision

Délimiter le contexte **et** la question par des marqueurs contenant un **nonce
aléatoire généré côté serveur à chaque requête** :

```
===CONTEXTE-<nonce>===   …   ===CONTEXTE-<nonce>===
===QUESTION-<nonce>===   …   ===QUESTION-<nonce>===
```

Le nonce fait 16 octets (`secrets.token_hex(16)`, 32 caractères hexadécimaux).
Un document écrit avant la requête ne peut pas connaître cette valeur, ni la
trouver par force brute dans le temps d'une requête.

Deux règles complètent le dispositif :

1. **Neutralisation par forme.** Tout ce qui ressemble à un délimiteur est
   retiré du contenu avant assemblage, quelle que soit la valeur du nonce. Le
   nonce réel étant imprévisible, cette règle ne devrait jamais rien attraper —
   c'est précisément pour cela qu'elle est là : elle ne coûte rien et couvre le
   cas où la génération du nonce serait affaiblie un jour par erreur.
2. **Les instructions ne citent que le préfixe** du marqueur, jamais sa valeur
   complète. Sinon le marqueur apparaîtrait trois fois dans le prompt et la
   première occurrence ne serait plus l'ouverture du bloc.

## Alternatives envisagées

- **Marqueur fixe en dur.** Écarté : il est dans le dépôt, donc connu. C'est le
  cas d'usage exact de l'attaque.
- **Échapper les marqueurs dans le contenu** (comme on échappe du HTML).
  Écarté comme mécanisme *principal* : il faut alors énumérer toutes les
  variantes d'écriture du marqueur — espaces, casse, caractères unicode
  ressemblants — et cette énumération est toujours incomplète. La règle est
  conservée en défense secondaire, pas en défense unique.
- **Message système structuré du fournisseur** (rôle `system` distinct du rôle
  `user`). Écarté à ce stade : la séparation par rôles varie d'un fournisseur à
  l'autre et n'est pas disponible de façon uniforme derrière `LLMProvider`. Elle
  sera combinée à la clôture, pas substituée, quand `OpenAIProvider` arrivera.

## Conséquences

- (+) Un extrait ne peut pas sortir du bloc de contexte. La propriété est
  **déterministe** et vérifiable par lecture du prompt assemblé, sans faire
  tourner de modèle — d'où des tests rapides et fiables.
- (+) La question de l'utilisateur bénéficie de la même clôture, ce qui couvre
  aussi le volet structurel de l'injection directe.
- (−) **Cette ADR ne garantit pas que le modèle obéit.** Elle empêche la
  confusion structurelle, pas la persuasion. Un prompt système reste
  contournable (ADR-0007), et la résistance comportementale se mesure en M5,
  avec SEC-01 et SEC-01b contre un vrai modèle. Confondre les deux reviendrait à
  déclarer la menace traitée alors que la moitié la plus difficile reste entière.
- (−) Le prompt est un peu plus verbeux : deux marqueurs de 45 caractères par
  bloc. Négligeable au regard du budget de contexte.
