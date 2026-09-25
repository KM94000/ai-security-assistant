# ADR-0015 : Traçage vers une instance Langfuse auto-hébergée

- Statut : accepté
- Date : 2026-09-25

## Contexte

Le ticket 23 a donné des logs structurés et un identifiant par requête. Ils
disent *qu'il s'est passé quelque chose*, et **volontairement rien de plus** :
ni la question, ni les extraits récupérés, ni la réponse — parce qu'un journal
est conservé longtemps et lu largement (SEC-12).

Or c'est précisément ce contenu qu'il faudra lire en M5. Quand une défense
cédera sur l'une des centaines d'exécutions d'une campagne de red teaming, la
question ne sera pas « à quelle heure ? » mais « qu'est-ce qui est entré, quel
extrait a été retenu, et avec quel score ? ».

Il faut donc une seconde destination, conçue pour ce contenu — et la question
devient : **où va-t-elle vivre ?**

## Décision

**1. Une instance auto-hébergée, pas le service en ligne.** C'est le point
central. Une trace contient par construction la question de l'utilisateur et les
extraits du corpus. L'envoyer à un tiers contredirait frontalement l'ADR-0003,
qui a retenu un modèle local parce qu'« un outil de sécurité manipule des
données qu'on préfère ne pas envoyer chez un tiers ».

Le coût est réel et assumé : **six conteneurs** — l'interface, le worker,
PostgreSQL, ClickHouse, Redis et un stockage compatible S3 — là où le service en
ligne n'aurait rien demandé.

**2. Derrière un profil docker compose.** Ces six services ne démarrent que sur
demande explicite. Imposer une telle pile à quiconque veut simplement lancer les
tests d'intégration rendrait l'environnement de développement plus lourd que le
produit lui-même.

**3. Le métier n'importe jamais le SDK.** Il appelle `traced(...)`, défini dans
`observability/tracing.py`, seul fichier à connaître Langfuse — comme
`llm/ollama.py` est seul à connaître l'API d'Ollama (ADR-0002). Deux bénéfices :
changer d'outil reste local, et **les 350 tests passent sans qu'aucune signature
n'ait changé**, ce qui vérifie au passage l'affirmation faite en arbitrant le
périmètre de M4 — ajouter du traçage n'oblige à retoucher aucun appelant.

**4. Désactivé, c'est un vrai no-op ; actif mais en panne, le produit continue.**
Une configuration absente ou incomplète n'empêche pas le démarrage, et toute
erreur du traceur est journalisée puis ignorée. Un service qui tombe parce que
son observabilité est en panne a inversé la hiérarchie.

**5. Les secrets sont rédigés avant l'envoi**, par le même guardrail que les
réponses. Une trace est une seconde sortie du système, vers un autre
destinataire : elle mérite la même barrière. Les valeurs sont aussi plafonnées —
une trace n'est pas un entrepôt.

## L'arbitrage à énoncer clairement

**Une trace contient délibérément ce que les logs excluent.** Ce n'est pas une
contradiction avec SEC-12, c'est un arbitrage :

| | Journaux | Traces |
|---|---|---|
| Question de l'utilisateur | jamais | **oui** |
| Extraits récupérés | jamais | **oui** |
| Secrets reconnaissables | jamais | jamais |
| Destination | agrégateur, conservé longtemps, lu largement | instance dédiée, locale |

Sans ce contenu, une trace ne servirait à rien. La contrepartie est que
**l'instance Langfuse doit être traitée comme un dépôt de données sensibles**, ce
que `docs/SECURITY.md` énonce désormais. C'est la raison qui rend la décision 1
non négociable : l'arbitrage n'est acceptable que parce que la destination reste
sur la machine.

Deux tests figent cette frontière, pour qu'elle reste un choix documenté et non
une dérive : l'un vérifie qu'une question sensible est absente des logs **et
présente** dans la trace, l'autre qu'un secret n'atteint jamais ni l'un ni
l'autre.

## Alternatives envisagées

- **Langfuse Cloud.** Gratuit, aucune infrastructure, une clé à créer. Écarté
  pour la décision 1. L'argument « les prompts partent déjà chez Groq en mode
  hébergé » ne tient pas : ce mode est un choix explicite et réversible, alors
  qu'un traçage en ligne exfiltrerait aussi les exécutions en mode local.
- **Un traçage maison, sans dépendance.** Écrire nous-mêmes durées et étapes
  dans un format simple. Moins cher, mais prive des vues de comparaison qui
  servent justement en M5, et s'écarte de la stack figée par l'ADR-0001.
- **Ne rien faire et aller directement à M5.** Sérieusement envisagé. Écarté
  parce que SEC-12 mentionne « logs **et** traces » : sans traces, la ligne
  serait restée à moitié fermée en prétendant le contraire.

## Conséquences

- (+) Le critère du ticket est vérifié de bout en bout : une requête `/agent`
  apparaît avec ses étapes — `agent` à 3,2 s, `outil:consulter_cve` à 0,66 s.
- (+) Langfuse 4 émet en **OpenTelemetry**, un protocole standard. Si l'outil
  disparaissait, les traces resteraient portables vers n'importe quel
  collecteur : l'enfermement est faible.
- (+) L'identifiant de requête du ticket 23 relie journaux et traces.
- (−) **Six conteneurs.** Sur un poste qui fait déjà tourner Qdrant et 4,9 Go de
  poids de modèle, c'est lourd, et une panne de l'un d'eux devient une panne de
  l'environnement de développement. Le profil limite les dégâts ; il ne les
  supprime pas.
- (−) **L'image du stockage objet est épinglée par empreinte**, pas par
  étiquette : `minio/minio` n'est plus accessible publiquement sur Docker Hub et
  `quay.io/minio/minio` répond 401. L'image retenue est une reprise
  communautaire. C'est le point le plus fragile de cette pile, et il est signalé
  comme tel dans le fichier compose.
- (−) Trois secrets d'infrastructure de plus, dans un second fichier
  d'environnement — la configuration de l'application refusant, à raison, les
  variables qu'elle ne connaît pas.
- (−) Le premier démarrage prend environ 90 secondes, le temps des migrations.
