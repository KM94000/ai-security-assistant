# ADR-0016 : Vérifier les barrières de sécurité par mutation

- Statut : accepté
- Date : 2026-11-04

## Contexte

Une suite verte ne prouve rien par elle-même. Un test passe parce que le code
est juste, ou parce qu'il ne vérifie rien — et les deux se ressemblent
exactement de l'extérieur.

Le projet a déjà payé pour le savoir. Une campagne menée **à la main** au
ticket 23 a révélé que la validation d'identifiant CVE ne faisait échouer que
**2 tests sur 12** : les huit autres charges hostiles étaient arrêtées par le
plafond de longueur de pydantic *avant* d'atteindre l'expression régulière
censée être sous test. La couverture de ligne, elle, affichait « couvert ».

Cette campagne n'a jamais été commitée. Personne ne pouvait la rejouer, et M5
s'apprête à ajouter **huit défenses supplémentaires** dont la qualité des
tests serait, elle aussi, inconnue.

## Décision

**1. Un harnais dédié, pas un outil générique.** `mutmut` ou `cosmic-ray`
génèrent des milliers de mutants sur tout le code et rendent un pourcentage.
Notre question est plus étroite et plus utile : **chacune des barrières de
sécurité peut-elle faire échouer au moins un test ?** Une table de huit
mutations choisies répond à ça ; « 87 % de mutants tués » n'y répond pas.

**2. Le seuil est à un test, pas à un pourcentage.** Un score agrégé se
contemple. « Cette barrière n'est testée par rien » se corrige.

**3. La mutation vise le site d'application, pas la valeur.** Les tests
injectent leurs propres plafonds (`max_iterations=2`, `max_answer_chars=120`) :
changer une constante de configuration ne les atteindrait pas. On neutralise
donc la règle — `plafonner` devient l'identité, `_suite` ne renvoie plus
jamais « plafond », le dictionnaire d'outils rend toujours quelque chose.

> Corollaire à retenir : **une barrière dont le test importe la constante
> qu'il vérifie est faiblement mutable**, puisque déplacer la constante
> déplace aussi l'attendu. Quand c'est le cas, on vise le comportement.

**4. Un sous-processus par barrière.** Certaines barrières sont figées à
l'import — la contrainte de longueur du schéma pydantic est construite au
moment où la classe est définie. Les muter en cours de session ne changerait
rien, et la barrière **paraîtrait survivre sans avoir été touchée** : un faux
négatif invisible. Le greffon s'applique dans `pytest_configure`, avant la
collecte.

**5. Bloquant en CI.** Déterministe, sans réseau, ~45 s. Une barrière que plus
rien ne teste doit faire rougir la CI, pas attendre qu'on y pense.

**6. Le rapport est le produit.** Un harnais dont l'échec dit « assertion
failed » n'a pas de produit. Le nôtre nomme la barrière survivante, ce qu'elle
empêchait, et les fichiers qui auraient dû la couvrir.

## Ce que la première exécution a trouvé

Sept barrières sur huit tuées. **Une survivante : la validation de
`X-Request-ID`.**

Or l'ADR-0014 et `SECURITY.md` affirmaient tous deux, sur la foi de la
campagne manuelle, que « désactiver la validation fait rougir neuf tests ».
**Non reproductible.**

Les deux tests concernés passaient **à vide** : ils interrogeaient le journal
après une requête `/query` réussie, qui n'émet aucune ligne applicative —
seules `asyncio` et `httpx` parlent, et leurs lignes ne portent pas
d'identifiant. Mesuré : avec la validation neutralisée, l'en-tête hostile est
bel et bien accepté et renvoyé tel quel, et le journal reste **identique à
l'octet près**.

C'est le même piège qu'un test voisin du même fichier avait déjà rencontré et
corrigé — son docstring le décrit. Deux tests, deux sections plus loin, y
étaient restés.

Correction : les deux déclenchent désormais le guardrail de sortie pour
produire une vraie ligne sous l'identifiant, et une assertion partagée refuse
le silence (`aucune ligne journalisée : le test ne prouverait rien`).

## Alternatives envisagées

- **Un outil de mutation générique.** Couverture plus large, mais un
  pourcentage sur l'ensemble du code noie le seul chiffre qui compte ici. À
  reconsidérer si le projet veut un jour mesurer la qualité globale des tests.
- **Garder la campagne manuelle.** Rejouable par une personne qui se souvient
  de la méthode, c'est-à-dire par personne dans six mois.
- **Un monkeypatch en cours de session, sans sous-processus.** Plus rapide,
  mais incapable de muter ce qui est figé à l'import — et ses faux négatifs
  seraient silencieux, ce qui est le pire défaut possible pour cet outil.

## Conséquences

- (+) Les huit barrières sont vérifiées à chaque exécution de la CI.
- (+) Deux tests qui ne prouvaient rien le prouvent maintenant.
- (+) Chaque défense de M5 naîtra avec son test vérifié, au lieu d'être
  rattrapée après coup.
- (+) Le harnais se teste lui-même : une barrière inconnue dans la table fait
  échouer la campagne, plutôt que de muter silencieusement rien du tout.
- (−) **~45 s de CI**, huit relances de pytest en sous-processus.
- (−) La table est **maintenue à la main**. Une barrière ajoutée sans sa ligne
  n'est pas vérifiée, et rien ne le signale. C'est le défaut structurel de
  l'approche choisie ; l'inscrire dans la Definition of Done est la parade.
- (−) Une neutralisation mal écrite peut ne rien muter et laisser croire à une
  survie. Le refus des barrières inconnues couvre la faute de frappe, pas la
  mutation inopérante.
