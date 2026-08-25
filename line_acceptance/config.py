from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    data_dir: Path
    storage_dir: Path
    report_dir: Path
    evidence_dir: Path
    model_dir: Path
    database_path: Path
    rule_file: Path
    host: str
    port: int

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)


def load_config(root_dir: Path | None = None) -> AppConfig:
    root = root_dir or Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    storage_dir = root / "storage" / "projects"
    report_dir = root / "storage" / "reports"
    evidence_dir = root / "storage" / "evidence"
    model_dir = root / "storage" / "models" / "grounding-dino-tiny"
    return AppConfig(
        root_dir=root,
        data_dir=data_dir,
        storage_dir=storage_dir,
        report_dir=report_dir,
        evidence_dir=evidence_dir,
        model_dir=model_dir,
        database_path=data_dir / "line_acceptance.db",
        rule_file=root / "config" / "check_rules.json",
        host=os.environ.get("LINE_ACCEPT_HOST", "127.0.0.1"),
        port=int(os.environ.get("LINE_ACCEPT_PORT", "8080")),
    )
