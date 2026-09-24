# Changelog

## [Non publie] - M4, ticket 23 : logs structures et identifiant de requete
### Ajoute
- **Module `observability/`** : configuration des logs structures et intergiciel
  d'identifiant de requete.
- **Chaque requete porte un identifiant**, repris de l'en-tete `X-Request-ID`
  s'il est bien forme, attribue sinon, et **renvoye au client** dans l'en-tete de
  reponse — de quoi citer une requete precise en signalant une panne.
- `LOG_LEVEL` et `LOG_JSON` en configuration.
- ADR-0014.

### Le parti pris
- **Aucun des vingt-cinq appels `logging` existants n'a ete reecrit.** structlog
  est branche en aval du module standard : les appels du projet comme ceux des
  bibliotheques tierces traversent la meme chaine et ressortent au meme format,
  horodates, avec leur module d'origine et l'identifiant de requete.
- L'identifiant voyage par variable de contexte, jamais en parametre : le passer
  de fonction en fonction aurait modifie toute la chaine d'appel, jusqu'aux
  doubles de test.
- L'intergiciel est ecrit a la main plutot qu'avec `BaseHTTPMiddleware`, qui
  execute la suite dans une tache distincte et casserait cette propagation.

### Securite
- **SEC-12 passe a partiel.** Ni question d'utilisateur, ni contenu de document,
  ni cle de fournisseur n'atteint une ligne de journal. Les arguments d'outil
  sont traces par leurs cles, jamais par leurs valeurs.
- **Injection de logs couverte** : un `X-Request-ID` client est valide contre une
  forme stricte. Sans cela, un saut de ligne suffirait a fabriquer une ligne de
  journal entiere, qu'un agregateur lirait comme un evenement authentique — de
  quoi masquer une intrusion sous un faux « connexion reussie ». Une valeur
  demesuree est ecartee de la meme facon.
- Verifie **par mutation** : desactiver la validation fait rougir neuf tests.
- Le volet **traces** de SEC-12 reste ouvert : il suppose que des traces
  existent, donc le ticket 24.

### Teste
- 22 tests unitaires, dont la propriete centrale : un appel `logging` inchange
  ressort en JSON et porte l'identifiant de la requete en cours.
- 8 tests de securite SEC-12.

## [Non publie] - Ticket 26 : un second fournisseur de modele, pour verifier que l'abstraction tient
### Ajoute
- **`OpenAICompatibleProvider`** : une seule implementation pour Groq, OpenAI,
  Together, Mistral, Fireworks ou un vLLM local — tous exposent la meme forme
  d'API. On en change par `HOSTED_LLM_BASE_URL`, sans toucher au code.
- `LLM_PROVIDER` (`ollama` par defaut, `hosted` au choix), `HOSTED_LLM_BASE_URL`,
  `HOSTED_LLM_MODEL`, `HOSTED_LLM_API_KEY`, `HOSTED_LLM_TIMEOUT_S`.
- La configuration **refuse de se charger** si le fournisseur heberge est actif
  sans cle : sinon la panne n'apparaitrait qu'a la premiere question, sous la
  forme d'un 503 generique qui ne nomme pas sa cause.
- ADR-0013, et trois tests d'integration contre le vrai service (marques
  `network`), dont l'aller-retour complet d'un appel d'outil.

### Ce que l'exercice a revele
- **Le code metier n'a pas bouge d'une ligne.** Le seul `if` distinguant les deux
  fournisseurs est dans la racine de composition, dont c'est le role.
- **Mais les types partages ont eu besoin de deux champs** : `ToolCall.id` et
  `ChatMessage.tool_call_id`. Les API de forme OpenAI exigent que chaque resultat
  d'outil reference l'appel qui l'a provoque ; Ollama les apparie par l'ordre des
  messages. Les deux champs sont facultatifs, et les deux implementations se
  replient sur le nom de l'outil en leur absence — un historique produit par l'une
  reste rejouable par l'autre.
- Mesure : `/query` passe de 97,8 s a 3,4 s, et l'agent effectue trois tours
  d'outils en 17,4 s la ou le modele local en faisait un en 28,4 s.

