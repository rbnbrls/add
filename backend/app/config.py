from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./add.db"
    api_cors_origins: str = "http://localhost:3000"
    add_api_token: str = "change-me"
    local_login_password: str = ""
    session_secret: str = "change-this-session-secret"
    secure_cookies: bool = False
    credential_encryption_key: str = ""
    ha_webhook_url: str = ""
    ha_webhook_token: str = ""
    ha_context_url: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 30
    llm_credential_provider: str = "llm"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
