from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..database import json_text
from ..ids import new_id, now_text
from .common import ServiceBase


class ModelService(ServiceBase):
    def import_uploaded_design_model(
        self,
        task_id: str,
        file_name: str,
        content: bytes,
        model_version: str = "V1.0",
        operator: str = "资料管理员",
    ) -> dict[str, Any]:
        task = self.require_task(task_id)
        if not content:
            raise ValueError("上传的设计模型文件为空")
        if Path(file_name).suffix.lower() != ".json":
            raise ValueError("第一阶段仅支持 JSON 格式的 GIM-like 设计模型")
        try:
            data = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("设计模型不是有效的 UTF-8 JSON 文件") from exc
        if not isinstance(data, dict) or not isinstance(data.get("components"), list):
            raise ValueError("设计模型必须包含 components 数组")
        target_dir = self.root_dir / "storage" / "projects" / task["task_no"] / "models"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{new_id('FILE')}_{safe_file_stem(file_name)}.json"
        target.write_bytes(content)
        return self.import_design_model(
            task_id,
            {
                **data,
                "file_path": self.relative_path(target),
                "model_type": data.get("model_type", "GIM-like JSON"),
                "model_version": model_version or data.get("model_version", "V1.0"),
                "coordinate_system": data.get("coordinate_system", "CGCS2000"),
            },
            operator=operator,
        )

    def import_design_model(self, task_id: str, payload: dict[str, Any], operator: str = "资料管理员") -> dict[str, Any]:
        self.require_task(task_id)
        components = self._read_components(payload)
        if not components:
            raise ValueError("设计模型中未找到可解析的线路构件")
        model_id = new_id("M")
        now = now_text()
        file_path = payload.get("file_path") or "sample_data/design_model.json"
        coordinate_system = payload.get("coordinate_system", "CGCS2000")
        self.db.execute(
            """
            INSERT INTO design_model
            (id, task_id, model_type, model_version, file_path, coordinate_system,
             parse_status, component_count, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_id,
                task_id,
                payload.get("model_type", "GIM-like JSON"),
                payload.get("model_version", "GIM-2026.07"),
                file_path,
                coordinate_system,
                "解析成功",
                len(components),
                "已解析杆塔、基础、导线、交跨对象和通道对象。原生 GIM 解析接口已预留。",
                now,
            ),
        )
        rows = []
        for component in components:
            rows.append(
                (
                    new_id("C"),
                    model_id,
                    task_id,
                    component["component_code"],
                    component["component_type"],
                    float(component.get("design_value", 0)),
                    component.get("unit", ""),
                    json_text(component.get("bbox", [])),
                    json_text(component.get("properties", {})),
                )
            )
        self.db.execute_many(
            """
            INSERT INTO model_component
            (id, model_id, task_id, component_code, component_type, design_value, unit, bbox_json, properties_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.log(operator, "导入设计模型", "design_model", model_id, "成功", {"component_count": len(components)})
        return self.db.one("SELECT * FROM design_model WHERE id = ?", (model_id,))

    def components(self, task_id: str) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM model_component WHERE task_id = ? ORDER BY component_type, component_code", (task_id,))

    def _read_components(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if "components" in payload:
            return list(payload["components"])
        source = payload.get("file_path")
        if source:
            path = self.resolve_path(source)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return list(data.get("components", []))
        return default_components()


def default_components() -> list[dict[str, Any]]:
    return [
        {
            "component_code": "T001",
            "component_type": "杆塔",
            "design_value": 0.0,
            "unit": "deg",
            "bbox": [-4.2, -4.2, 4.2, 4.2],
            "properties": {"check_item": "tower_inclination", "tower_height": 36.5, "axis": "Z"},
        },
        {
            "component_code": "F001",
            "component_type": "基础",
            "design_value": 8.0,
            "unit": "m",
            "bbox": [-4.0, -4.0, 4.0, 4.0],
            "properties": {"check_item": "foundation_span", "foundation_type": "四腿基础"},
        },
        {
            "component_code": "L001",
            "component_type": "导线",
            "design_value": 9.8,
            "unit": "m",
            "bbox": [0.0, -2.0, 410.0, 2.0],
            "properties": {"check_item": "conductor_sag", "span": 410, "phase": "A/B/C"},
        },
        {
            "component_code": "X001",
            "component_type": "交跨对象",
            "design_value": 8.0,
            "unit": "m",
            "bbox": [132.0, -10.0, 158.0, 8.0],
            "properties": {"check_item": "crossing_clearance", "object": "道路"},
        },
        {
            "component_code": "CH001",
            "component_type": "通道",
            "design_value": 3.0,
            "unit": "m",
            "bbox": [178.0, 10.0, 230.0, 24.0],
            "properties": {"check_item": "channel_distance", "object": "树障"},
        },
    ]


def safe_file_stem(file_name: str) -> str:
    value = Path(file_name or "design_model").stem
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"})
    return cleaned or "design_model"