### Securite
- Le guardrail de sortie reconnait desormais la forme des cles Groq. Un guardrail
  qui ignore le secret que l'application manipule elle-meme protege tout le monde
  sauf nous (SEC-02).
- La cle n'apparait dans aucun log ni dans aucun message d'erreur : le corps
  d'erreur d'un fournisseur peut refleter l'en-tete recu, donc on ne le lit pas
  et on ne retient que le code de statut. Un test le verifie.
- **SEC-07 : observation datee consignee.** `llama3.1` a spontanement imite la
  forme de nos delimiteurs de contexte dans une reponse. Non reproduit sur
  `gpt-oss-120b` : la divulgation depend du modele, ce qui interdit de conclure
  d'un seul essai. Protocole de mesure note pour M5.

## [Non publie] - M3, ticket 21 : `POST /agent`, et le budget de temps de l'agent
### Ajoute
- **Route `POST /agent`** : le livrable de M3. Meme schema d'entree que `/query`
  — l'agent n'est pas une seconde porte aux regles plus souples — et une reponse
  qui expose `answer`, `sources` et `iterations`.
- **`iterations` dans la reponse** : le nombre de tours d'outils reellement
  effectues. Zero signifie que le modele a repondu de lui-meme, sans rien
  consulter. C'est ce qui rend le cheminement verifiable par le lecteur.
- **`AGENT_TIMEOUT_S`**, budget de temps total d'une execution, 300 s par defaut.
- Un **504** distinct du 503 : le budget epuise n'est pas une panne, et
  reformuler y change quelque chose la ou reessayer ne sert a rien.
- Section « A quoi ca ressemble vraiment » dans le README : deux echanges
  reellement captures, dont un dont les limites sont commentees.

### Securite
- **Le budget de temps est le seul plafond que les autres ne remplacent pas.**
  Le plafond d'iterations et celui d'appels par tour comptent des etapes ; ils
  ne voient rien d'un appel unique qui ne revient jamais (SEC-10).
- Le plafond de longueur de question s'applique aussi **dans le service**, et
  plus seulement dans le schema HTTP : le service est une porte a part entiere.
- Le 504 ne revele ni la duree du budget ni aucun detail interne — un test
  SEC-11 le verifie, la duree partant dans les logs.
- `extra="forbid"` refuse un `max_iterations` envoye par le client : c'est
  precisement le parametre qu'on tenterait de pousser pour relever un plafond.

### Modifie
- Les fixtures d'integration partagees (collection jetable, corpus ingere)
  passent dans `tests/integration/conftest.py` : deux fichiers s'en servent.
- `AgentService` exige desormais un `timeout_s` explicite, comme ses autres
  plafonds.

## [Non publie] - M3, ticket 20 : consultation d'une CVE, premier outil qui sort de la machine
### Ajoute
- **Outil `consulter_cve`** : interroge la base publique du NIST (NVD) pour un
  identifiant donne, et rend sa description, sa date de publication et son score
  CVSS v3.1. Lecture seule.
- **Deuxieme outil, donc vrai arbitrage.** Le critere d'acceptation de M3 —
  « l'agent selectionne le bon outil » — devient verifiable : un test contre le
  vrai modele montre qu'une question sur une CVE nommee part vers le NIST, et
  une question de fond vers le corpus.
- `NVD_BASE_URL`, `NVD_TIMEOUT_S`, `NVD_API_KEY` (facultative) et
  `CVE_DESCRIPTION_MAX_CHARS` en configuration.
- Marqueur de test `network`, exclu de la CI au meme titre que `llm`.
- ADR-0012.

### Securite
- **Le modele choisit quelle CVE, jamais ou la chercher.** L'hote et le chemin
  viennent de la configuration ; l'identifiant est valide par une expression
  reguliere ancree, puis transmis comme parametre de requete encode. Les tests
  SEC-05 verifient qu'un identifiant non conforme **n'emet aucune requete** —
  c'est cette propriete qui ferme la porte au SSRF, pas le refus lui-meme.
