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
    #STT (faster-whisper, open-source/self-hosted; lazy-imported)
    stt_language: str = "auto"               # BCP-47 tag or "auto" (detect per file; enables kk routing)
    whisper_model: str = "large-v3-turbo"          # base multilingual model (ru/en strong, kk decent)
    whisper_kk_model: Optional[str] = None
    whisper_device: str = "auto"             # "auto" | "cpu" | "cuda"
    whisper_compute_type: str = "auto"       # "auto" | "int8" | "float16" | "int8_float16"
    hf_token: Optional[str] = None           # HuggingFace token for pyannote diarization (WhisperX mixed path)
    #Agent (LLM analysis via OpenAI or any OpenAI-compatible endpoint)
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: Optional[str] = None    # set for OpenAI-compatible providers (DeepSeek, Gemini-compat, ...)
    agent_output_language: str = "ru"

settings = Settings()
