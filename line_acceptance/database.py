from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable

from .config import AppConfig


class Database:
    def __init__(self, config: AppConfig):
        self.config = config
        self.config.ensure_dirs()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.config.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def session(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA_SQL)
            self._apply_migrations(conn)

    def reset(self) -> None:
        if self.config.database_path.exists():
            self.config.database_path.unlink()
        self.init_schema()

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self.session() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return row_to_dict(row) if row else None

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [row_to_dict(row) for row in rows]

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.session() as conn:
            conn.execute(sql, tuple(params))

    def execute_many(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self.session() as conn:
            conn.executemany(sql, rows)

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        migrations = {
            "vision_defect_result": {
                "inference_run_id": "TEXT DEFAULT ''",
                "model_label": "TEXT DEFAULT ''",
                "model_score": "REAL NOT NULL DEFAULT 0",
                "rule_id": "TEXT DEFAULT ''",
                "rule_score": "REAL NOT NULL DEFAULT 0",
                "diagnosis_json": "TEXT NOT NULL DEFAULT '{}'",
            },
            "image_asset": {
                "quality_json": "TEXT NOT NULL DEFAULT '{}'",
            },
        }
        for table, columns in migrations.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.execute(
            "INSERT OR IGNORE INTO schema_migration (version, applied_at) VALUES (?, datetime('now'))",
            (2,),
        )


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if key.endswith("_json") and isinstance(value, str) and value:
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return result


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS acceptance_task (
    id TEXT PRIMARY KEY,
    task_no TEXT NOT NULL UNIQUE,
    project_name TEXT NOT NULL,
    line_name TEXT NOT NULL,
    section_name TEXT NOT NULL,
    batch_no TEXT NOT NULL,
    construction_unit TEXT DEFAULT '',
    owner TEXT NOT NULL,
    acceptance_scope TEXT DEFAULT '',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS design_model (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    model_type TEXT NOT NULL,
    model_version TEXT NOT NULL,
    file_path TEXT NOT NULL,
    coordinate_system TEXT NOT NULL,
    parse_status TEXT NOT NULL,
    component_count INTEGER NOT NULL DEFAULT 0,
    message TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_component (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL REFERENCES design_model(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    component_code TEXT NOT NULL,
    component_type TEXT NOT NULL,
    design_value REAL NOT NULL DEFAULT 0,
    unit TEXT DEFAULT '',
    bbox_json TEXT NOT NULL,
    properties_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pointcloud_asset (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    point_count INTEGER NOT NULL,
    coordinate_system TEXT NOT NULL,
    density REAL NOT NULL,
    quality_status TEXT NOT NULL,
    quality_message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pointcloud_slice (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES pointcloud_asset(id) ON DELETE CASCADE,
    grid_x INTEGER NOT NULL,
    grid_y INTEGER NOT NULL,
    point_count INTEGER NOT NULL,
    density REAL NOT NULL,
    min_z REAL NOT NULL,
    max_z REAL NOT NULL,
    avg_intensity REAL NOT NULL,
    dominant_class TEXT NOT NULL,
    bounds_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pointcloud_object (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES pointcloud_asset(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL,
    object_code TEXT NOT NULL,
    point_count INTEGER NOT NULL,
    bbox_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    defect_type TEXT DEFAULT '',
    severity TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pointcloud_measurement (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES pointcloud_asset(id) ON DELETE CASCADE,
    check_item TEXT NOT NULL,
    measured_value REAL NOT NULL,
    unit TEXT NOT NULL,
    method TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS image_asset (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source_type TEXT NOT NULL,
    frame_time TEXT DEFAULT '',
    shoot_position TEXT DEFAULT '',
    clarity_score REAL NOT NULL DEFAULT 0,
    quality_json TEXT NOT NULL DEFAULT '{}',
    process_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registration_result (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    method TEXT NOT NULL,
    transform_matrix_json TEXT NOT NULL,
    residual REAL NOT NULL,
    quality_level TEXT NOT NULL,
    control_point_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geometry_check_result (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    check_item TEXT NOT NULL,
    design_value REAL NOT NULL,
    measured_value REAL NOT NULL,
    deviation REAL NOT NULL,
    threshold REAL NOT NULL,
    deviation_ratio REAL NOT NULL,
    status TEXT NOT NULL,
    level TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS heatmap_marker (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    check_item TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    value REAL NOT NULL,
    level TEXT NOT NULL,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vision_defect_result (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    image_id TEXT NOT NULL REFERENCES image_asset(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    defect_type TEXT NOT NULL,
    bbox_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    level TEXT NOT NULL,
    snapshot_path TEXT DEFAULT '',
    status TEXT NOT NULL,
    inference_run_id TEXT DEFAULT '',
    model_label TEXT DEFAULT '',
    model_score REAL NOT NULL DEFAULT 0,
    rule_id TEXT DEFAULT '',
    rule_score REAL NOT NULL DEFAULT 0,
    diagnosis_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vision_inference_run (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    image_id TEXT NOT NULL REFERENCES image_asset(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    device TEXT NOT NULL,
    status TEXT NOT NULL,
    prompt_json TEXT NOT NULL,
    raw_output_json TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_model_registry (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    revision TEXT NOT NULL,
    local_path TEXT NOT NULL,
    license TEXT NOT NULL,
    source_url TEXT NOT NULL,
    install_status TEXT NOT NULL,
    device TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    last_checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS acceptance_rule (
    id TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    name TEXT NOT NULL,
    target_type TEXT DEFAULT '',
    parameters_json TEXT NOT NULL,
    severity TEXT NOT NULL,
    standard_basis TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migration (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vision_run_task_image
ON vision_inference_run(task_id, image_id, created_at);

CREATE INDEX IF NOT EXISTS idx_rule_module
ON acceptance_rule(module, enabled);

CREATE TABLE IF NOT EXISTS fusion_scene (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    scene_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS algorithm_run (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    module TEXT NOT NULL,
    status TEXT NOT NULL,
    input_summary_json TEXT NOT NULL,
    output_summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS acceptance_issue (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    level TEXT NOT NULL,
    description TEXT NOT NULL,
    review_status TEXT NOT NULL,
    rectify_status TEXT NOT NULL,
    reviewer TEXT DEFAULT '',
    review_opinion TEXT DEFAULT '',
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_export (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES acceptance_task(id) ON DELETE CASCADE,
    format TEXT NOT NULL,
    file_path TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    export_time TEXT NOT NULL,
    operator TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_log (
    id TEXT PRIMARY KEY,
    operator TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    result TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""