- Un message de refus ne recopie jamais la valeur fautive : la charge ne doit
  pas revenir dans le prompt par la porte de l'erreur.
- **Une panne du tiers n'est pas une panne du produit.** Delai depasse, 5xx,
  JSON illisible, quota refuse : chacun devient une observation qui dit au
  modele de repondre sans la verification, et de le preciser.
- La description renvoyee par le NIST est du contenu tiers : plafonnee puis
  assainie comme un extrait du corpus (SEC-01b, SEC-10).
- Le plafond d'appels par tour borne aussi les appels sortants : un modele
  detourne ne peut pas se servir de l'agent comme relais pour marteler un
  service externe.
- La cle d'API n'apparait dans aucun log, et un test le verifie.

### Teste
- 19 tests unitaires sur l'outil, avec un transport factice : cas nominal,
  quota, panne, delai, JSON illisible, description piegee, absence de score.
- 14 tests de securite supplementaires (SEC-05 et SEC-06).
- 3 tests unitaires sur l'aiguillage entre deux outils.
- 2 tests d'integration contre la vraie base du NIST, marques `network` : ils
  verifient le contrat suppose au service — chemin, parametre, forme de la
  reponse — et c'est eux qui detecteront un changement de son API.

## [Non publie] - M3, ticket 19 : agent LangGraph, le RAG expose comme outil
### Ajoute
- **Module `agents/`** : un graphe LangGraph a trois noeuds — decider, executer,
  couper sur plafond — et le service qui le pilote. Le modele choisit d'appeler
  un outil ou de repondre ; le code impose tout le reste.
- **Outil `rechercher_corpus`** : le RAG expose a l'agent, en lecture seule. Ses
  arguments sont valides par un schema pydantic `extra="forbid"`, et les extraits
  rendus sont assainis avant d'entrer dans la conversation.
- **`ToolCallingProvider`** : interface distincte de `LLMProvider` pour l'appel
  d'outils, implementee par `OllamaProvider` via `/api/chat` (ADR-0011). Le
  fournisseur traduit et ne decide rien : il n'execute aucun outil et ne valide
  aucun argument.
