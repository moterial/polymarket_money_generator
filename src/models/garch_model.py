"""
GARCH Volatility Model

Implements GARCH(1,1) for prediction market volatility modeling.

From the article:
"After a major information event hits a contract, how long should you maintain
widened spreads before returning to normal quoting? The GARCH β₁ parameter
gives you that number mathematically."

GARCH(1,1): σ²ₜ = α₀ + α₁ε²ₜ₋₁ + β₁σ²ₜ₋₁

Key parameters:
- α₁: How much yesterday's shock affects today's variance
- β₁: How persistent is volatility (controls decay speed)
- Half-life = ln(2) / ln(α₁ + β₁): How long for a shock to decay by half
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from src.utils.data_models import PriceHistory
from src.utils.logger import setup_logger

logger = setup_logger("models.garch")


@dataclass
class GARCHResult:
    """GARCH(1,1) estimation results."""
    omega: float    # α₀: long-run variance constant
    alpha: float    # α₁: ARCH term (shock impact)
    beta: float     # β₁: GARCH term (persistence)
    long_run_variance: float
    half_life_periods: float
    current_volatility: float
    volatility_forecast: list[float]  # forecasted volatility for next N periods
    is_valid: bool = True


class GARCHModel:
    """
    GARCH(1,1) model for prediction market volatility.

    Uses maximum likelihood estimation or simplified method-of-moments
    when the arch library is not available.
    """

    def __init__(self, lookback_periods: int = 100):
        self.lookback_periods = lookback_periods

    def fit(
        self,
        price_history: PriceHistory,
        forecast_horizon: int = 10,
    ) -> Optional[GARCHResult]:
        """
        Fit GARCH(1,1) to price data and produce volatility forecasts.
        """
        if len(price_history.prices) < 20:
            return None

        prices = np.array(price_history.prices[-self.lookback_periods:])
        prices = np.clip(prices, 1e-6, 1.0 - 1e-6)

        # Log returns
        log_returns = np.diff(np.log(prices))

        if len(log_returns) < 15:
            return None

        # Try using the arch library first
        try:
            return self._fit_arch_library(log_returns, forecast_horizon)
        except ImportError:
            logger.debug("arch library not available, using MoM estimator")
        except Exception as e:
            logger.debug("arch library failed: %s, falling back to MoM", e)

        # Fallback: method of moments
        return self._fit_method_of_moments(log_returns, forecast_horizon)

    def _fit_arch_library(
        self,
        returns: np.ndarray,
        forecast_horizon: int,
    ) -> GARCHResult:
        """Fit using the arch library (proper MLE)."""
        from arch import arch_model

        # Scale returns for numerical stability
        scale = 100.0
        scaled_returns = returns * scale

        model = arch_model(scaled_returns, vol="Garch", p=1, q=1, dist="normal")
        result = model.fit(disp="off", show_warning=False)

        omega = result.params.get("omega", 0.01) / (scale ** 2)
        alpha = result.params.get("alpha[1]", 0.1)
        beta = result.params.get("beta[1]", 0.85)

        persistence = alpha + beta
        long_run_var = omega / (1 - persistence) if persistence < 1 else omega * 100
        half_life = np.log(2) / (-np.log(persistence)) if 0 < persistence < 1 else float("inf")

        # Current conditional variance
        current_var = result.conditional_volatility.iloc[-1] ** 2 / (scale ** 2)

        # Forecast
        forecasts = []
        var_t = current_var
        for _ in range(forecast_horizon):
            var_t = omega + persistence * var_t
            forecasts.append(float(np.sqrt(var_t)))

        return GARCHResult(
            omega=float(omega),
            alpha=float(alpha),
            beta=float(beta),
            long_run_variance=float(long_run_var),
            half_life_periods=float(half_life),
            current_volatility=float(np.sqrt(current_var)),
            volatility_forecast=forecasts,
        )

    def _fit_method_of_moments(
        self,
        returns: np.ndarray,
        forecast_horizon: int,
    ) -> GARCHResult:
        """
        Simple method-of-moments GARCH(1,1) estimator.

        Uses autocorrelation of squared returns to estimate parameters.
        Less accurate than MLE but works without external libraries.
        """
        T = len(returns)
        mean_return = np.mean(returns)
        residuals = returns - mean_return
        squared_resid = residuals ** 2

        # Sample variance
        sample_var = np.var(returns)

        # Autocorrelation of squared returns at lag 1
        if T < 5:
            return GARCHResult(
                omega=sample_var * 0.05,
                alpha=0.10,
                beta=0.85,
                long_run_variance=sample_var,
                half_life_periods=10.0,
                current_volatility=float(np.sqrt(sample_var)),
                volatility_forecast=[float(np.sqrt(sample_var))] * forecast_horizon,
                is_valid=False,
            )

        mean_sq = np.mean(squared_resid)
        autocov_1 = np.mean(
            (squared_resid[1:] - mean_sq) * (squared_resid[:-1] - mean_sq)
        )
        autocorr_1 = autocov_1 / np.var(squared_resid) if np.var(squared_resid) > 0 else 0

        # MoM estimates (simplified)
        # persistence ≈ autocorrelation of squared returns
        persistence = max(0.1, min(0.99, abs(autocorr_1) + 0.5))
        alpha = max(0.01, min(0.3, persistence * 0.15))
        beta = max(0.5, min(0.98, persistence - alpha))
        omega = sample_var * (1 - alpha - beta)
        omega = max(1e-10, omega)

        long_run_var = omega / (1 - alpha - beta) if (alpha + beta) < 1 else sample_var
        half_life = np.log(2) / (-np.log(alpha + beta)) if 0 < (alpha + beta) < 1 else 30.0

        # Current volatility estimate using EWMA
        lambda_ewma = 0.94
        ewma_var = sample_var
        for r in residuals:
            ewma_var = lambda_ewma * ewma_var + (1 - lambda_ewma) * r ** 2

        # Forecast
        forecasts = []
        var_t = ewma_var
        for _ in range(forecast_horizon):
            var_t = omega + (alpha + beta) * var_t
            forecasts.append(float(np.sqrt(max(0, var_t))))

        return GARCHResult(
            omega=float(omega),
            alpha=float(alpha),
            beta=float(beta),
            long_run_variance=float(long_run_var),
            half_life_periods=float(half_life),
            current_volatility=float(np.sqrt(max(0, ewma_var))),
            volatility_forecast=forecasts,
        )

    @staticmethod
    def should_widen_spreads(garch_result: GARCHResult, threshold_multiple: float = 1.5) -> bool:
        """
        Determine if market maker should widen spreads based on GARCH.

        If current volatility > threshold * long-run volatility,
        the market is in a high-vol regime and spreads should be wider.
        """
        if not garch_result.is_valid:
            return False

        long_run_vol = np.sqrt(max(0, garch_result.long_run_variance))
        if long_run_vol <= 0:
            return False

        return garch_result.current_volatility > threshold_multiple * long_run_vol
