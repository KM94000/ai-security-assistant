# Corpus de reference

Documents ingeres par le pipeline (`python -m aisecassist.ingestion.pipeline data/corpus`).

> Cette note vit dans `data/` et non dans `data/corpus/` : le chargeur ingere
> **tout** fichier du repertoire cible. Laissee a l'interieur, elle etait
> vectorisee au meme titre que les referentiels, et pouvait etre citee comme
> source d'une reponse de cybersecurite. `data/corpus/` ne contient que du
> contenu destine a etre interroge.

## Provenance

Ces fichiers sont des **syntheses redigees pour ce projet**, pas des copies des
documents originaux. Ils resument les referentiels publics ci-dessous et servent
de corpus de demarrage pour M1 :

| Fichier | Referentiel resume |
|---|---|
| `owasp-llm-top10.md` | OWASP Top 10 for LLM Applications (2025) |
| `mitre-atlas.md` | MITRE ATLAS — tactiques et techniques adverses contre l'IA |
| `nist-ai-rmf.md` | NIST AI Risk Management Framework (AI RMF 1.0) |

## Pourquoi la provenance est tracee

Chaque fragment indexe porte le nom de son fichier source (`SearchResult.source`).
C'est ce qui permet de citer l'origine d'une reponse, et de remonter d'un contenu
suspect jusqu'au document qui l'a introduit dans le corpus.

Un corpus dont on ignore l'origine est un corpus qu'on ne peut pas auditer. Tout
ajout ici doit venir avec sa ligne dans le tableau ci-dessus.

## Regles d'ingestion

Le chargeur n'accepte que `.md` et `.txt`, sous un plafond de taille
(`MAX_DOCUMENT_BYTES`). Tout document ecarte est nomme dans le rapport
d'ingestion, jamais ignore en silence.
