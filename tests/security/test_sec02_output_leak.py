"""SEC-02 — fuite d'information sensible dans la reponse.

Reference : docs/SECURITY.md, matrice section 6.

**Portee exacte.** Ce fichier teste le guardrail de sortie : ce qui a une forme
reconnaissable de secret est redige avant d'atteindre le client, sur les deux
chemins — reponse complete et flux.

Il ne teste pas que le modele **refuse** de divulguer : c'est un comportement,
mesure en M5 avec un canari plante (SEC-03). Et le guardrail est incomplet par
construction : un mot de passe en clair au milieu d'une phrase passera. Il
reduit la surface, il ne la ferme pas — le presenter autrement serait faux.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import pytest

from aisecassist.llm.base import LLMProvider
from aisecassist.security.output_guardrail import (
    LONGUEUR_MAX_MOTIF,
    REMPLACEMENT,
    StreamRedactor,
    redact,
)
from tests.doubles import StreamingLLM, extrait, make_generation

pytestmark = pytest.mark.anyio

# En-tete PEM assemblee a l'execution. Ecrite en clair, elle declencherait le
# hook pre-commit `detect-private-key`, qui n'offre aucune derogation en ligne.
# La composer garde le hook actif sur l'ensemble du fichier — l'alternative,
# exclure ce fichier de la verification, le desarmerait precisement la ou des
# valeurs a forme de secret sont attendues.
_ENTETE_PEM = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"

_SECRETS = [
    ("cle privee", _ENTETE_PEM),
    ("cle de fournisseur", "sk-abcdefghijklmnopqrstuvwxyz012345"),
    ("cle aws", "AKIAIOSFODNN7EXAMPLE"),
    ("jeton github", "ghp_" + "a" * 36),
    ("en-tete bearer", "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"),
    # La derogation ci-dessous est posee ligne a ligne, et non sur le
    # repertoire : exempter tout tests/security/ laisserait passer un vrai
    # secret depose la par accident. Chaque exemption reste ainsi un acte
    # delibere, visible en relecture.
    ("affectation de secret", 'api_key = "s3cr3t_val_de_test_1234"'),  # gitleaks:allow
]


# --- Le guardrail lui-meme --------------------------------------------------


@pytest.mark.parametrize(("categorie", "secret"), _SECRETS)
def test_chaque_forme_de_secret_est_redigee(categorie: str, secret: str) -> None:
    resultat = redact(f"Voici la valeur : {secret} — fin.")

    assert secret not in resultat.text
    assert REMPLACEMENT in resultat.text
    assert categorie in resultat.categories


def test_un_texte_ordinaire_nest_pas_touche() -> None:
    """Un guardrail qui redige du contenu legitime devient vite desactive."""
    texte = (
        "L'injection indirecte passe par un document ingere. La remediation "
        "consiste a delimiter le contexte et a assainir le corpus."
    )

    resultat = redact(texte)

    assert resultat.text == texte
    assert resultat.categories == ()


def test_les_categories_ne_contiennent_jamais_la_valeur() -> None:
    """Journaliser un secret pour dire qu'on l'a bloque le divulgue une seconde fois."""
    secret = "sk-abcdefghijklmnopqrstuvwxyz012345"

    resultat = redact(f"cle : {secret}")

    assert all(secret not in categorie for categorie in resultat.categories)


def test_un_litteral_signale_est_retire() -> None:
    """Sert au nonce : le modele n'a aucune raison de le restituer."""
    resultat = redact("le marqueur est deadbeef1234", literaux=("deadbeef1234",))

    assert "deadbeef1234" not in resultat.text
    assert "marqueur interne" in resultat.categories


# --- Redaction en flux ------------------------------------------------------


def test_un_secret_a_cheval_sur_deux_fragments_est_redige() -> None:
    """Le piege propre au streaming.

    Rediger chaque fragment independamment ne verrait rien, et le client
    reconstituerait le secret en concatenant.
    """
    redacteur = StreamRedactor()
    secret = "sk-abcdefghijklmnopqrstuvwxyz012345"
    remplissage = "texte anodin. " * 20

    sortie = redacteur.feed(remplissage + secret[:10])
    sortie += redacteur.feed(secret[10:] + " suite de la reponse.")
    sortie += redacteur.flush()

    assert secret not in sortie
    assert REMPLACEMENT in sortie


