from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

"""Central settings - reads env vars + .env. The only module that touches the environment."""

class Settings(BaseSettings):
    def require(self, name:str) -> str:
        value = getattr(self, name)
        if not value:
            raise RuntimeError(f"Missing required setting: set '{name.upper()}' in your .env file")
        return value

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    recordings_root:str = "./recordings" #the directory where the recordings will be saved
    #needed fields for capturing and transcribing
    google_application_credentials: Optional[str] = None
    google_impersonate_subject: Optional[str] = None
    capture_trigger: str = "poll"
    use_google_transcript: bool = True
    #STT
    speech_key: Optional[str] = None
    speech_region: Optional[str] = None
    stt_language: str = "ru-RU"
    stt_language_candidates: str = "ru-RU, kk-KZ, en-US"
    #Agent
    azure_openai_endpoint: Optional[str] = None
    azure_openai_key: Optional[str] = None
    azure_openai_deployment: Optional[str] = None
    agent_output_language: str = "ru"

settings = Settings()
