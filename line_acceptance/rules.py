from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CheckRule:
    item: str
    label: str
    unit: str
    threshold: float
    review_ratio: float
    serious_ratio: float
    default_design: float
    default_measured: float


class RuleBook:
    def __init__(self, path: Path):
        self.path = path
        self.raw = self._load()
        self.rules = {
            item["item"]: CheckRule(
                item=item["item"],
                label=item["label"],
                unit=item["unit"],
                threshold=float(item["threshold"]),
                review_ratio=float(item.get("review_ratio", 1.0)),
                serious_ratio=float(item.get("serious_ratio", 1.2)),
                default_design=float(item.get("default_design", 0)),
                default_measured=float(item.get("default_measured", 0)),
            )
            for item in self.raw.get("geometry_rules", [])
        }
        self.vision_threshold = float(self.raw.get("vision", {}).get("confidence_threshold", 0.6))
        self.registration_max_residual = float(self.raw.get("registration", {}).get("max_residual", 0.15))

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return DEFAULT_RULES
        return json.loads(self.path.read_text(encoding="utf-8"))

    def geometry_items(self) -> list[str]:
        return list(self.rules.keys())

    def rule(self, item: str) -> CheckRule:
        if item not in self.rules:
            raise ValueError(f"未知校核项：{item}")
        return self.rules[item]

    def classify_geometry(self, item: str, design_value: float, measured_value: float) -> dict[str, Any]:
        rule = self.rule(item)
        deviation = abs(float(measured_value) - float(design_value))
        ratio = deviation / rule.threshold if rule.threshold else 0
        if ratio < rule.review_ratio:
            status, level = "合格", "一般"
            suggestion = "偏差处于规则阈值内，可作为验收校核记录归档。"
        elif ratio < rule.serious_ratio:
            status, level = "需复核", "关注"
            suggestion = "偏差接近或超过阈值，应结合原始点云、模型构件和现场记录复核。"
        else:
            status, level = "超限", "严重"
            suggestion = "偏差超过复核线，建议进入问题台账并保留证据位置。"
        return {
            "check_item": item,
            "label": rule.label,
            "unit": rule.unit,
            "design_value": round(float(design_value), 4),
            "measured_value": round(float(measured_value), 4),
            "deviation": round(deviation, 4),
            "threshold": rule.threshold,
            "deviation_ratio": round(ratio, 4),
            "status": status,
            "level": level,
            "suggestion": suggestion,
        }

    def registration_quality(self, residual: float, control_point_count: int) -> str:
        if control_point_count < 3:
            return "配准失败"
        if residual <= self.registration_max_residual * 0.6:
            return "配准通过"
        if residual <= self.registration_max_residual:
            return "配准需复核"
        return "配准失败"

    def classify_defect(self, defect_type: str, confidence: float) -> tuple[str, str]:
        severe = {"螺栓缺失", "绝缘子破损", "金具断裂", "通道净距不足", "防震锤滑移"}
        if confidence < self.vision_threshold:
            return "低置信度", "一般"
        if defect_type in severe:
            return "待复核", "严重"
        return "待复核", "关注"

    def update_geometry_rule(self, item: str, parameters: dict[str, Any]) -> None:
        current = self.rule(item)
        values = asdict(current)
        for key in {
            "label",
            "unit",
            "threshold",
            "review_ratio",
            "serious_ratio",
            "default_design",
            "default_measured",
        }:
            if key in parameters:
                values[key] = parameters[key]
        self.rules[item] = CheckRule(
            item=item,
            label=str(values["label"]),
            unit=str(values["unit"]),
            threshold=float(values["threshold"]),
            review_ratio=float(values["review_ratio"]),
            serious_ratio=float(values["serious_ratio"]),
            default_design=float(values["default_design"]),
            default_measured=float(values["default_measured"]),
        )

    def update_vision_threshold(self, value: float) -> None:
        self.vision_threshold = float(value)


DEFAULT_RULES: dict[str, Any] = {
    "registration": {"max_residual": 0.15},
    "vision": {"confidence_threshold": 0.6},
    "geometry_rules": [
        {
            "item": "foundation_span",
            "label": "基础根开偏差",
            "unit": "m",
            "threshold": 0.08,
            "review_ratio": 1.0,
            "serious_ratio": 1.2,
            "default_design": 8.0,
            "default_measured": 8.04,
        },
        {
            "item": "tower_inclination",
            "label": "杆塔倾斜度",
            "unit": "deg",
            "threshold": 0.25,
            "review_ratio": 1.0,
            "serious_ratio": 1.2,
            "default_design": 0.0,
            "default_measured": 0.22,
        },
        {
            "item": "conductor_sag",
            "label": "导线弧垂",
            "unit": "m",
            "threshold": 0.35,
            "review_ratio": 1.0,
            "serious_ratio": 1.2,
            "default_design": 9.8,
            "default_measured": 10.21,
        },
        {
            "item": "crossing_clearance",
            "label": "交叉跨越净空",
            "unit": "m",
            "threshold": 0.3,
            "review_ratio": 1.0,
            "serious_ratio": 1.2,
            "default_design": 8.0,
            "default_measured": 7.58,
        },
        {
            "item": "channel_distance",
            "label": "通道物距",
            "unit": "m",
            "threshold": 0.5,
            "review_ratio": 1.0,
            "serious_ratio": 1.2,
            "default_design": 3.0,
            "default_measured": 2.41,
        },
    ],
}
