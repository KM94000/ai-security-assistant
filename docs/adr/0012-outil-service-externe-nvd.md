# ADR-0012 : Un outil d'agent qui appelle un service externe — le NIST

- Statut : accepté
- Date : 2026-09-23

## Contexte

Le ticket 20 ajoute un second outil à l'agent : la consultation d'une CVE. Cela
répond d'abord à un besoin fonctionnel — le critère d'acceptation de M3 est que
l'agent *choisisse* le bon outil, ce qui n'a aucun sens avec un seul.

Mais l'enjeu est ailleurs. Jusqu'ici, tous les outils restaient sur la machine :
la recherche dans le corpus lit une base vectorielle locale. `docs/SECURITY.md`
l'écrivait déjà à propos de SEC-05 : *« la surface réelle arrivera avec l'outil
de lookup CVE, qui appellera un service externe »*.

Trois questions se posent alors, qui ne se posaient pas avant :

1. **Quelle source**, et à quel degré de confiance ?
2. **Qui choisit la destination** de l'appel — le code, ou le modèle ?
3. **Que se passe-t-il** quand le tiers est lent, indisponible, ou refuse ?

## Décision

**1. La base du NIST (NVD), via son API publique 2.0.** Source officielle,
gratuite, sans authentification obligatoire, et déjà nommée dans le périmètre du
produit. C'est la référence canonique pour une CVE.

**2. Le modèle choisit *quelle* CVE, jamais *où* la chercher.** L'hôte et le
chemin viennent de la configuration. Le modèle ne fournit qu'un identifiant,
soumis à trois contrôles avant tout appel :

- une expression régulière ancrée aux deux extrémités, `^CVE-\d{4}-\d{4,7}$` ;
- une transmission comme **paramètre de requête**, encodé par le client HTTP,
  jamais concaténé dans une URL ;
- un schéma pydantic `extra="forbid"`, pour qu'aucun paramètre clandestin
  n'atteigne le service.

La propriété qui compte est vérifiée en tant que telle : les tests SEC-05
n'assertent pas seulement que l'appel est refusé, mais qu'**aucune requête n'est
émise**. C'est cela, et cela seul, qui interdit à un modèle détourné de se
servir du serveur pour joindre un tiers (SSRF).

**3. Une panne du tiers n'est pas une panne du produit.** Délai dépassé, HTTP
5xx, JSON illisible, quota refusé : chacun devient une **observation rendue au
modèle**, jamais une exception. C'est l'extension de la règle posée au ticket 19
— une erreur du modèle n'est pas une panne du serveur — au cas du tiers
défaillant. L'observation ne se contente pas de constater : elle dit quoi faire,
*« réponds sans cette vérification, et précise-le »*, parce qu'un modèle laissé
sans consigne comble le vide.

**4. Le contenu renvoyé est traité comme un extrait du corpus.** Une description
de CVE est du texte tiers : elle est plafonnée puis assainie avant d'entrer dans
le prompt (SEC-01b, SEC-10).

**5. Une clé d'API facultative.** Sans clé, le NIST limite à 5 requêtes par
fenêtre de 30 secondes — or l'agent peut en émettre jusqu'à 9 pour une seule
question (3 appels par tour × 3 tours). Avec clé, la limite passe à 50. La clé
vient de l'environnement, n'est jamais journalisée, et un test le vérifie.

**6. Un nouveau marqueur de test, `network`, exclu de la CI.** Même logique que
`llm`, pour une autre raison : une CI qui rougit parce que le NIST est lent
n'apprend rien sur notre code, et une CI qui rougit sans raison finit par ne
plus être lue.

## Alternatives envisagées

- **OSV.dev** plutôt que le NIST. API plus rapide et sans quota, mais centrée
  sur les paquets open source : moins canonique pour une CVE prise isolément, et
  hors du périmètre annoncé du produit. À rouvrir si le quota du NIST devenait
  bloquant.
- **Un instantané local de la base CVE.** Aucun réseau, aucun quota, parfaitement
  reproductible. Écartée pour deux raisons : plusieurs gigaoctets, périmés en
  quelques jours — et surtout, cela esquiverait précisément la question que ce
  ticket existe pour traiter, à savoir comment appeler un tiers sans lui
  déléguer le contrôle.
- **Mettre les réponses en cache.** Réduirait la pression sur le quota. Reportée :
  les plafonds de l'agent bornent déjà à 9 appels par question, et un cache
  introduit une question de fraîcheur — une CVE est réévaluée. À reprendre si
  `/agent` reçoit du trafic réel (M4).
- **Introduire une interface `VulnerabilityDatabase`** dès maintenant, pour
  respecter l'inversion de dépendance de l'ADR-0002. Écartée : une seule source
  existe. Le client HTTP est injectable, ce qui suffit aux tests, et une
  abstraction sur un unique cas concret est une supposition, pas une conception
  (règle 8 de `CLAUDE.md`). Le jour où une seconde source arrive, l'interface
  est le bon geste.

## Conséquences

- (+) Le critère d'acceptation de M3 devient réel : avec deux outils, le modèle
  arbitre, et le test contre le vrai modèle le vérifie.
- (+) SEC-05 gagne une surface authentique. Jusqu'ici l'argument reposait sur
  l'absence de shell sur le chemin ; il repose désormais sur une barrière de
  validation dont on mesure l'effet — zéro requête émise.
- (+) Le chemin d'échec est conçu, pas subi. Un test couvre chaque mode de
  défaillance du tiers, sans réseau.
- (−) **Une partie des réponses dépend maintenant de la disponibilité d'un
  tiers.** Atténué par la règle 3, mais le produit peut désormais répondre
  « je n'ai pas pu vérifier » pour une raison qui ne lui appartient pas.
- (−) **La CI ne vérifie pas le contrat réel** avec le NIST. Le test qui le fait
  existe, marqué `network`, et doit être lancé en local — notamment avant une
  livraison. C'est lui qui détectera un changement d'API du NIST.
- (−) Sans clé, une question portant sur plusieurs CVE peut dépasser le quota en
  usage normal. La dégradation est annoncée au modèle, donc à l'utilisateur,
  mais c'est une dégradation.
- (−) Un secret de plus à gérer, même facultatif.