- Modules partages `security/limits.py` (plafonds d'entree et de sortie) et
  `security/prompt_sanitation.py` (neutralisation des marqueurs de bloc), pour que
  `/query` et l'agent appliquent la meme implementation plutot que deux copies.
- `AGENT_MAX_ITERATIONS`, par defaut 3.
- ADR-0011.

### Securite
- **SEC-05 et SEC-06 passent a partiel.** Quatre barrieres, toutes cote code :
  liste blanche d'outils, plafond d'iterations, plafond d'appels par tour,
  validation des arguments. Un appel refuse est journalise.
- La reponse de l'agent passe par le meme guardrail de sortie et le meme plafond
  de longueur que `/query` : une seconde porte ne doit pas devenir une porte
  derobee.
- Les arguments d'appel sont traces par leurs cles, jamais par leurs valeurs :
  une question peut contenir des donnees sensibles (SEC-12). Le tracage complet
  viendra avec Langfuse en M4, dans un systeme prevu pour.

### Mesure
- Un tour d'agent sur CPU : **31 s** pour decider d'appeler l'outil, **86 s**
  pour rediger la reponse a partir de l'extrait. Un aller-retour coute donc
  environ deux minutes, contre une vingtaine de secondes pour `/query`. La
  latence varie fortement d'un appel a l'autre — de 32 s a 237 s pour un meme
  appel de decision. Le delai de 120 s calibre pour `/query` sera a revoir au
  ticket 21, avec l'endpoint.
- **Temperature nulle sur le chemin outille.** A la temperature par defaut
  d'Ollama (0,8), `llama3.1` a decrit une fois l'appel d'outil en JSON dans son
  texte au lieu d'emprunter le canal prevu — le code ne l'interprete pas, et
  l'agent a donc repondu sans source. Sur six essais ulterieurs, l'appel etait
  structure a chaque fois : c'est de la variance, pas un defaut de formulation.
  La temperature est mise a zero pour rendre la decision reproductible.
- Sans outils presentes au second tour, le modele repond de memoire : 1 855
  caracteres en 539 s, sans source. Avec les outils presentes : 395 caracteres
  fondes sur l'extrait. Les outils restent donc presentes a chaque tour.

### Dependance
- `langgraph` ajoute **22 paquets transitifs**, dont `langchain-core` et
  `langsmith` : c'est la plus lourde du projet en nombre de paquets, donc en
  surface de chaine d'approvisionnement (LLM03). Cout assume et documente
  (ADR-0011) ; le tracage LangSmith reste inactif tant qu'aucune variable
  d'environnement ne l'active.

## [Non publie] - Dette M2 : un retrieval capable de dire « je n'ai rien »
### Ajoute
- **Seuil de pertinence** `RETRIEVAL_MIN_SCORE` (0,64), applique extrait par
  extrait par `RetrievalService`. Une liste vide signifie que le corpus ne couvre
  pas la question : `/query` et `/query/stream` renvoient alors le refus explicite,
  sans appeler le modele. Auparavant la recherche renvoyait toujours ses k
  extraits, meme pour une recette de cuisine, et ce refus ne se declenchait jamais.
- **Garde-fou d'espace vectoriel** : le store inscrit `modele@revision` dans les
  metadonnees de la collection qu'il cree. Lire ou ecrire avec un autre modele,
  ou dans une collection qui n'en declare aucun, leve
  `CollectionEmbeddingModelMismatchError` (503 generique cote API). Le controle de
  dimension ne voyait rien : ancien et nouveau modele ont tous deux 384 dimensions.
- **Revision du modele epinglee** (`EMBEDDING_MODEL_REVISION`) et transmise au
  chargement : le seuil est calibre sur ces poids precis.
- `tests/integration/test_retrieval_relevance.py` : 47 questions, en jeux de
  calibrage et de controle, rejouees en CI contre le vrai Qdrant. En cas d'echec,
  le message affiche chaque score et le seuil que donnerait la regle.
- ADR-0010, qui remplace l'ADR-0006.
- `docs/DESIGN.md` : section « Strategie RAG », qui argumente le tri des
  strategies avancees — retenues (agentic RAG en M3, puis decoupage semantique,
  reranking, recherche hybride) et ecartees (contextual retrieval, expansion de
  requete hors agent, late chunking, embeddings fine-tunes) — avec le critere de
  decision : battre la base sur le banc de 47 questions.

### Modifie
- **Modele d'embeddings** : `all-MiniLM-L6-v2` remplace par
  `ibm-granite/granite-embedding-107m-multilingual` (384 dimensions, 512 tokens,
  ~220 Mo, Apache 2.0). Decoupage inchange (800/120).
- Le test d'integration hors corpus exige desormais le refus exact, sans source.
  Il n'a plus besoin d'Ollama et tourne en CI.
- Le test d'ingestion accepte OWASP ou MITRE ATLAS en tete pour l'injection
  indirecte : les deux referentiels la traitent, et exiger l'un devant l'autre
  figeait un ordre entre deux passages pertinents.

### Mesure
- 47 questions sur le vrai corpus, quatre modeles (details dans l'ADR-0010) :

  | Modele | Seuil possible | MRR@5 |
  |---|---|---|
  | all-MiniLM-L6-v2 | non, chevauchement | 0,63 |
  | paraphrase-multilingual-MiniLM-L12-v2 | oui | 0,53 |
  | multilingual-e5-small | non, scores tasses | 0,70 |
  | **granite-embedding-107m-multilingual** | **oui, 0 erreur au controle** | **0,77** |

- Traduire la question en anglais avec le modele actuel, meme a la main :
  chevauchement et MRR 0,56. Ecarte.
- Les tests ont ete verifies par mutation : avec l'ancien modele, ou avec le seuil
  desactive, ils echouent.

### Limites
- **Marge etroite** : 0,652 pour la pire question couverte, 0,613 pour la
  meilleure hors sujet. Des erreurs sont attendues sur des formulations inedites.
- Le seuil ecarte le hors-sujet, pas le non couvert : 5 questions de securite
  absentes du corpus sur 10 le franchissent. Ce n'est pas non plus un controle de
  securite.

### Migration
- Les collections existantes sont refusees au premier acces. Les recreer :
  `curl -X DELETE http://localhost:6333/collections/aisec_docs`, puis
  `python -m aisecassist.ingestion.pipeline data/corpus`.

## [Non publie] - M2, ticket 15 : guardrail de sortie (SEC-02)
### Ajoute
- Module `security/output_guardrail.py` : redaction des secrets a forme
  reconnaissable avant renvoi au client — cles privees, jetons de fournisseurs,
  affectations explicites — ainsi que du nonce de delimitation du prompt.
- `StreamRedactor` : la meme protection sur le flux. Un secret coupe entre deux
  fragments echapperait a une redaction fragment par fragment, et le client le
  reconstituerait en concatenant. Deux mecanismes : une fenetre de retenue
  dimensionnee sur la plus longue correspondance possible, et un recul de la
  coupe devant une correspondance a cheval.
- Journalisation en avertissement a chaque declenchement, avec les categories
  et jamais les valeurs : journaliser un secret pour signaler qu'on l'a bloque
  reviendrait a le divulguer une seconde fois, dans un endroit souvent moins
  bien protege que la reponse HTTP.

### Securite
- **SEC-02 passe a partiel.** Le guardrail couvre les deux chemins, flux
  compris. Restent hors portee : la detection de PII, et le fait que le modele
  *refuse* de divulguer — un comportement, mesure en M5 avec SEC-03.
- Le module est explicitement une **derniere ligne de defense** : un secret ne
  devrait jamais atteindre le modele, et un declenchement signale une
  defaillance en amont. Une detection par motifs attrape des formes connues,
  pas tout ce qui est secret.

### Modifie
- Les tests de streaming n'affirment plus les frontieres de decoupage, seulement
  l'ordre et le contenu. La fenetre de retenue regroupe les fragments courts, et
  un protocole de streaming ne promet rien sur ces frontieres.

### Mesure
- Cout de la fenetre de retenue sur une vraie connexion HTTP : premier fragment
  a 3,91 s contre 2,16 s sans guardrail, soit environ 1,7 s — la valeur attendue
  pour 96 caracteres. Le flux reste incremental : 16,2 s d'etalement sur 225
  fragments, progression lineaire.

## [Non publie] - M2, tickets 16 et 18 : doc OpenAPI et integration en CI
### Ajoute
- **Job CI `integration`** : les tests d'integration tournent desormais contre
  un vrai conteneur Qdrant, demarre en service GitHub Actions. C'est le job qui
  manquait — le healthcheck casse du compose avait traverse ruff, mypy, 104
  tests, trois scans de securite et `docker compose config` sans etre vu.
- Marqueur pytest `llm`, distinct de `integration` : la CI peut demarrer Qdrant
  et telecharger MiniLM (90 Mo), pas heberger Ollama et ses 4,9 Go. Elle lance
  `pytest -m "integration and not llm"` ; les 4 tests restants se lancent en
  local avec `pytest -m integration`.
- Cache du modele d'embeddings en CI.
- Documentation OpenAPI : description de l'API, tags decrits, resumes de
  routes, reponses 422 et 503 documentees, exemples sur `QueryResponse` et
  `SourceRef`, et un exemple de flux SSE — OpenAPI ne sachant pas decrire une
  suite d'evenements, sans lui un client ne peut pas deviner le format.
- La version affichee dans `/docs` est lue depuis les metadonnees du paquet :
  une constante en dur finit toujours par diverger de `pyproject.toml`.
- `tests/unit/test_openapi.py` : la documentation se degrade en silence, ces
  tests transforment l'exigence en controle automatique.

### Modifie
- `/health` : resume explicite au lieu du libelle derive du nom de fonction, et
  docstring precisant qu'il ne sonde volontairement pas les dependances — une
  sonde de vivacite qui echoue parce que Qdrant est momentanement absent ferait
  redemarrer l'API en boucle.

## [Non publie] - M2, ticket 14 : streaming SSE
### Ajoute
- `POST /query/stream` : meme reponse que `/query`, emise au fil de la
  generation. Trois types d'evenements — `sources` d'abord, puis autant de
  `token` que de fragments, enfin `done`. Les sources arrivent avant le texte
  pour que le client puisse les afficher pendant que la reponse se construit.
- `GenerationService.stream_answer()`, adosse a `LLMProvider.stream()` pose des
  le ticket 8 (ADR-0008) — l'anticipation evite ici toute reecriture.
- Module `api/sse.py` : encodage des evenements. La charge est serialisee en
  JSON, ce qui neutralise par construction le piege du format — un saut de
  ligne brut dans `data` termine l'evenement, et une reponse de modele en
  contient des le premier paragraphe.
- Module `api/messages.py` : messages d'erreur partages entre le chemin JSON et
  le chemin streame, pour qu'ils disent exactement la meme chose.
- Plafond `max_answer_chars` (8 000 par defaut), applique cote serveur fragment
  par fragment, avec un marqueur explicite quand la troncature a lieu.

### Securite
- **SEC-10 etendu** : au plafond de longueur de question s'ajoute celui de la
  reponse. En streaming, c'est le seul endroit ou il protege — une generation
  qui part en boucle emettrait sinon des fragments indefiniment, et rien du
  cote client ne l'arreterait.
- **SEC-11 etendu au chemin streame.** Une fois le flux ouvert, le statut 200 et
  les en-tetes sont deja partis : les gestionnaires d'exception ne peuvent plus
  s'appliquer. Sans rattrapage explicite dans le generateur, le streaming
  laisserait fuiter ce que le chemin classique masque. La panne devient un
  evenement `error` portant le meme message generique.

### Verifie
- Incrementalite mesuree sur une vraie connexion HTTP : sources a 0,42 s,
  premier fragment a 2,16 s, dernier a 21,34 s — soit 19,2 s d'etalement sur
  113 fragments. `TestClient` ne peut pas le prouver : son transport ASGI
  tamponne le corps entier avant de le rendre.

## [Non publie] - Revue de M1 : correctifs
### Corrige
- **docker-compose** : le healthcheck Qdrant utilisait `/dev/tcp`, une extension
  bash, alors que `CMD-SHELL` passe par `/bin/sh` — dash dans cette image. La
  sonde echouait systematiquement et, avec `depends_on: service_healthy`, l'API
  ne demarrait jamais. Invocation explicite de bash. Verifie : le conteneur
  passe `healthy` des la premiere sonde.
- **Assemblage du prompt** : `resultat.source` etait interpole sans passer par
  la neutralisation appliquee au texte, alors qu'il vient du meme payload non
  fiable. Un nom de fichier contenant un saut de ligne rompait la structure
  `[n] source : X`. Repliement des lignes, neutralisation et plafond de longueur.
- **Recherche Qdrant** : un point sans provenance faisait echouer la requete
  entiere. Un seul point corrompu proche du centre de l'espace vectoriel rendait
  `/query` indisponible pour tous. Le point est desormais ecarte et journalise ;
  aucun extrait sans provenance n'est rendu, la disponibilite ne depend plus de
  l'integrite de chaque point.
- **Decoupage** : la deduplication ne retirait qu'une seule queue redondante. Un
  recouvrement eleve en produit plusieurs, qui occupaient des places du top-k
  pour le meme passage.
- **Corpus** : `README.md` etait ingere comme du contenu interrogeable et pouvait
  etre cite en source d'une reponse de securite. Deplace dans `data/`.
- **Configuration** : contraintes pydantic sur les bornes, et validation de
  `chunk_overlap < chunk_size` au chargement. `RETRIEVAL_TOP_K=0` demarrait sans
  un mot puis faisait echouer chaque requete en 503.
- **Generation** : une reponse vide du modele repartait en 200 accompagnee de
  sources, ce qui a la forme d'un resultat verifiable sans rien affirmer. Traitee
  comme un echec de generation.
- Retrait d'une fonction morte dans les tests d'integration.

## [Non publie] - M1, tickets 11 a 13 : recherche, generation et POST /query
### Ajoute
- `RetrievalService` : vectorise la question et interroge la base. N'appelle pas
  le modele — la separation permet de mesurer les deux etages independamment.
- `generation/prompt.py` : assemblage en trois blocs separes, contexte et
  question clos par un **nonce aleatoire genere cote serveur a chaque requete**
  (ADR-0009). Un document empoisonne ne peut pas connaitre cette valeur, donc
  pas fermer la cloture.
- `GenerationService` : sans extrait pertinent, le modele n'est pas appele du
  tout et un refus explicite est renvoye.
- `POST /query` : route mince, schemas pydantic stricts (`extra="forbid"`,
  rognage des blancs, plafond de 2 000 caracteres), reponse accompagnee de ses
  sources et de leurs scores.
- Gestionnaires d'erreurs : panne de dependance en 503 generique, exception
  imprevue en 500 generique, detail technique journalise et jamais renvoye.
- Cycle de vie de l'application : clients Qdrant et HTTP crees au demarrage et
  fermes a l'arret.
- ADR-0009 : delimitation du contexte par nonce serveur.
- Doubles de test partages (`tests/doubles.py`) implementant les vraies
  interfaces.

### Securite
- **SEC-11 passe a vert en CI** : 7 formes d'entree malformee en 422, pannes en
  503 generique, et verification qu'aucune reponse ne laisse fuiter de trace, de
  chemin, de nom de module ni d'hote interne.
- **SEC-01 et SEC-01b passent a partiel** : le confinement structurel est fait
  et teste ; la resistance comportementale du modele reste entiere, M5.
- **SEC-10 passe a partiel** : seul le plafond de longueur de question est pose.

### Modifie
- `llm_timeout_s` releve de 60 a 120 secondes : le premier appel a un Ollama
  local paie le chargement du modele en memoire, ce qui depasse une minute sur
  CPU.
- Les erreurs d'Ollama incluent desormais le **type** de l'exception. httpx leve
  des depassements de delai dont le message est vide, ce qui produisait des logs
  du genre "Appel a Ollama echoue :", sans aucune valeur de diagnostic.

## [Non publie] - M1, ticket 10 : pipeline d'ingestion
### Ajoute
- Chaine complete `charger -> assainir -> decouper -> vectoriser -> indexer`,
  avec un point d'entree CLI :
  `python -m aisecassist.ingestion.pipeline data/corpus`.
- `loader` : liste blanche d'extensions et plafond de taille verifie **avant**
  lecture, refus des contenus non decodables.
- `cleaner` : normalisation NFKC, suppression des caracteres de largeur nulle,
  des marques bidirectionnelles et des caracteres de controle. Comptage des
  invisibles retires, remonte dans le rapport d'ingestion.
- `chunker` : fenetre glissante pure, avec garde-fou contre un recouvrement
  superieur ou egal a la taille du fragment, qui bouclerait indefiniment.
- `IngestionReport` : chaque document ecarte est nomme avec sa raison, jamais
  simplement compte.
- **Naissance de `tests/security/`**, nomme par identifiant de la matrice :
  `test_sec13_ingestion_limits.py` et `test_sec04_sanitation.py`.
- Corpus de reference dans `data/corpus/` : syntheses OWASP LLM Top 10,
  MITRE ATLAS et NIST AI RMF, avec un README qui trace leur provenance.
- Test d'integration ingerant le vrai corpus dans le vrai Qdrant.
- Parametres `chunk_size`, `chunk_overlap` et `max_document_bytes`.

### Securite
- **SEC-13 passe a vert en CI.** Fichier surdimensionne, extension hors liste
  blanche et binaire deguise sont refuses, et le pipeline poursuit en nommant
  les documents ecartes.
- **SEC-04 passe a partiel.** La sanitation est faite et testee ; l'isolement
  au retrieval depend de la delimitation du contexte (ticket 12).

## [Non publie] - M1, ticket 9 : base vectorielle Qdrant
### Ajoute
- Interface `VectorStore` (`ensure_collection`, `add`, `search`) et dataclass
  `SearchResult` {text, source, score}.
- Implementation `QdrantVectorStore`, client injectable.
- `ensure_collection` idempotent, qui leve `CollectionDimensionMismatchError`
  si la collection existe avec une autre dimension au lieu de degrader la
  recherche en silence.
- Provenance obligatoire : chaque point porte `text` et `source` en payload, et
  un point sans provenance exploitable est refuse a la lecture plutot que rendu
  avec des valeurs par defaut.
- Identifiants de points derives de (source, texte) : re-ingerer un corpus met
  a jour au lieu de dupliquer.
- Controle d'alignement dans `add` : des sequences de longueurs differentes
  associeraient un extrait a la provenance d'un autre.
- 12 tests unitaires sur un Qdrant en memoire, plus 2 tests d'integration
  contre le conteneur, dont la chaine complete MiniLM puis indexation puis
  recherche semantique.
- Parametres `qdrant_url` et `qdrant_collection`, refletes dans `.env.example`.

### Modifie
- `docker-compose.yml` : service Qdrant active, image epinglee en v1.18.3,
  healthcheck, `depends_on` conditionne a la sante du service, et bloc
  `volumes` remis en fin de fichier.

## [Non publie] - M1, ticket 8 : interfaces LLM et embeddings
### Ajoute
- Interface `LLMProvider` (`complete`, `stream`) et son implementation
  `OllamaProvider`, avec client HTTP injectable pour des tests sans reseau.
- Interface `Embedder` (`embed`, `dimension`) et son implementation
  `SentenceTransformerEmbedder` (all-MiniLM-L6-v2, chargement paresseux,
  vectorisation deportee hors de la boucle d'evenements).
- Garde-fou de dimension : un modele dont la dimension differe de la
  configuration leve `DimensionMismatchError` au lieu de degrader la recherche
  en silence.
- Erreurs typees `LLMError`, `EmbedderError` : les exceptions des bibliotheques
  tierces ne remontent pas au metier.
- Parametres de configuration pour Ollama et les embeddings, refletes dans
  `.env.example`.
- Marqueur pytest `integration`, exclu par defaut : tests contre le vrai serveur
  Ollama et le vrai modele MiniLM, lances avec `pytest -m integration`.
- ADR-0008 : interfaces asynchrones des M1.

### Modifie
- Plancher Python releve de 3.11 a 3.12 : les stubs de numpy, tire par
  sentence-transformers, exigent la syntaxe PEP 695.
- `httpx` passe des dependances de dev aux dependances d'execution.
- Tests reorganises en `tests/unit/` et `tests/integration/` (CLAUDE.md 5).
- CI : cache pip active, le telechargement de torch n'etant pas repete a chaque job.
- CI : gitleaks lance via son binaire epingle plutot que via gitleaks-action@v2,
  cassee par la migration forcee des runners GitHub de Node 20 vers Node 24.
  Meme binaire et meme version qu'en pre-commit, donc meme verdict des deux cotes.

## [Non publie] - Consolidation avant M1
### Ajoute
- Documentation de conception rapatriee dans le depot : ARCHITECTURE, BUILD_PLAN,
  DESIGN, SECURITY et ADR-0002 a ADR-0007 (les ADR sont desormais contigus 0000-0007).
- Scans securite en CI : gitleaks (secrets), pip-audit (dependances), bandit (SAST).
- gitleaks en pre-commit comme garde-fou local, conformement a ARCHITECTURE.md.
- Colonne "Statut" dans la matrice de tests de SECURITY.md : tableau de bord
  verifiable de la couverture securite, mis a jour par la PR qui implemente la barriere.

### Modifie
- Environnement de dev aligne sur la CI en Python 3.12 (via uv).
- Dockerfile : l'API ne s'execute plus en root (utilisateur `appuser`).
- pre-commit : retrait de `ruff-format`, black reste le seul formateur.
- Revisions pre-commit epinglees sur les versions courantes.

## [0.1.0] - M0 : fondations
- Squelette FastAPI avec endpoint /health
- Qualite : ruff, black, mypy, pre-commit
- CI GitHub Actions (lint + types + tests)
- Conteneurisation Docker + docker-compose
- ADR-0001 : choix de la stack technique