def test_le_flux_restitue_integralement_un_texte_sans_secret() -> None:
    """La retenue ne doit rien perdre : ce qui entre doit ressortir."""
    redacteur = StreamRedactor()
    morceaux = [f"fragment {i} " for i in range(40)]

    sortie = "".join(redacteur.feed(m) for m in morceaux) + redacteur.flush()

    assert sortie == "".join(morceaux)


def test_rien_nest_emis_avant_que_la_fenetre_ne_soit_depassee() -> None:
    """Garantie de la retenue : un secret encore incomplet ne peut pas fuir."""
    redacteur = StreamRedactor()

    assert redacteur.feed("a" * (LONGUEUR_MAX_MOTIF - 1)) == ""


def test_la_fenetre_couvre_la_plus_longue_correspondance_possible() -> None:
    """Non-regression structurelle.

    Si un motif s'allonge sans que `LONGUEUR_MAX_MOTIF` suive, la retenue
    devient trop courte et un secret a cheval passerait.
    """
    from aisecassist.security.output_guardrail import _MOTIFS

    pire_cas = (
        _ENTETE_PEM + " "
        "sk-" + "a" * 64 + " "
        "AKIAIOSFODNN7EXAMPLE "
        "ghp_" + "b" * 36 + " "
        "Bearer " + "c" * 64 + " "
        'api_key = "' + "d" * 64 + '"'
    )

    for _, motif in _MOTIFS:
        for correspondance in motif.finditer(pire_cas):
            longueur = correspondance.end() - correspondance.start()
            assert longueur < LONGUEUR_MAX_MOTIF, f"{motif.pattern} peut matcher {longueur} car."


# --- Bout en bout, via le service ------------------------------------------


async def test_un_secret_produit_par_le_modele_natteint_pas_le_client() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz012345"
    service = make_generation(StreamingLLM([f"La cle est {secret} voila."]))

    resultat = await service.answer("question", [extrait("contenu")])

    assert secret not in resultat.answer
    assert REMPLACEMENT in resultat.answer


async def test_le_chemin_streame_offre_la_meme_protection() -> None:
    """Une protection asymetrique est un contournement, pas une protection.

    Proteger `/query` et pas `/query/stream` reviendrait a documenter la porte
    de sortie dans l'OpenAPI.
    """
    secret = "AKIAIOSFODNN7EXAMPLE"
    morceaux = ["Reponse longue. " * 10, f"Cle : {secret} ", "fin de la reponse."]
    service = make_generation(StreamingLLM(morceaux))

    texte = "".join([f async for f in service.stream_answer("question", [extrait("c")])])

    assert secret not in texte
    assert REMPLACEMENT in texte


async def test_le_nonce_de_delimitation_ne_ressort_jamais() -> None:
    """Le modele n'a aucune raison de restituer la cloture du contexte.

    La laisser passer revelerait sa structure a qui cherche a la forger. Le
    double ci-dessous reproduit le scenario exact : il lit le nonce dans le
    prompt qu'il recoit et le recrache dans sa reponse.
    """

    class _LLMBavard(LLMProvider):
        def __init__(self) -> None:
            self.nonce_vu = ""

        async def complete(self, prompt: str) -> str:
            correspondance = re.search(r"===CONTEXTE-([0-9a-f]{32})===", prompt)
            assert correspondance, "cloture introuvable dans le prompt"
            self.nonce_vu = correspondance.group(1)
            return f"Mon marqueur interne est {self.nonce_vu}, au fait."

        async def stream(self, prompt: str) -> AsyncIterator[str]:
            yield await self.complete(prompt)

    llm = _LLMBavard()
    service = make_generation(llm)

    resultat = await service.answer("question", [extrait("contenu")])

    assert llm.nonce_vu, "le double n'a pas vu de nonce"
    assert llm.nonce_vu not in resultat.answer
    assert REMPLACEMENT in resultat.answer
