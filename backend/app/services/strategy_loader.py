"""YAML-based strategy configuration loader.

Allows users to define custom factor weights, category weights,
and scoring parameters via YAML files without changing code.

Example YAML (strategies/default.yaml):

    name: 默认策略
    description: 技术面 + 基本面 + 情绪面均衡配置

    categories:
      technical: 0.4
      fundamental: 0.4
      sentiment: 0.2

    factors:
      technical:
        ma_crossover: { weight: 0.25 }
        macd: { weight: 0.25 }
        rsi: { weight: 0.20 }
        kdj: { weight: 0.15 }
        bollinger: { weight: 0.10 }
        volume_ratio: { weight: 0.05 }
      fundamental:
        pe_score: { weight: 0.20 }
        pb_score: { weight: 0.15 }
        roe_score: { weight: 0.25 }
        revenue_growth_score: { weight: 0.20 }
        profit_growth_score: { weight: 0.15 }
        debt_ratio_score: { weight: 0.05 }
      sentiment:
        turnover_score: { weight: 0.12 }
        capital_flow_score: { weight: 0.12 }
        real_capital_flow_score: { weight: 0.22 }
        chip_concentration_score: { weight: 0.12 }
        sector_heat_score: { weight: 0.17 }
        momentum_5d_score: { weight: 0.12 }
        momentum_20d_score: { weight: 0.13 }
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

# Default config mirrors factor_config.py constants
_DEFAULT_STRATEGY: dict[str, Any] = {
    "name": "默认策略",
    "description": "技术面 + 基本面 + 情绪面均衡配置",
    "categories": {
        "technical": 0.4,
        "fundamental": 0.4,
        "sentiment": 0.2,
    },
    "factors": {
        "technical": {
            "ma_crossover": {"weight": 0.25},
            "macd": {"weight": 0.25},
            "rsi": {"weight": 0.20},
            "kdj": {"weight": 0.15},
            "bollinger": {"weight": 0.10},
            "volume_ratio": {"weight": 0.05},
        },
        "fundamental": {
            "pe_score": {"weight": 0.20},
            "pb_score": {"weight": 0.15},
            "roe_score": {"weight": 0.25},
            "revenue_growth_score": {"weight": 0.20},
            "profit_growth_score": {"weight": 0.15},
            "debt_ratio_score": {"weight": 0.05},
        },
        "sentiment": {
            "turnover_score": {"weight": 0.12},
            "capital_flow_score": {"weight": 0.12},
            "real_capital_flow_score": {"weight": 0.22},
            "chip_concentration_score": {"weight": 0.12},
            "sector_heat_score": {"weight": 0.17},
            "momentum_5d_score": {"weight": 0.12},
            "momentum_20d_score": {"weight": 0.13},
        },
    },
}

STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent / "strategies"


class StrategyLoader:
    """Loads and manages YAML strategy configurations."""

    def __init__(self, strategies_dir: Path | None = None):
        self._dir = strategies_dir or STRATEGIES_DIR
        self._strategies: dict[str, dict[str, Any]] = {}
        self._active_name: str = "default"
        self._load_all()

    def _load_all(self) -> None:
        """Scan strategies directory and load all YAML files."""
        self._strategies.clear()
        self._strategies["default"] = copy.deepcopy(_DEFAULT_STRATEGY)

        if not self._dir.is_dir():
            self._dir.mkdir(parents=True, exist_ok=True)
            # Write default strategy file
            self._write_default()
            logger.info(f"Created strategies directory: {self._dir}")
            return

        for path in sorted(self._dir.glob("*.yaml")) + sorted(self._dir.glob("*.yml")):
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    logger.warning(f"Skipping {path.name}: not a dict")
                    continue
                name = data.get("name", path.stem)
                slug = path.stem
                self._strategies[slug] = data
                logger.debug(f"Loaded strategy: {name} ({slug})")
            except Exception as exc:
                logger.error(f"Failed to load {path.name}: {exc}")

        logger.info(f"Loaded {len(self._strategies)} strategies: {list(self._strategies.keys())}")

    def _write_default(self) -> None:
        """Write the default strategy to a YAML file."""
        path = self._dir / "default.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(_DEFAULT_STRATEGY, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def reload(self) -> None:
        """Re-scan the strategies directory."""
        self._load_all()

    @property
    def active_name(self) -> str:
        return self._active_name

    def set_active(self, name: str) -> bool:
        """Set the active strategy by slug/filename."""
        if name not in self._strategies:
            return False
        self._active_name = name
        logger.info(f"Active strategy set to: {name}")
        return True

    def list_strategies(self) -> list[dict[str, str]]:
        """Return summary of all available strategies."""
        return [
            {
                "slug": slug,
                "name": s.get("name", slug),
                "description": s.get("description", ""),
                "active": slug == self._active_name,
            }
            for slug, s in self._strategies.items()
        ]

    def get_active_config(self) -> dict[str, Any]:
        """Return the full config dict for the active strategy."""
        return self._strategies.get(self._active_name, _DEFAULT_STRATEGY)

    def get_category_weights(self) -> dict[str, float]:
        """Return category weights from active strategy."""
        config = self.get_active_config()
        cats = config.get("categories", _DEFAULT_STRATEGY["categories"])
        total = sum(cats.values())
        if total == 0:
            return _DEFAULT_STRATEGY["categories"]
        # Normalize to sum to 1.0
        return {k: v / total for k, v in cats.items()}

    def get_factor_config(self) -> dict[str, dict]:
        """Return factor config from active strategy (same shape as FACTOR_CONFIG)."""
        config = self.get_active_config()
        factors = config.get("factors", _DEFAULT_STRATEGY["factors"])
        cat_weights = self.get_category_weights()
        result = {}
        for cat in ("technical", "fundamental", "sentiment"):
            cat_factors = factors.get(cat, {})
            result[cat] = dict(cat_factors)
            result[cat]["category_weight"] = cat_weights.get(cat, 0.0)
        return result


# Singleton instance
strategy_loader = StrategyLoader()
