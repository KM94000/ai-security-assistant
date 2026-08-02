# ADR-0001 : Choix de la stack technique

- Statut : accepté
- Date : 2026-08-03

## Contexte
On construit une plateforme RAG + agents pour la cybersecurite, pensee comme
un produit de production : deployable, testee, observable, securisee. Budget
etudiant (priorite au gratuit), developpee en solo.

## Decision
- API : FastAPI (async, streaming, doc OpenAPI auto) sur Uvicorn.
- LLM : Ollama en dev (local, gratuit), derriere une interface `LLMProvider`
  permettant de basculer vers OpenAI/Azure en production sans toucher au reste.
- Base vectorielle : Qdrant (dediee, conteneurisable).
- Agents : LangGraph / LangChain.
- Qualite : ruff, black, mypy, pre-commit, pytest.
- CI/CD : GitHub Actions.
- Conteneurs : Docker + docker-compose. Kubernetes NON retenu (voir ci-dessous).
- Deploiement : Render / Railway (offre gratuite).

## Alternatives envisagees
- Kubernetes : ecarte. Complexite disproportionnee pour un service solo ; un
  monolithe bien conteneurise couvre le besoin. La comprehension de K8s est
  documentee, le cluster n'est pas monte.
- Flask : ecarte au profit de FastAPI (async + validation pydantic + OpenAP natif).

## Consequences
- Environnement reproductible et deployable des M0.
- Cout quasi nul en dev grace a Ollama et aux offres gratuites.
- L'abstraction LLMProvider ajoute un peu de code mais evite un couplage fort
  a un fournisseur — choix de conception assume (inversion de dependance).
