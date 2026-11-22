"""Application settings loaded from environment variables / .env.

All secrets come from the environment. Nothing here is logged in full.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.plans import PLANS, REQUESTABLE_PLANS, limits_of

_PLACEHOLDER_DOMAINS = ("@example.com", "@example.org", "@example.net", "replace-with")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "Provenance"
    # Public origin for the sitemap and robots.txt, e.g. https://provenance.example; empty uses the
    # request's own host.
    public_base_url: str = ""
    # Browser origins allowed to call the API directly (comma-separated); empty means same-origin
    # only. Keys belong on a server, so most deployments leave this empty.
    cors_allow_origins: str = ""
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "sqlite:///./dev.sqlite3"

    # SEC fair-access settings
    sec_user_agent: str = ""
    sec_min_request_interval_seconds: float = 0.25
    # one budget for every process on this machine that uses the contact UA (SEC allows 10/s)
    sec_max_requests_per_second: float = 8.0  # 0 turns the machine-wide limit off
    sec_rate_file: str = "~/.cache/provenance/sec-rate"
    sec_timeout_seconds: float = 20.0
    sec_max_retries: int = 5
    sec_max_response_bytes: int = 50 * 1024 * 1024
    sec_cache_dir: str = ".sec_cache"
    # single-run locks used without PostgreSQL (PostgreSQL uses advisory locks)
    poll_lock_file: str = ".poll_sec.lock"
    markets_lock_file: str = ".markets_daily.lock"
    tracker_lock_file: str = ".track_filings.lock"
    sec_base_data_url: str = "https://data.sec.gov"
    sec_base_www_url: str = "https://www.sec.gov"
    sec_live_tests: bool = False
    # Nightly SEC bulk archives (all filers in two downloads); stored here between runs
    sec_bulk_dir: str = ".sec_bulk"
    sec_bulk_max_bytes: int = 6 * 1024 * 1024 * 1024

    ingestion_poll_interval_seconds: int = 300
    current_8k_poll_seconds: int = 45  # scripts/poll_current_8k.py (officer changes, ticket 20)
    # Newly detected filings older than this are treated as backfill and never notified
    notify_max_filing_age_days: int = 30
    # Universe (bulk coverage) settings
    universe_refresh_interval_seconds: int = 6 * 3600
    universe_request_budget_per_run: int = 400
    universe_max_consecutive_failures: int = 10
    sec_filings_history_pages: int = 0
    freshness_stale_after_seconds: int = 24 * 3600
    on_demand_ingestion_enabled: bool = True
    # International listings (Canada/Europe/UK) sources
    markets_user_agent: str = ""  # defaults to SEC_USER_AGENT
    markets_timeout_seconds: float = 60.0
    markets_cache_dir: str = ".markets_cache"
    markets_sources_enabled: str = (
        "esma_firds,fca_firds,gleif"  # comma list; exchange adapters opt-in
    )
    markets_firds_days_back: int = 3
    markets_gleif_lookups_per_run: int = 50  # API calls of up to 200 LEIs each
    markets_gleif_refresh_days: int = 30
    # Daily scheduler: the poller runs all enabled sources once per UTC day after this hour
    # (ESMA and FCA publish deltas by 09:00 CET/UTC). Set false where a platform cron runs it.
    # Connections graph (ADR 0011): new insider data sets and showcase sources, once a day
    connections_daily_enabled: bool = True
    # Filings tracker (ADR 0012): EDGAR's latest filings every hour, the daily index once a day;
    # refreshes covered companies and adds companies going public
    filings_tracker_enabled: bool = True
    filings_tracker_interval_seconds: int = 3600
    filings_tracker_feed_pages: int = 25  # 100 filings a page; the feed keeps about 2,000
    filings_tracker_max_companies: int = 1500  # refreshed or added per run; the rest wait
    markets_daily_enabled: bool = True
    markets_daily_hour_utc: int = 10
    # Public demo key ("demo"): read-only endpoints, showcase companies, small pages, per-IP limits
    demo_key_enabled: bool = True
    demo_rate_limit_per_minute: int = 20
    demo_requests_per_day: int = 300
    demo_requests_per_minute_all: int = 1200  # all demo callers together; 0 turns it off
    demo_max_limit: int = 10
    # Event feed (ADR 0007): rows reach readers only after settling, so no committed event is
    # skipped by a reader that has already moved past its publication time.
    events_settle_seconds: float = 5.0
    events_stream_poll_seconds: float = 2.0
    events_stream_heartbeat_seconds: float = 15.0
    events_stream_max_seconds: float = 900.0
    events_max_since_days: int = 30
    # Local language model (Ollama API) for the company-intelligence chat and extraction.
    # Off by default; the chat still returns the deterministic brief without it.
    llm_enabled: bool = False
    # "ollama" (a model on our own host) or "openai" (any OpenAI-compatible chat completions API,
    # e.g. a hosted model; set LLM_BASE_URL to its /v1 root and LLM_API_KEY). GH #13.
    llm_provider: Literal["ollama", "openai"] = "ollama"
    llm_api_key: str = ""
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:4b-instruct"
    llm_timeout_seconds: float = 90.0
    llm_max_answer_tokens: int = 700
    # Prompt window; prospectus passages need more than Ollama's default.
    llm_context_tokens: int = 8192
    # Forecasts: a reasoning model thinks over the figures, filings and news before answering.
    llm_reasoning_model: str = "qwen3:30b-a3b"
    llm_reasoning_timeout_seconds: float = 300.0
    llm_reasoning_tokens: int = 2500
    # Headlines for forecasts (Google News RSS; personal, non-commercial use only).
    news_enabled: bool = True
    # "google_rss" is personal, non-commercial use only (development); "gdelt" is the GDELT
    # Project's open index, free for commercial use with attribution (production). GH #14.
    news_provider: Literal["google_rss", "gdelt"] = "google_rss"
    news_cache_dir: str = ".news_cache"
    news_cache_hours: float = 6.0
    news_timeout_seconds: float = 10.0
    chat_rate_limit_per_minute: int = 10
    # Questions a day per key (or per address for the demo key): every answer can run a model.
    chat_requests_per_day: int = 200
    # Public statistics are served from a stored snapshot (P-01), refreshed in the background
    # by the web process every N seconds (0: only the poller refreshes it).
    stats_refresh_seconds: int = 45
    # Accounts (GH #15): one-time sign-in links by email, then a session cookie.
    sign_in_link_minutes: int = 15
    account_session_days: int = 30
    sign_in_per_email_per_hour: int = 5
    sign_in_per_ip_per_hour: int = 20
    account_max_active_keys: int = 100  # ceiling; the plan sets the real number (G-01)
    # Read 8-K item 5.02 text from EDGAR when a chat question needs it (needs SEC_USER_AGENT).
    officer_extraction_enabled: bool = True
    # Read a company's latest S-1/F-1 prospectus from EDGAR when a chat question needs it.
    prospectus_reading_enabled: bool = True
    # POC (issue #7): clean chatbot residue from model answers (blader/humanizer patterns).
    chat_humanize: bool = True
    # Public website showcase: explicit CIK list, or the most recently filed ingested companies
    public_showcase_ciks: str = ""
    public_showcase_limit: int = 12

    # Security
    api_key_pepper: str = ""
    webhook_signing_secret: str = ""
    admin_token: str = ""

    # Limits
    max_export_rows: int = 1000
    default_rate_limit_per_minute: int = 60
    # per-address limits on the keyless endpoints; 0 keeps the built-in value (public 60, stats
    # 30). A load test from one address raises them on its own instance only.
    public_rate_limit_per_minute: int = 0
    stats_rate_limit_per_minute: int = 0
    default_monthly_request_quota: int = 10_000

    # Webhooks
    webhook_timeout_seconds: float = 5.0
    webhook_max_attempts: int = 6
    webhook_retry_base_seconds: float = 30.0
    webhook_allow_private_destinations: bool = False

    # Email (optional)
    # "console" logs messages instead of sending them: development only, never in production.
    email_provider: Literal["none", "smtp", "console"] = "none"
    email_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    # Where rate-limit counters live: "auto" (the database on PostgreSQL, so replicas share
    # them), "memory" (per process) or "database".
    rate_limit_store: str = "auto"
    # Operator alerts (Slack or Discord incoming webhook); empty sends nothing.
    alert_webhook_url: str = ""
    alert_repeat_seconds: int = 3600
    # The poller purges old usage, deliveries and rate-limit windows once a UTC day.
    retention_enabled: bool = True
    usage_retention_days: int = 90
    delivery_retention_days: int = 90

    @field_validator("sec_user_agent")
    @classmethod
    def _validate_user_agent(cls, v: str) -> str:
        return v.strip()

    @property
    def email_configured(self) -> bool:
        return self.email_provider == "smtp" and bool(self.smtp_host and self.email_from)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_for_runtime(self) -> list[str]:
        """Return a list of human-readable configuration problems (no secret values)."""
        problems: list[str] = []
        if not self.sec_user_agent or "contact=" not in self.sec_user_agent:
            problems.append("SEC_USER_AGENT must be set and include 'contact=<email>'")
        elif any(d in self.sec_user_agent.lower() for d in _PLACEHOLDER_DOMAINS):
            problems.append(
                "SEC_USER_AGENT contact address is a placeholder; use a monitored mailbox"
            )
        if not self.api_key_pepper or len(self.api_key_pepper) < 16:
            problems.append("API_KEY_PEPPER must be set to a random secret of at least 16 chars")
        if not self.webhook_signing_secret or len(self.webhook_signing_secret) < 16:
            problems.append(
                "WEBHOOK_SIGNING_SECRET must be set to a random secret of at least 16 chars"
            )
        if self.is_production and self.database_url.startswith("sqlite"):
            problems.append("SQLite is not supported in production; use PostgreSQL")
        if self.is_production and self.webhook_allow_private_destinations:
            problems.append("WEBHOOK_ALLOW_PRIVATE_DESTINATIONS must be false in production")
        if self.llm_enabled and self.llm_provider == "openai" and not self.llm_api_key:
            problems.append("LLM_PROVIDER=openai needs LLM_API_KEY")
        if self.is_production and self.news_enabled and self.news_provider == "google_rss":
            problems.append("NEWS_PROVIDER=google_rss is non-commercial; use gdelt in production")
        if self.is_production and self.email_provider == "console":
            problems.append("EMAIL_PROVIDER=console is for development; use smtp in production")
        return problems


# Limits per plan come from app/core/plans.py, the one source of truth (launch plan G-01).
PLAN_LIMITS: dict[str, dict[str, int]] = {name: limits_of(name) for name in PLANS}
PLAN_NAMES = tuple(PLAN_LIMITS)
SELF_SERVE_PLANS = REQUESTABLE_PLANS


def plan_limits(plan: str, settings: Settings) -> dict[str, int]:
    base = dict(PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]))
    if plan == "free":
        base["rate_limit_per_minute"] = settings.default_rate_limit_per_minute
        base["monthly_request_quota"] = settings.default_monthly_request_quota
    base["max_export_rows"] = min(base["max_export_rows"], settings.max_export_rows)
    return base


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = [
    "Settings",
    "get_settings",
    "plan_limits",
    "PLAN_LIMITS",
    "PLAN_NAMES",
    "SELF_SERVE_PLANS",
    "Field",
]
