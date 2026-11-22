"""Application settings (Phase 7). Everything has a safe local default; tests override via Settings(...)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = "default"


@dataclass
class Settings:
    db_path: str = str(ROOT / "data" / "app" / "text2task.db")          # ":memory:" in tests
    entity_model_dir: Path = ROOT / "models/text2task-distilbert/entity_v2_three_class/epoch3_sqrt_weighted"
    relation_model_dir: Path = ROOT / "models/text2task-relations/ACTIVE"
    frontend_dist: Path = ROOT / "frontend" / "dist"
    results_dir: Path = ROOT / "results"
    scenario_dir: Path = Path(__file__).resolve().parent / "fixtures" / "scenarios"
    default_timezone: str = "UTC"
    load_models: bool = True                                             # False: never touch torch (tests, scripted-only demo)
    audit_clock: Optional[Callable[[], str]] = None                      # injectable clock for history timestamps
    cors_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        if os.environ.get("T2T_DB"):
            s.db_path = os.environ["T2T_DB"]
        if os.environ.get("T2T_ENTITY_MODEL"):
            s.entity_model_dir = Path(os.environ["T2T_ENTITY_MODEL"])
        if os.environ.get("T2T_RELATION_MODEL"):
            s.relation_model_dir = Path(os.environ["T2T_RELATION_MODEL"])
        if os.environ.get("T2T_FRONTEND_DIST"):
            s.frontend_dist = Path(os.environ["T2T_FRONTEND_DIST"])
        if os.environ.get("T2T_RESULTS_DIR"):
            s.results_dir = Path(os.environ["T2T_RESULTS_DIR"])
        if os.environ.get("T2T_NO_MODELS") == "1":
            s.load_models = False
        if os.environ.get("T2T_TZ"):
            s.default_timezone = os.environ["T2T_TZ"]
        return s
