import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    github_token: str = os.getenv("GITHUB_TOKEN", "")

    llm_model: str = "llama-3.3-70b-versatile"
    fallback_llm_model: str = "llama-3.1-8b-instant"  # used if primary hits Groq rate limit

    max_sub_questions: int = 4
    sources_per_query: int = 5
    min_relevance_score: float = 0.6  # LLM-scored relevance threshold, 0-1

    # Parallel Send() fan-out (4 sub-questions at once) means up to ~40
    # scoring calls can fire near-simultaneously, which blew through Groq's
    # 6000 TPM cap on both primary and fallback models under sustained load
    # (confirmed via eval_harness.py — hit at query 19 of 20). This semaphore
    # throttles concurrent LLM calls across ALL parallel branches combined.
    max_concurrent_llm_calls: int = 3

    # Self-correction loop: if aggregate_sources() ends up with fewer than
    # this many scored sources, broaden.py fires a single broader re-query
    # instead of letting the Writer synthesize a thin report.
    min_sources_threshold: int = 3
    max_retries: int = 1

    # CORS: comma-separated list, no wildcard in production. Include your
    # deployed frontend origin here once you have one.
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:5500,http://127.0.0.1:8000"

    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()