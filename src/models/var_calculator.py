"""
Value at Risk (VaR) Calculator

Implements three VaR methods from the MIT course / Morgan Stanley practitioner lecture:

1. Parametric VaR: σ²_p = wᵀΣw, fast but assumes normality (wrong near resolution)
2. Monte Carlo VaR: Simulate 10,000 scenarios, sort, find percentile
3. Historical VaR: Use actual past returns

Key insight: "The most dangerous risk is not the risk your model measures.
It is the risk your model does not know to look for."

Run multiple methods and watch for divergence as an early warning signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from src.utils.data_models import PriceHistory, RiskMetrics
from src.utils.logger import setup_logger

logger = setup_logger("models.var")


@dataclass
class VaRResult:
    """VaR calculation results."""
    parametric_var: float
    montecarlo_var: float
    historical_var: float
    expected_shortfall: float  # CVaR: average loss beyond VaR
    divergence_warning: bool  # True if methods disagree significantly
    confidence: float
    horizon_days: int


class VaRCalculator:
    """
    Multi-method VaR calculator for Polymarket portfolios.

    Computes portfolio risk using parametric, Monte Carlo, and historical
    simulation approaches. Flags when methods diverge significantly.
    """

    def __init__(self, confidence: float = 0.99, n_simulations: int = 10000):
        self.confidence = confidence
        self.n_simulations = n_simulations

    def compute_portfolio_var(
        self,
        price_histories: list[PriceHistory],
        weights: list[float],
        horizon_days: int = 1,
    ) -> VaRResult:
        """
        Compute VaR using all three methods.

        Args:
            price_histories: Historical prices for each position
            weights: Dollar amount in each position
            horizon_days: VaR horizon in days
        """
        # Build returns matrix (log returns per article recommendation)
        returns_matrix = self._build_returns_matrix(price_histories)
        if returns_matrix is None or returns_matrix.shape[0] < 10:
            return VaRResult(
                parametric_var=0, montecarlo_var=0, historical_var=0,
                expected_shortfall=0, divergence_warning=False,
                confidence=self.confidence, horizon_days=horizon_days,
            )

        weights_arr = np.array(weights[:returns_matrix.shape[1]])
        # Normalize weights if needed
        total_exposure = np.sum(np.abs(weights_arr))
        if total_exposure == 0:
            total_exposure = 1.0

        # 1. Parametric VaR
        param_var = self._parametric_var(returns_matrix, weights_arr, horizon_days)

        # 2. Monte Carlo VaR
        mc_var, mc_es = self._montecarlo_var(returns_matrix, weights_arr, horizon_days)

        # 3. Historical VaR
        hist_var, hist_es = self._historical_var(returns_matrix, weights_arr, horizon_days)

        # Check divergence
        vars_list = [v for v in [param_var, mc_var, hist_var] if v > 0]
        divergence = False
        if len(vars_list) >= 2:
            ratio = max(vars_list) / min(vars_list)
            divergence = ratio > 2.0  # > 2x difference = warning

        if divergence:
            logger.warning(
                "VaR DIVERGENCE: Parametric=%.2f, MC=%.2f, Historical=%.2f",
                param_var, mc_var, hist_var,
            )

        return VaRResult(
            parametric_var=param_var,
            montecarlo_var=mc_var,
            historical_var=hist_var,
            expected_shortfall=max(mc_es, hist_es),
            divergence_warning=divergence,
            confidence=self.confidence,
            horizon_days=horizon_days,
        )

    def compute_risk_metrics(
        self,
        price_histories: list[PriceHistory],
        weights: list[float],
    ) -> RiskMetrics:
        """Compute comprehensive risk metrics for the portfolio."""
        returns_matrix = self._build_returns_matrix(price_histories)
        if returns_matrix is None or returns_matrix.shape[0] < 10:
            return RiskMetrics()

        weights_arr = np.array(weights[:returns_matrix.shape[1]])

        # Portfolio returns
        portfolio_returns = returns_matrix @ weights_arr

        # VaR
        var_result = self.compute_portfolio_var(price_histories, weights)

        # Sharpe ratio (annualized)
        mean_return = np.mean(portfolio_returns)
        std_return = np.std(portfolio_returns)
        # Assume daily returns, annualize with √252
        sharpe = (mean_return * 252) / (std_return * np.sqrt(252)) if std_return > 0 else 0

        # Max drawdown
        cumulative = np.cumsum(portfolio_returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = cumulative - running_max
        max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0

        # Volatility (annualized)
        vol = float(std_return * np.sqrt(252))

        return RiskMetrics(
            var_99=var_result.montecarlo_var,
            var_95=self._compute_single_var(portfolio_returns, 0.95),
            expected_shortfall=var_result.expected_shortfall,
            sharpe_ratio=float(sharpe),
            max_drawdown=float(max_dd),
            volatility=vol,
        )

    # ── Method implementations ──

    def _parametric_var(
        self,
        returns: np.ndarray,
        weights: np.ndarray,
        horizon: int,
    ) -> float:
        """
        Parametric VaR: σ²_p = wᵀΣw

        Assumes normal distribution. Fast but inaccurate near resolution
        (where returns are bimodal, not normal).
        """
        cov_matrix = np.cov(returns, rowvar=False)
        if cov_matrix.ndim == 0:
            cov_matrix = np.array([[cov_matrix]])

        portfolio_var = weights @ cov_matrix @ weights
        portfolio_vol = np.sqrt(max(0, portfolio_var))

        # Scale by √T for multi-day horizon
        z_score = stats.norm.ppf(self.confidence)
        var = z_score * portfolio_vol * np.sqrt(horizon)

        return float(var)

    def _montecarlo_var(
        self,
        returns: np.ndarray,
        weights: np.ndarray,
        horizon: int,
    ) -> tuple[float, float]:
        """
        Monte Carlo VaR: Simulate N scenarios, find percentile.

        Most appropriate for prediction markets because it handles
        non-normal distributions (bimodal near resolution).
        """
        mean_returns = np.mean(returns, axis=0)
        cov_matrix = np.cov(returns, rowvar=False)
        if cov_matrix.ndim == 0:
            cov_matrix = np.array([[cov_matrix]])

        # Generate correlated random scenarios
        try:
            simulated_returns = np.random.multivariate_normal(
                mean_returns * horizon,
                cov_matrix * horizon,
                size=self.n_simulations,
            )
        except np.linalg.LinAlgError:
            # Fallback for singular covariance matrix
            return 0.0, 0.0

        # Portfolio P&L for each scenario
        portfolio_pnl = simulated_returns @ weights

        # VaR: the loss at the confidence percentile
        var_percentile = (1 - self.confidence) * 100
        var = -float(np.percentile(portfolio_pnl, var_percentile))

        # Expected Shortfall (CVaR): average loss beyond VaR
        threshold = np.percentile(portfolio_pnl, var_percentile)
        tail_losses = portfolio_pnl[portfolio_pnl <= threshold]
        es = -float(np.mean(tail_losses)) if len(tail_losses) > 0 else var

        return max(0, var), max(0, es)

    def _historical_var(
        self,
        returns: np.ndarray,
        weights: np.ndarray,
        horizon: int,
    ) -> tuple[float, float]:
        """
        Historical VaR: Use actual past returns.

        No distributional assumptions. Captures fat tails automatically.
        Limited by: history only contains events that already happened.
        """
        # Multi-day returns via rolling windows
        if horizon > 1 and returns.shape[0] > horizon:
            n_windows = returns.shape[0] - horizon + 1
            multi_day = np.zeros((n_windows, returns.shape[1]))
            for i in range(n_windows):
                multi_day[i] = np.sum(returns[i : i + horizon], axis=0)
            portfolio_pnl = multi_day @ weights
        else:
            portfolio_pnl = returns @ weights

        if len(portfolio_pnl) == 0:
            return 0.0, 0.0

        var_percentile = (1 - self.confidence) * 100
        var = -float(np.percentile(portfolio_pnl, var_percentile))

        threshold = np.percentile(portfolio_pnl, var_percentile)
        tail_losses = portfolio_pnl[portfolio_pnl <= threshold]
        es = -float(np.mean(tail_losses)) if len(tail_losses) > 0 else var

        return max(0, var), max(0, es)

    @staticmethod
    def _compute_single_var(returns: np.ndarray, confidence: float) -> float:
        var_pct = (1 - confidence) * 100
        return max(0, -float(np.percentile(returns, var_pct)))

    def _build_returns_matrix(
        self,
        price_histories: list[PriceHistory],
    ) -> np.ndarray | None:
        valid = [ph for ph in price_histories if len(ph.prices) >= 10]
        if len(valid) < 1:
            return None

        min_len = min(len(ph.prices) for ph in valid)
        n = min_len - 1
        if n < 5:
            return None

        matrix = np.zeros((n, len(valid)))
        for j, ph in enumerate(valid):
            prices = np.array(ph.prices[-min_len:])
            prices = np.clip(prices, 1e-6, 1.0 - 1e-6)
            matrix[:, j] = np.diff(np.log(prices))

        return matrix
