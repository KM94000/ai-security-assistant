from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Paramètres de l'application, chargés depuis l'environnement ou un .env.

    Aucune valeur sensible n'est écrite en dur : tout passe par l'environnement.
    """

    app_name: str = "AI Security Assistant"
    environment: str = "development"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
