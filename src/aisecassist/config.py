from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Paramètres de l'application, chargés depuis l'environnement ou un .env.

    Aucune valeur sensible n'est écrite en dur : tout passe par l'environnement.
    """

    app_name: str = "AI Security Assistant"
    environment: str = "development"

    # --- LLM (ADR-0003 : Ollama en local) ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    llm_timeout_s: float = 60.0

    # --- Embeddings (ADR-0006 : all-MiniLM-L6-v2) ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # La dimension est un paramètre, jamais une valeur en dur : elle doit rester
    # cohérente avec la collection Qdrant, créée pour cette même dimension.
    # Changer de modèle impose de recréer la collection et de ré-ingérer.
    embedding_dimension: int = 384

    # --- Base vectorielle (ADR-0005 : Qdrant) ---
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "aisec_docs"

    # --- Ingestion ---
    chunk_size: int = 800
    chunk_overlap: int = 120
    # Plafond de taille d'un document (SEC-13). Verifie avant toute lecture :
    # controler apres coup ne protegerait de rien, le mal etant deja fait.
    max_document_bytes: int = 2_000_000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
