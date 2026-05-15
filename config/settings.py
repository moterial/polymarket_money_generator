"""Polymarket Money Generator - Configuration"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class APIConfig:
    clob_url: str = os.getenv("POLYMARKET_API_URL", "https://clob.polymarket.com")
    gamma_url: str = os.getenv("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com")
    ws_url: str = os.getenv("POLYMARKET_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws")
    private_key: str = os.getenv("POLYMARKET_PRIVATE_KEY", "")
    api_key: str = os.getenv("POLYMARKET_API_KEY", "")
    api_secret: str = os.getenv("POLYMARKET_API_SECRET", "")
    api_passphrase: str = os.getenv("POLYMARKET_API_PASSPHRASE", "")


@dataclass
class ScannerConfig:
    interval_seconds: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))
    min_arbitrage_edge_pct: float = float(os.getenv("MIN_ARBITRAGE_EDGE_PCT", "1.0"))
    min_liquidity_usd: float = float(os.getenv("MIN_LIQUIDITY_USD", "500"))
    max_position_size_usd: float = float(os.getenv("MAX_POSITION_SIZE_USD", "1000"))


@dataclass
class RiskConfig:
    var_confidence: float = float(os.getenv("VAR_CONFIDENCE", "0.99"))
    max_portfolio_var_usd: float = float(os.getenv("MAX_PORTFOLIO_VAR_USD", "5000"))
    garch_lookback_days: int = int(os.getenv("GARCH_LOOKBACK_DAYS", "30"))


@dataclass
class AIConfig:
    openai_api_key: str = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    base_url: str = os.getenv("LLM_BASE_URL", "")
    model: str = os.getenv("LLM_MODEL_NAME", os.getenv("OPENAI_MODEL", "gpt-4o"))


@dataclass
class DashboardConfig:
    refresh_seconds: int = int(os.getenv("DASHBOARD_REFRESH_SECONDS", "5"))


@dataclass
class Settings:
    api: APIConfig = field(default_factory=APIConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)


settings = Settings()
