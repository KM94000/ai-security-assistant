# Changelog

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
