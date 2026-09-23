from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Paramètres de l'application, chargés depuis l'environnement ou un .env.

    Aucune valeur sensible n'est écrite en dur : tout passe par l'environnement.

    Les contraintes portées par les champs ne sont pas décoratives. Ces valeurs
    viennent de l'extérieur, et une faute de frappe dans un `.env` doit faire
    échouer le démarrage — pas produire une panne d'exécution trois couches plus
    bas, dont le message ne nomme même pas la variable en cause.
    """

    app_name: str = "AI Security Assistant"
    environment: str = "development"

    # --- LLM (ADR-0003 : Ollama en local) ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    # 120 s et non 60 : le premier appel a un Ollama local paie le chargement du
    # modele en memoire, ce qui depasse largement une minute sur CPU. La valeur
    # est dimensionnee pour ce demarrage a froid, pas pour le regime nominal.
    # En production derriere un fournisseur heberge, une valeur bien plus basse
    # est attendue — c'est precisement pourquoi c'est un parametre.
    llm_timeout_s: float = Field(default=120.0, gt=0)

    # --- Embeddings (ADR-0010 : granite-embedding-107m-multilingual) ---
    # Multilingue et entraîné pour la recherche : le corpus et les questions sont
    # en français, et un modèle anglais y écrasait l'écart entre pertinent et
    # hors sujet (mesures dans l'ADR-0010).
    embedding_model: str = "ibm-granite/granite-embedding-107m-multilingual"
    # Révision épinglée des poids. Le seuil de pertinence est calibré sur ces
    # poids précis : une mise à jour silencieuse du dépôt déplacerait les scores
    # sans que rien ne le signale. C'est aussi une protection de la chaîne
    # d'approvisionnement (LLM03).
    embedding_model_revision: str = Field(
        default="d6cffd338414d6a1c1f5decfad5fec62eebc90d5", min_length=1
    )
    # La dimension est un paramètre, jamais une valeur en dur : elle doit rester
    # cohérente avec la collection Qdrant, créée pour cette même dimension.
    # Changer de modèle impose de recréer la collection et de ré-ingérer — même à
    # dimension égale, ce que la collection vérifie (ADR-0010).
    embedding_dimension: int = Field(default=384, gt=0)

    # --- Base vectorielle (ADR-0005 : Qdrant) ---
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "aisec_docs"

    # --- Ingestion ---
    chunk_size: int = Field(default=800, gt=0)
    chunk_overlap: int = Field(default=120, ge=0)
    # Plafond de taille d'un document (SEC-13). Verifie avant toute lecture :
    # controler apres coup ne protegerait de rien, le mal etant deja fait.
    max_document_bytes: int = Field(default=2_000_000, gt=0)

    # --- Recherche ---
    retrieval_top_k: int = Field(default=5, gt=0)
    # Similarité cosinus minimale pour qu'un extrait soit retenu (ADR-0010). Sans
    # elle, la recherche renvoie toujours k extraits, même hors sujet, et le refus
    # « le corpus ne contient rien » ne se déclenche jamais.
    #
    # Valeur mesurée, pas choisie : elle ne vaut que pour le modèle et la révision
    # ci-dessus. Changer de modèle impose de la recalibrer —
    # `tests/integration/test_retrieval_relevance.py` échoue sinon, en affichant
    # les scores nécessaires.
    retrieval_min_score: float = Field(default=0.64, ge=-1.0, le=1.0)

    # --- Agent (M3) ---
    # Nombre maximal de tours d'outils avant que l'agent ne soit coupé (SEC-06).
    # Sans plafond, un agent qui ne trouve rien relance indéfiniment : c'est un
    # déni de service qu'on s'inflige, et la facture d'inférence avec.
    agent_max_iterations: int = Field(default=3, gt=0)

    # --- Generation ---
    # Plafond de longueur d'une reponse (SEC-10). En streaming surtout : une
    # generation qui part en boucle produirait des fragments indefiniment, et
    # rien du cote client ne l'arreterait. Le plafond est applique cote serveur,
    # ou il protege reellement.
    max_answer_chars: int = Field(default=8_000, gt=0)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def embedding_model_id(self) -> str:
        """Identifie l'espace vectoriel : le modèle et la révision exacte de ses poids.

        C'est cette valeur que la collection enregistre et vérifie. Deux révisions
        d'un même modèle ne produisent pas des vecteurs identiques ; les mélanger
        dans une collection dégraderait la recherche sans erreur visible.
        """
        return f"{self.embedding_model}@{self.embedding_model_revision}"

    @model_validator(mode="after")
    def _verifier_la_coherence_du_decoupage(self) -> "Settings":
        """Refuse un recouvrement qui empêcherait la fenêtre de découpage d'avancer.

        `chunk_text` lève déjà cette erreur, mais au premier document ingéré —
        c'est-à-dire potentiellement des heures après le démarrage. La détecter
        ici la ramène au chargement de la configuration, là où on peut encore
        nommer la variable fautive.
        """
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"CHUNK_OVERLAP ({self.chunk_overlap}) doit être strictement inférieur à "
                f"CHUNK_SIZE ({self.chunk_size}) : sinon le découpage ne progresse pas."
            )
        return self


settings = Settings()
