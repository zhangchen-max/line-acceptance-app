from __future__ import annotations

from typing import Any

from ..database import json_text
from ..ids import new_id, now_text
from ..rules import RuleBook
from .common import ServiceBase


class CheckService(ServiceBase):
    def __init__(self, db, rules: RuleBook):
        super().__init__(db)
        self.rules = rules

    def run_geometry_checks(self, task_id: str, payload: dict[str, Any] | None = None, operator: str = "验收工程师") -> list[dict[str, Any]]:
        return self.run_model_pointcloud_compare(task_id, payload, operator)

    def run_model_pointcloud_compare(self, task_id: str, payload: dict[str, Any] | None = None, operator: str = "验收工程师") -> list[dict[str, Any]]:
        payload = payload or {}
        self.require_task(task_id)
        latest_registration = self.db.one(
            "SELECT * FROM registration_result WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        )
        if not latest_registration:
            raise ValueError("请先执行坐标配准")
        if latest_registration["quality_level"] == "配准失败":
            raise ValueError("配准结果不合格，不能执行模型点云对比")

        selected = payload.get("items") or self.rules.geometry_items()
        measured_overrides = payload.get("measured_values", {})
        measurements = self._measurements_by_item(task_id)
        self._clear_previous_results(task_id)

        results: list[dict[str, Any]] = []
        for item in selected:
            rule = self.rules.rule(item)
            component = self._component_for_item(task_id, item)
            design_value = float(component["design_value"]) if component else rule.default_design
            measurement = measurements.get(item)
            measured_value = float(measured_overrides.get(item, measurement["measured_value"] if measurement else rule.default_measured))
            classified = self.rules.classify_geometry(item, design_value, measured_value)
            result_id = new_id("GEO")
            evidence = self._evidence(item, component, measurement, latest_registration, classified)
            self.db.execute(
                """
                INSERT INTO geometry_check_result
                (id, task_id, check_item, design_value, measured_value, deviation, threshold,
                 deviation_ratio, status, level, evidence_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    task_id,
                    item,
                    classified["design_value"],
                    classified["measured_value"],
                    classified["deviation"],
                    classified["threshold"],
                    classified["deviation_ratio"],
                    classified["status"],
                    classified["level"],
                    json_text(evidence),
                    now_text(),
                ),
            )
            result = self.db.one("SELECT * FROM geometry_check_result WHERE id = ?", (result_id,))
            results.append(result)
            self._create_heatmap_marker(task_id, result, classified["label"], evidence)
            if classified["status"] in {"需复核", "超限"}:
                self._create_issue(task_id, result, classified["label"], evidence)
        self._record_run(
            task_id,
            "模型与点云对比分析",
            "成功",
            {"selected_items": selected, "registration_id": latest_registration["id"]},
            {"result_count": len(results), "issue_count": sum(1 for item in results if item["status"] in {"需复核", "超限"})},
        )
        self.log(operator, "执行模型点云对比", "geometry_check_result", task_id, "成功", {"count": len(results)})
        return results

    def results(self, task_id: str) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM geometry_check_result WHERE task_id = ? ORDER BY created_at DESC", (task_id,))

    def _clear_previous_results(self, task_id: str) -> None:
        self.db.execute("DELETE FROM acceptance_issue WHERE task_id = ? AND source_type = ?", (task_id, "geometry"))
        self.db.execute("DELETE FROM heatmap_marker WHERE task_id = ? AND source_type = ?", (task_id, "geometry"))
        self.db.execute("DELETE FROM geometry_check_result WHERE task_id = ?", (task_id,))

    def _measurements_by_item(self, task_id: str) -> dict[str, dict[str, Any]]:
        rows = self.db.all(
            """
            SELECT * FROM pointcloud_measurement
            WHERE task_id = ?
            ORDER BY created_at DESC
            """,
            (task_id,),
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            result.setdefault(row["check_item"], row)
        return result

    def _component_for_item(self, task_id: str, item: str) -> dict[str, Any] | None:
        rows = self.db.all("SELECT * FROM model_component WHERE task_id = ?", (task_id,))
        for row in rows:
            props = row.get("properties_json") or {}
            if props.get("check_item") == item:
                return row
        return None

    def _evidence(
        self,
        item: str,
        component: dict[str, Any] | None,
        measurement: dict[str, Any] | None,
        registration: dict[str, Any],
        classified: dict[str, Any],
    ) -> dict[str, Any]:
        measurement_evidence = measurement.get("evidence_json", {}) if measurement else {}
        position = self._position_hint(item, component, measurement_evidence)
        return {
            "component_code": component["component_code"] if component else "",
            "component_type": component["component_type"] if component else "",
            "measurement_id": measurement["id"] if measurement else "",
            "measurement_method": measurement["method"] if measurement else "规则默认值",
            "measurement_confidence": measurement["confidence"] if measurement else 0.5,
            "registration_id": registration["id"],
            "registration_residual": registration["residual"],
            "position": position["label"],
            "x": position["x"],
            "y": position["y"],
            "suggestion": classified["suggestion"],
        }

    def _position_hint(self, item: str, component: dict[str, Any] | None, evidence: dict[str, Any]) -> dict[str, Any]:
        if evidence:
            return {"x": float(evidence.get("x", 0)), "y": float(evidence.get("y", 0)), "label": evidence.get("label", "线路验收对象")}
        if component and component.get("bbox_json"):
            bbox = component["bbox_json"]
            if len(bbox) >= 4:
                return {"x": (bbox[0] + bbox[2]) / 2, "y": (bbox[1] + bbox[3]) / 2, "label": component["component_code"]}
        return {
            "foundation_span": {"x": 0.0, "y": 0.0, "label": "T001 基础四腿中心"},
            "tower_inclination": {"x": 0.0, "y": 0.0, "label": "T001 塔身主轴"},
            "conductor_sag": {"x": 205.0, "y": 0.0, "label": "T001-T002 跨中导线"},
            "crossing_clearance": {"x": 145.0, "y": 0.0, "label": "K12+480 道路跨越点"},
            "channel_distance": {"x": 205.0, "y": 7.0, "label": "T001 小号侧树障区"},
        }.get(item, {"x": 0.0, "y": 0.0, "label": "线路验收对象"})

    def _create_heatmap_marker(self, task_id: str, result: dict[str, Any], label: str, evidence: dict[str, Any]) -> None:
        self.db.execute(
            """
            INSERT INTO heatmap_marker
            (id, task_id, source_type, source_id, check_item, x, y, value, level, label, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("HM"),
                task_id,
                "geometry",
                result["id"],
                result["check_item"],
                float(evidence.get("x", 0)),
                float(evidence.get("y", 0)),
                float(result["deviation_ratio"]),
                result["level"],
                label,
                now_text(),
            ),
        )

    def _create_issue(self, task_id: str, result: dict[str, Any], label: str, evidence: dict[str, Any]) -> None:
        existing = self.db.one(
            "SELECT id FROM acceptance_issue WHERE source_type = ? AND source_id = ?",
            ("geometry", result["id"]),
        )
        if existing:
            return
        issue_id = new_id("ISS")
        description = (
            f"{label}：实测值 {result['measured_value']}，设计值 {result['design_value']}，"
            f"偏差 {result['deviation']}，状态 {result['status']}。"
        )
        now = now_text()
        self.db.execute(
            """
            INSERT INTO acceptance_issue
            (id, task_id, source_type, source_id, issue_type, level, description,
             review_status, rectify_status, evidence_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue_id,
                task_id,
                "geometry",
                result["id"],
                label,
                result["level"],
                description,
                "待复核",
                "未整改",
                json_text(evidence),
                now,
                now,
            ),
        )

    def _record_run(
        self,
        task_id: str,
        module: str,
        status: str,
        input_summary: dict[str, Any],
        output_summary: dict[str, Any],
    ) -> None:
        self.db.execute(
            """
            INSERT INTO algorithm_run
            (id, task_id, module, status, input_summary_json, output_summary_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id("ALG"), task_id, module, status, json_text(input_summary), json_text(output_summary), now_text()),
        )
