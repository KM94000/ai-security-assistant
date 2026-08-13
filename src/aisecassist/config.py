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

    # --- Embeddings (ADR-0006 : all-MiniLM-L6-v2) ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # La dimension est un paramètre, jamais une valeur en dur : elle doit rester
    # cohérente avec la collection Qdrant, créée pour cette même dimension.
    # Changer de modèle impose de recréer la collection et de ré-ingérer.
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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
