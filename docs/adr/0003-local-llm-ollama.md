# ADR-0003 : LLM local (Ollama) en développement, swappable en production

- Statut : accepté
- Date : 2026-08-05

## Contexte
Le développement implique de nombreux appels LLM (tests, itérations). Un outil
de cybersécurité manipule aussi des données qu'on préfère ne pas externaliser.
Budget contraint (projet étudiant).

## Décision
Utiliser Ollama (`llama3.1`) en local pour le développement, derrière l'interface
`LLMProvider` (voir ADR-0002), permettant de basculer vers une API
(OpenAI/Azure) en production sans modifier le code métier.

## Alternatives envisagées
- **API LLM directe (OpenAI/Anthropic)** : meilleure qualité de génération, mais
  coût par appel (chaque test facturé) et données envoyées à un tiers. Écarté en
  dev, réservé à une éventuelle prod.
- **Auto-hébergement d'un grand modèle** : coûteux en matériel/GPU, hors budget.
  Écarté.

## Conséquences
- (+) Développement gratuit, illimité, et données conservées en local (argument
  de sécurité pour un outil cyber).
- (−) Qualité de génération inférieure à une API haut de gamme — neutralisée par
  l'abstraction `LLMProvider` : bascule possible vers une API le jour où la
  qualité prime, sans refonte.
