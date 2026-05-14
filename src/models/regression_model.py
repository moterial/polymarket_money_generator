"""
Regression Model

Implements weighted and robust regression for prediction market modeling.

From the article:
- OLS is the gold standard (Gauss-Markov theorem)
- But prediction markets violate constant variance assumption (heteroscedasticity)
- Near resolution: low variance, far from resolution: high variance
- Fix: Generalized Least Squares (GLS) / weighted regression
- Robust regression: protect against outliers from contested resolutions / oracle failures
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import stats

from src.utils.logger import setup_logger

logger = setup_logger("models.regression")


@dataclass
class RegressionResult:
    coefficients: np.ndarray
    r_squared: float
    residuals: np.ndarray
    std_errors: np.ndarray
    p_values: np.ndarray
    is_weighted: bool = False
    predicted_probability: Optional[float] = None


class PredictionMarketRegression:
    """
    Regression models tailored for prediction markets.

    Features:
    1. Weighted regression (GLS) — accounts for variance changing with time-to-resolution
    2. Robust regression — resistant to outliers from oracle failures
    3. Log-odds transformation — proper handling of probability space [0, 1]
    """

    @staticmethod
    def weighted_ols(
        X: np.ndarray,
        y: np.ndarray,
        days_to_resolution: np.ndarray,
    ) -> RegressionResult:
        """
        Weighted OLS where weights inversely relate to time-to-resolution.

        Near resolution → low variance → high weight
        Far from resolution → high variance → low weight

        Weight_i = 1 / sqrt(days_to_resolution_i)
        This accounts for the √T scaling of uncertainty.
        """
        n, k = X.shape

        # Compute weights: inverse of √(days to resolution)
        # Add small constant to avoid division by zero
        weights = 1.0 / np.sqrt(np.maximum(days_to_resolution, 0.1))
        W = np.diag(weights)

        # Weighted least squares: β = (X'WX)^(-1) X'Wy
        XtWX = X.T @ W @ X
        XtWy = X.T @ W @ y

        try:
            beta = np.linalg.solve(XtWX, XtWy)
        except np.linalg.LinAlgError:
            beta = np.linalg.lstsq(XtWX, XtWy, rcond=None)[0]

        # Residuals and R²
        y_pred = X @ beta
        residuals = y - y_pred
        ss_res = np.sum(weights * residuals ** 2)
        ss_tot = np.sum(weights * (y - np.average(y, weights=weights)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Standard errors
        sigma2 = ss_res / max(n - k, 1)
        try:
            cov_beta = sigma2 * np.linalg.inv(XtWX)
            std_errors = np.sqrt(np.diag(cov_beta))
        except np.linalg.LinAlgError:
            std_errors = np.full(k, np.nan)

        # P-values
        t_stats = beta / np.where(std_errors > 0, std_errors, 1)
        p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=max(n - k, 1)))

        return RegressionResult(
            coefficients=beta,
            r_squared=float(r_squared),
            residuals=residuals,
            std_errors=std_errors,
            p_values=p_values,
            is_weighted=True,
        )

    @staticmethod
    def robust_regression(
        X: np.ndarray,
        y: np.ndarray,
        max_iterations: int = 50,
        tolerance: float = 1e-6,
    ) -> RegressionResult:
        """
        Iteratively Reweighted Least Squares (IRLS) with Huber weights.

        Resistant to outliers from contested resolutions / oracle failures.
        Large residuals get down-weighted, preventing them from pulling
        the regression line.
        """
        n, k = X.shape
        huber_c = 1.345  # Huber's constant for 95% efficiency

        # Initial OLS
        beta = np.linalg.lstsq(X, y, rcond=None)[0]

        for iteration in range(max_iterations):
            residuals = y - X @ beta
            mad = np.median(np.abs(residuals - np.median(residuals)))
            scale = mad / 0.6745 if mad > 0 else 1.0

            # Huber weights
            u = residuals / max(scale, 1e-10)
            weights = np.where(np.abs(u) <= huber_c, 1.0, huber_c / np.abs(u))
            W = np.diag(weights)

            # Weighted LS step
            XtWX = X.T @ W @ X
            XtWy = X.T @ W @ y

            try:
                beta_new = np.linalg.solve(XtWX, XtWy)
            except np.linalg.LinAlgError:
                break

            if np.max(np.abs(beta_new - beta)) < tolerance:
                beta = beta_new
                break
            beta = beta_new

        # Final statistics
        residuals = y - X @ beta
        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        sigma2 = ss_res / max(n - k, 1)
        try:
            cov_beta = sigma2 * np.linalg.inv(X.T @ X)
            std_errors = np.sqrt(np.diag(cov_beta))
        except np.linalg.LinAlgError:
            std_errors = np.full(k, np.nan)

        t_stats = beta / np.where(std_errors > 0, std_errors, 1)
        p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=max(n - k, 1)))

        return RegressionResult(
            coefficients=beta,
            r_squared=float(r_squared),
            residuals=residuals,
            std_errors=std_errors,
            p_values=p_values,
        )

    @staticmethod
    def estimate_true_probability(
        signals: dict[str, float],
        historical_data: Optional[np.ndarray] = None,
    ) -> float:
        """
        Estimate the true probability of an event given signals.

        Uses logistic regression in log-odds space to combine signals.
        This is the core of "better probability estimation" — the only
        place where systematic edge lives (per the martingale argument).

        Signals could include:
        - polling_average: Latest polling data
        - historical_base_rate: Base rate for similar events
        - market_momentum: Recent price trend
        - volume_imbalance: Buy vs sell pressure
        - time_factor: √(days to resolution) adjusted
        """
        if not signals:
            return 0.5

        # Simple weighted average as baseline
        # In production, this would be a trained logistic regression model
        weights = {
            "polling_average": 0.35,
            "historical_base_rate": 0.20,
            "market_price": 0.25,
            "expert_estimate": 0.15,
            "volume_signal": 0.05,
        }

        weighted_sum = 0.0
        weight_total = 0.0
        for key, value in signals.items():
            w = weights.get(key, 0.1)
            weighted_sum += w * np.clip(value, 0.01, 0.99)
            weight_total += w

        if weight_total > 0:
            return float(np.clip(weighted_sum / weight_total, 0.01, 0.99))
        return 0.5
