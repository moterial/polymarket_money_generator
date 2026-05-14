"""
Correlation & PCA Analyzer

Implements concepts from the MIT Financial Mathematics course:
- Eigenvalue decomposition of correlation matrices
- SVD for finding hidden structure in market returns
- PCA for factor extraction (how many independent risk drivers exist)
- Effective number of bets calculation

Key insight from the articles:
"You think you have 100 independent positions, but eigenvalue decomposition
shows that 3 eigenvectors explain 80% of your total variance.
Your diversification is an illusion."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from numpy.linalg import eig, svd

from src.utils.data_models import PriceHistory
from src.utils.logger import setup_logger

logger = setup_logger("models.correlation")


@dataclass
class CorrelationAnalysis:
    """Results of correlation / PCA analysis."""
    correlation_matrix: np.ndarray
    eigenvalues: np.ndarray
    eigenvectors: np.ndarray
    explained_variance_ratio: np.ndarray
    n_effective_bets: float
    top_factor_labels: list[str] = field(default_factory=list)
    concentration_ratio: float = 0.0  # % variance explained by top 3 factors


@dataclass
class PairCorrelation:
    market_a: str
    market_b: str
    correlation: float
    beta: float  # sensitivity of B to A


class CorrelationAnalyzer:
    """
    Analyze correlation structure across Polymarket contracts.

    Uses eigenvalue decomposition and PCA to reveal:
    1. How many truly independent risk factors exist
    2. Which markets move together (hidden correlations)
    3. Whether apparent diversification is real or illusory
    """

    def analyze_returns_matrix(
        self,
        price_histories: list[PriceHistory],
        min_observations: int = 20,
    ) -> Optional[CorrelationAnalysis]:
        """
        Build returns matrix from price histories and analyze structure.

        Steps:
        1. Compute log-returns (as per article: model log of price, not price itself)
        2. Build correlation matrix
        3. Eigenvalue decomposition → find dominant risk factors
        4. Compute effective number of bets
        """
        # Build aligned returns matrix
        returns_matrix = self._build_returns_matrix(price_histories, min_observations)
        if returns_matrix is None:
            return None

        n_assets = returns_matrix.shape[1]
        if n_assets < 2:
            return None

        # Correlation matrix
        corr_matrix = np.corrcoef(returns_matrix, rowvar=False)
        # Handle NaN from constant columns
        corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)

        # Eigenvalue decomposition
        eigenvalues, eigenvectors = eig(corr_matrix)
        # Sort by eigenvalue magnitude (descending)
        idx = np.argsort(-np.abs(eigenvalues))
        eigenvalues = np.real(eigenvalues[idx])
        eigenvectors = np.real(eigenvectors[:, idx])

        # Explained variance ratio
        total_var = np.sum(np.abs(eigenvalues))
        explained_ratio = np.abs(eigenvalues) / total_var if total_var > 0 else eigenvalues

        # Effective number of bets (entropy-based)
        # If all eigenvalues equal → max diversification → n_eff = N
        # If one eigenvalue dominates → min diversification → n_eff ≈ 1
        n_eff = self._compute_effective_bets(eigenvalues)

        # Concentration: variance explained by top 3 factors
        top3_ratio = float(np.sum(explained_ratio[:3])) if len(explained_ratio) >= 3 else 1.0

        analysis = CorrelationAnalysis(
            correlation_matrix=corr_matrix,
            eigenvalues=eigenvalues,
            eigenvectors=eigenvectors,
            explained_variance_ratio=explained_ratio,
            n_effective_bets=n_eff,
            concentration_ratio=top3_ratio,
        )

        logger.info(
            "PCA: %d assets → %.1f effective bets, top-3 factors explain %.1f%% variance",
            n_assets, n_eff, top3_ratio * 100,
        )

        return analysis

    def compute_svd(
        self,
        price_histories: list[PriceHistory],
        min_observations: int = 20,
    ) -> Optional[dict]:
        """
        Singular Value Decomposition: A = UΣVᵀ

        More general than eigendecomposition. Works on any matrix.
        Reveals how many truly independent sources of movement exist.

        Returns dict with singular values, explained variance, and factor loadings.
        """
        returns_matrix = self._build_returns_matrix(price_histories, min_observations)
        if returns_matrix is None:
            return None

        # Standardize returns
        means = np.mean(returns_matrix, axis=0)
        stds = np.std(returns_matrix, axis=0)
        stds[stds == 0] = 1.0
        standardized = (returns_matrix - means) / stds

        U, S, Vt = svd(standardized, full_matrices=False)

        total_var = np.sum(S ** 2)
        explained = (S ** 2) / total_var if total_var > 0 else S

        # How many factors explain 80% of variance?
        cumulative = np.cumsum(explained)
        n_factors_80 = int(np.searchsorted(cumulative, 0.80)) + 1

        return {
            "singular_values": S.tolist(),
            "explained_variance_ratio": explained.tolist(),
            "cumulative_variance": cumulative.tolist(),
            "n_factors_80pct": n_factors_80,
            "factor_loadings": Vt[:min(5, len(S))].tolist(),  # Top 5 factor loadings
        }

    def find_correlated_pairs(
        self,
        price_histories: list[PriceHistory],
        threshold: float = 0.7,
    ) -> list[PairCorrelation]:
        """Find highly correlated market pairs."""
        returns_matrix = self._build_returns_matrix(price_histories, min_observations=10)
        if returns_matrix is None or returns_matrix.shape[1] < 2:
            return []

        corr = np.corrcoef(returns_matrix, rowvar=False)
        corr = np.nan_to_num(corr, nan=0.0)

        pairs: list[PairCorrelation] = []
        n = corr.shape[0]
        token_ids = [ph.token_id for ph in price_histories if len(ph.prices) >= 10]

        for i in range(n):
            for j in range(i + 1, n):
                if abs(corr[i, j]) >= threshold:
                    # Compute beta (regression coefficient)
                    x = returns_matrix[:, i]
                    y = returns_matrix[:, j]
                    var_x = np.var(x)
                    beta = np.cov(x, y)[0, 1] / var_x if var_x > 0 else 0.0

                    pairs.append(PairCorrelation(
                        market_a=token_ids[i] if i < len(token_ids) else f"asset_{i}",
                        market_b=token_ids[j] if j < len(token_ids) else f"asset_{j}",
                        correlation=float(corr[i, j]),
                        beta=float(beta),
                    ))

        pairs.sort(key=lambda p: abs(p.correlation), reverse=True)
        return pairs

    # ── Private helpers ──

    def _build_returns_matrix(
        self,
        price_histories: list[PriceHistory],
        min_observations: int,
    ) -> Optional[np.ndarray]:
        """
        Build log-returns matrix from price histories.

        Uses log returns instead of simple returns (article recommendation):
        - Avoids negative price issues
        - Properly handles percentage asymmetry
        - ln(1.5) + ln(0.5) < 0, correctly reflecting net loss
        """
        valid_histories = [
            ph for ph in price_histories
            if len(ph.prices) >= min_observations
        ]
        if len(valid_histories) < 2:
            return None

        # Align to common length (use shortest)
        min_len = min(len(ph.prices) for ph in valid_histories)
        if min_len < min_observations:
            return None

        # Build matrix of log returns
        n_periods = min_len - 1
        n_assets = len(valid_histories)

        returns = np.zeros((n_periods, n_assets))
        for j, ph in enumerate(valid_histories):
            prices = np.array(ph.prices[-min_len:])
            # Clamp prices to avoid log(0)
            prices = np.clip(prices, 1e-6, 1.0 - 1e-6)
            # Log returns
            log_returns = np.diff(np.log(prices))
            returns[:, j] = log_returns

        return returns

    @staticmethod
    def _compute_effective_bets(eigenvalues: np.ndarray) -> float:
        """
        Compute effective number of independent bets using entropy.

        n_eff = exp(-Σ p_i * ln(p_i))

        where p_i = |λ_i| / Σ|λ_j| is the normalized eigenvalue.

        Maximum n_eff = N (all eigenvalues equal, perfectly diversified)
        Minimum n_eff ≈ 1 (one eigenvalue dominates)
        """
        abs_eig = np.abs(eigenvalues)
        total = np.sum(abs_eig)
        if total == 0:
            return 1.0

        proportions = abs_eig / total
        # Filter out zeros to avoid log(0)
        proportions = proportions[proportions > 1e-10]
        entropy = -np.sum(proportions * np.log(proportions))

        return float(np.exp(entropy))
