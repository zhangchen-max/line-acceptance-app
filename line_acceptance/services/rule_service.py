from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..database import json_text
from ..ids import now_text
from ..rules import RuleBook
from .common import ServiceBase

STANDARD_BASIS = "项目示例验收规则 V1.0（待按正式标准表复核）"


class RuleService(ServiceBase):
    def __init__(self, db, rule_book: RuleBook):
        super().__init__(db)
        self.rule_book = rule_book
        self.default_rows = default_rule_rows(rule_book)
        self.ensure_seeded()

    def ensure_seeded(self) -> None:
        existing = {row["id"] for row in self.db.all("SELECT id FROM acceptance_rule")}
        for rule in self.default_rows:
            if rule["id"] in existing:
                continue
            self.db.execute(
                """
                INSERT INTO acceptance_rule
                (id, module, name, target_type, parameters_json, severity,
                 standard_basis, enabled, version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule["id"],
                    rule["module"],
                    rule["name"],
                    rule.get("target_type", ""),
                    json_text(rule["parameters"]),
                    rule["severity"],
                    rule["standard_basis"],
                    1 if rule.get("enabled", True) else 0,
                    1,
                    now_text(),
                ),
            )
        self._apply_overrides()

    def list_rules(self, module: str | None = None) -> list[dict[str, Any]]:
        if module:
            return self.db.all("SELECT * FROM acceptance_rule WHERE module = ? ORDER BY id", (module,))
        return self.db.all("SELECT * FROM acceptance_rule ORDER BY module, id")

    def get_rule(self, rule_id: str) -> dict[str, Any]:
        rule = self.db.one("SELECT * FROM acceptance_rule WHERE id = ?", (rule_id,))
        if not rule:
            raise ValueError(f"验收规则不存在：{rule_id}")
        return rule

    def update_rule(self, rule_id: str, payload: dict[str, Any], operator: str = "系统管理员") -> dict[str, Any]:
        current = self.get_rule(rule_id)
        parameters = dict(current["parameters_json"])
        parameters.update(payload.get("parameters", {}))
        severity = payload.get("severity", current["severity"])
        if severity not in {"一般", "关注", "严重"}:
            raise ValueError("规则等级仅支持：一般、关注、严重")
        enabled = bool(payload.get("enabled", current["enabled"]))
        self._validate_parameters(rule_id, parameters)
        self.db.execute(
            """
            UPDATE acceptance_rule
            SET name = ?, target_type = ?, parameters_json = ?, severity = ?,
                standard_basis = ?, enabled = ?, version = version + 1, updated_at = ?
            WHERE id = ?
            """,
            (
                payload.get("name", current["name"]),
                payload.get("target_type", current["target_type"]),
                json_text(parameters),
                severity,
                payload.get("standard_basis", current["standard_basis"]),
                1 if enabled else 0,
                now_text(),
                rule_id,
            ),
        )
        self._apply_overrides()
        updated = self.get_rule(rule_id)
        self.log(operator, "更新验收规则", "acceptance_rule", rule_id, "成功", updated)
        return updated

    def restore_defaults(self, rule_id: str | None = None, operator: str = "系统管理员") -> list[dict[str, Any]]:
        defaults = {item["id"]: item for item in self.default_rows}
        selected = [rule_id] if rule_id else list(defaults)
        for current_id in selected:
            if current_id not in defaults:
                raise ValueError(f"没有可恢复的默认规则：{current_id}")
            rule = defaults[current_id]
            self.db.execute(
                """
                UPDATE acceptance_rule
                SET name = ?, target_type = ?, parameters_json = ?, severity = ?,
                    standard_basis = ?, enabled = ?, version = version + 1, updated_at = ?
                WHERE id = ?
                """,
                (
                    rule["name"],
                    rule.get("target_type", ""),
                    json_text(rule["parameters"]),
                    rule["severity"],
                    rule["standard_basis"],
                    1 if rule.get("enabled", True) else 0,
                    now_text(),
                    current_id,
                ),
            )
        self._apply_overrides()
        self.log(operator, "恢复默认规则", "acceptance_rule", rule_id or "all", "成功", {"count": len(selected)})
        return self.list_rules()

    def vision_settings(self) -> dict[str, dict[str, Any]]:
        return {
            row["id"]: {
                **row,
                "enabled": bool(row["enabled"]),
                "parameters": row["parameters_json"],
            }
            for row in self.list_rules(module="vision")
        }

    def _apply_overrides(self) -> None:
        for row in self.list_rules():
            if not row["enabled"]:
                continue
            parameters = row["parameters_json"]
            if row["module"] == "geometry" and row["id"].startswith("geometry."):
                self.rule_book.update_geometry_rule(row["id"].split(".", 1)[1], parameters)
            elif row["id"] == "vision.detector":
                self.rule_book.update_vision_threshold(float(parameters.get("candidate_threshold", 0.6)))

    def _validate_parameters(self, rule_id: str, parameters: dict[str, Any]) -> None:
        for key, value in parameters.items():
            if isinstance(value, (int, float)) and key not in {"required_count"} and value < 0:
                raise ValueError(f"规则参数 {key} 不能小于 0")
        if rule_id == "vision.detector" and not parameters.get("prompts"):
            raise ValueError("目标检测规则至少需要一个提示词")


def default_rule_rows(rule_book: RuleBook) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item, rule in rule_book.rules.items():
        rows.append(
            {
                "id": f"geometry.{item}",
                "module": "geometry",
                "name": rule.label,
                "target_type": item,
                "parameters": asdict(rule),
                "severity": "严重",
                "standard_basis": STANDARD_BASIS,
            }
        )
    rows.extend(
        [
            {
                "id": "vision.detector",
                "module": "vision",
                "name": "线路构件开放词汇检测",
                "target_type": "线路构件",
                "parameters": {
                    "box_threshold": 0.30,
                    "text_threshold": 0.25,
                    "candidate_threshold": 0.60,
                    "prompts": [
                        {"id": "insulator", "prompt": "insulator string", "target_type": "绝缘子串"},
                        {"id": "fitting", "prompt": "power line fitting", "target_type": "连接金具"},
                        {"id": "bolt", "prompt": "metal bolt", "target_type": "螺栓"},
                        {"id": "damper", "prompt": "vibration damper", "target_type": "防震锤"},
                        {"id": "conductor", "prompt": "power conductor wire", "target_type": "导线"},
                        {"id": "tower", "prompt": "transmission tower steel member", "target_type": "杆塔构件"},
                    ],
                },
                "severity": "一般",
                "standard_basis": STANDARD_BASIS,
            },
            {
                "id": "vision.quality",
                "module": "vision",
                "name": "影像可诊断质量",
                "target_type": "现场影像",
                "parameters": {
                    "min_clarity": 0.55,
                    "min_brightness": 0.25,
                    "max_brightness": 0.94,
                    "min_target_detections": 1,
                },
                "severity": "关注",
                "standard_basis": STANDARD_BASIS,
            },
            {
                "id": "vision.rust",
                "module": "vision",
                "name": "金属构件锈蚀",
                "target_type": "连接金具/杆塔构件/防震锤",
                "parameters": {"min_rust_ratio": 0.035, "high_rust_ratio": 0.12},
                "severity": "关注",
                "standard_basis": STANDARD_BASIS,
            },
            {
                "id": "vision.insulator_damage",
                "module": "vision",
                "name": "绝缘子疑似破损",
                "target_type": "绝缘子串",
                "parameters": {"min_edge_density": 0.025, "max_edge_density": 0.23, "candidate_score": 0.64},
                "severity": "严重",
                "standard_basis": STANDARD_BASIS,
            },
            {
                "id": "vision.damper_position",
                "module": "vision",
                "name": "防震锤位置异常",
                "target_type": "防震锤",
                "parameters": {"max_conductor_distance_ratio": 0.13, "candidate_score": 0.68},
                "severity": "严重",
                "standard_basis": STANDARD_BASIS,
            },
            {
                "id": "vision.bolt_presence",
                "module": "vision",
                "name": "连接部位螺栓完整性",
                "target_type": "连接金具",
                "parameters": {"required_count": 1, "min_bolt_score": 0.32, "candidate_score": 0.58},
                "severity": "严重",
                "standard_basis": STANDARD_BASIS,
            },
        ]
    )
    return rows
