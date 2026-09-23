# ADR-0013 : Un second fournisseur de modèle, pour vérifier que l'abstraction tient

- Statut : accepté
- Date : 2026-09-23

## Contexte

L'ADR-0003 affirme depuis le premier jour qu'Ollama est « derrière une interface,
donc remplaçable sans toucher au métier ». C'était une **promesse d'architecture
jamais mise à l'épreuve** : une seule implémentation existait, et une abstraction
à un seul cas concret ne prouve rien.

Deux besoins concrets la rendent urgente à vérifier.

**La vitesse conditionne les deux jalons qui restent.** M5 rejoue chaque attaque
N fois pour mesurer sa reproductibilité — c'est la règle posée dans les points de
vigilance de `SECURITY.md`. M6 déclenche plusieurs appels de modèle par question
évaluée, sur un banc de 47 questions. À 30 secondes l'appel sur un processeur,
une campagne se compte en heures ; c'est la différence entre relancer une mesure
et s'en passer.

**Rien n'est démontrable.** Un agent qui répond en deux minutes n'est pas
montrable, et ferme la porte à tout déploiement.

## Décision

**1. Une implémentation « compatible OpenAI », pas une implémentation Groq.**
Groq, OpenAI, Together, Mistral, Fireworks et vLLM exposent la même forme d'API.
Un seul module les couvre tous ; on en change par `HOSTED_LLM_BASE_URL`. Coder
pour un fournisseur nommé aurait été plus simple à court terme et faux dès le
second.

**2. Groq comme défaut, pour une raison mesurable.** Palier gratuit sans carte
bancaire, et la latence la plus basse — ce qui est exactement le critère utile
pour les campagnes de M5. Ce n'est pas un engagement : c'est une valeur par
défaut dans un fichier de configuration.

**3. `ollama` reste le fournisseur par défaut.** La CI n'a pas de clé, les tests
d'intégration supposent un modèle local, et le projet doit rester utilisable hors
ligne. Le basculement est explicite.

**4. La configuration refuse de se charger si la clé manque.** Sans cette règle,
l'application démarrerait, `/health` répondrait `200`, et le problème
n'apparaîtrait qu'à la première question — sous la forme d'un 503 générique dont
le message ne nomme volontairement pas la cause.

**5. httpx plutôt que le SDK officiel.** Le projet parle déjà à Ollama en HTTP
direct, et l'API de chat tient en deux formes de requête. Un SDK apporterait des
dizaines de paquets transitifs, donc de la surface de chaîne d'approvisionnement
(LLM03), pour économiser une centaine de lignes qu'il faut de toute façon
comprendre.

## Ce que l'exercice a révélé

C'était l'objet du ticket, et la réponse est nuancée.

**Le code métier n'a pas bougé d'une ligne.** Génération, agent, outils, routes :
rien ne sait qu'un second fournisseur existe. Le seul `if` du projet qui les
distingue est dans la racine de composition, dont c'est précisément le rôle.

**Mais les types partagés ont eu besoin de deux champs.** Les API de forme OpenAI
exigent que chaque résultat d'outil référence l'appel qui l'a provoqué, par un
identifiant ; Ollama les apparie par l'ordre des messages et n'en produit aucun.
D'où `ToolCall.id` et `ChatMessage.tool_call_id`, tous deux facultatifs.

Est-ce une fuite de l'abstraction ? **Non, et il faut dire pourquoi.** Un appel
d'outil *a* une identité — c'est une notion du domaine, pas un détail de
transport. Ollama choisit de ne pas s'en servir ; ce n'est pas la même chose que
de ne pas en avoir. Les deux champs sont optionnels, et les deux implémentations
se replient sur le nom de l'outil quand l'identifiant est absent, ce qui rend un
historique produit par l'un rejouable par l'autre.

La leçon tient en une phrase : **une abstraction dérivée d'un seul cas concret
est une hypothèse.** Celle-ci a tenu à deux champs près, découverts en une heure
plutôt qu'en production.

## Alternatives envisagées

- **Anthropic (Claude).** Forme d'API différente, donc une seconde implémentation
  sans réutilisation possible, et un amendement de l'ADR-0001 qui nomme
  OpenAI/Azure. Écartée comme chemin le plus long pour vérifier l'abstraction.
  Reste ouverte : le module d'aujourd'hui ne la gêne pas.
- **Les deux fournisseurs d'un coup.** Preuve plus forte, deux fois le travail et
  deux clés à gérer, pour un bénéfice de démonstration plus que d'usage.
- **Rester en local et attendre M5.** C'est l'ordre du plan, et c'est l'erreur :
  on aurait découvert le coût en latence au moment où il bloque, sur un jalon
  déjà chargé.
- **Le SDK officiel.** Voir décision 5.

## Conséquences

- (+) L'ADR-0003 cesse d'être une promesse. Le test d'intégration contre le vrai
  service en fait un fait vérifiable, y compris sur le point le plus fragile —
  l'aller-retour complet d'un appel d'outil.
- (+) M5 et M6 deviennent praticables : une campagne se compte en minutes.
- (+) Le guardrail de sortie reconnaît désormais la forme des clés Groq. Un
  guardrail qui ignore le secret que l'application manipule elle-même protège
  tout le monde sauf nous (SEC-02).
- (−) **Un secret de plus**, et le premier dont dépend le fonctionnement nominal.
  La clé du NIST était facultative ; celle-ci ne l'est pas quand le fournisseur
  hébergé est actif.
- (−) **La CI ne teste pas ce chemin.** Elle n'a pas de clé, et lui en donner une
  échangerait une couverture contre un secret dans les réglages du dépôt. Le
  test existe, marqué `network`, et se lance en local.
- (−) Deux implémentations à maintenir en parallèle, dont une dont on dépend peu
  au quotidien — c'est-à-dire celle qui se dégradera sans qu'on s'en aperçoive.
  Le test marqué `network` est la seule parade.
- (−) Les réponses partent désormais chez un tiers quand le mode hébergé est
  actif, ce que l'ADR-0003 avait précisément voulu éviter. Le défaut local reste
  donc le défaut, et le basculement est une décision explicite.
