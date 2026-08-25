from __future__ import annotations

from typing import Any

from ..database import json_text
from ..ids import new_id, now_text
from ..rules import RuleBook
from .common import ServiceBase


class RegistrationService(ServiceBase):
    def __init__(self, db, rules: RuleBook):
        super().__init__(db)
        self.rules = rules

    def run_registration(self, task_id: str, payload: dict[str, Any] | None = None, operator: str = "验收工程师") -> dict[str, Any]:
        payload = payload or {}
        self.require_task(task_id)
        models = self.db.all("SELECT * FROM design_model WHERE task_id = ?", (task_id,))
        pointclouds = self.db.all("SELECT * FROM pointcloud_asset WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        if not models:
            raise ValueError("请先导入 GIM-like 设计模型")
        if not pointclouds:
            raise ValueError("请先导入点云资料")
        control_count = int(payload.get("control_point_count", 5))
        base_residual = float(payload.get("base_residual", 0.078))
        density_penalty = 0.018 if pointclouds[0]["quality_status"] == "需复核" else 0.0
        residual = round(base_residual + max(0, 4 - control_count) * 0.04 + density_penalty, 4)
        quality = self.rules.registration_quality(residual, control_count)
        matrix = payload.get("transform_matrix") or [
            [1.0, 0.0, 0.0, 0.018],
            [0.0, 1.0, 0.0, -0.012],
            [0.0, 0.0, 1.0, 0.006],
            [0.0, 0.0, 0.0, 1.0],
        ]
        result_id = new_id("REG")
        self.db.execute(
            """
            INSERT INTO registration_result
            (id, task_id, method, transform_matrix_json, residual, quality_level,
             control_point_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                task_id,
                payload.get("method", "控制点约束配准"),
                json_text(matrix),
                residual,
                quality,
                control_count,
                now_text(),
            ),
        )
        self.log(operator, "执行坐标配准", "registration_result", result_id, quality, {"residual": residual})
        return self.db.one("SELECT * FROM registration_result WHERE id = ?", (result_id,))
