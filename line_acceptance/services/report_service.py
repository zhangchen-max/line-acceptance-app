from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import APP_NAME, APP_VERSION
from ..database import json_text
from ..document import write_docx
from ..ids import new_id, now_text
from .common import ServiceBase


class ReportService(ServiceBase):
    def __init__(self, db, report_dir: Path):
        super().__init__(db)
        self.report_dir = report_dir

    def export_report(self, task_id: str, payload: dict[str, Any] | None = None, operator: str = "验收工程师") -> dict[str, Any]:
        payload = payload or {}
        task = self.require_task(task_id)
        measurements = self.db.all("SELECT * FROM pointcloud_measurement WHERE task_id = ? ORDER BY check_item", (task_id,))
        checks = self.db.all("SELECT * FROM geometry_check_result WHERE task_id = ? ORDER BY check_item", (task_id,))
        visions = self.db.all("SELECT * FROM vision_defect_result WHERE task_id = ? ORDER BY created_at", (task_id,))
        inference_runs = self.db.all(
            "SELECT * FROM vision_inference_run WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        )
        model_registry = self.db.all("SELECT * FROM ai_model_registry ORDER BY last_checked_at DESC")
        acceptance_rules = self.db.all("SELECT * FROM acceptance_rule ORDER BY module, id")
        issues = self.db.all("SELECT * FROM acceptance_issue WHERE task_id = ? ORDER BY updated_at", (task_id,))
        reports_dir = self.report_dir / task["task_no"]
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_id = new_id("RPT")
        fmt = payload.get("format", "docx").lower()
        title = f"{task['project_name']}验收校核报告"
        paragraphs = self._paragraphs(task, measurements, checks, visions, inference_runs, issues)
        tables = self._tables(measurements, checks, visions, inference_runs, model_registry, acceptance_rules, issues)
        if fmt == "md":
            path = reports_dir / f"{report_id}_验收校核报告.md"
            path.write_text(self._markdown(title, paragraphs, tables), encoding="utf-8")
        else:
            fmt = "docx"
            path = reports_dir / f"{report_id}_验收校核报告.docx"
            write_docx(path, title, paragraphs, tables)
        summary = {
            "measurement_count": len(measurements),
            "geometry_count": len(checks),
            "vision_count": len(visions),
            "vision_inference_count": len(inference_runs),
            "issue_count": len(issues),
            "confirmed_issue_count": sum(1 for item in issues if item["review_status"] == "已确认"),
        }
        self.db.execute(
            """
            INSERT INTO report_export
            (id, task_id, format, file_path, summary_json, export_time, operator)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (report_id, task_id, fmt, str(path), json_text(summary), now_text(), operator),
        )
        self.log(operator, "导出校核报告", "report_export", report_id, "成功", summary)
        return self.db.one("SELECT * FROM report_export WHERE id = ?", (report_id,))

    def _paragraphs(
        self,
        task: dict[str, Any],
        measurements: list[dict[str, Any]],
        checks: list[dict[str, Any]],
        visions: list[dict[str, Any]],
        inference_runs: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> list[str]:
        return [
            f"软件名称：{APP_NAME} {APP_VERSION}",
            f"任务编号：{task['task_no']}；线路名称：{task['line_name']}；标段：{task['section_name']}；验收批次：{task['batch_no']}。",
            "本报告依据已导入的 GIM-like 设计模型、CSV 点云资料和现场影像资料生成。影像部分由本地目标检测模型定位线路构件，再由可配置验收规则计算缺陷候选。",
            f"本次共形成点云量测结果 {len(measurements)} 条，模型点云偏差校核结果 {len(checks)} 条，影像模型运行记录 {len(inference_runs)} 条，影像缺陷候选 {len(visions)} 条，问题台账记录 {len(issues)} 条。",
            "系统输出属于 AI 初判和辅助校核结果。系统保留模型版本、推理设备、模型分数、规则分数、证据图及问题台账；最终验收结论须由具备权限的验收人员依据正式标准表复核确认。",
        ]

    def _tables(
        self,
        measurements: list[dict[str, Any]],
        checks: list[dict[str, Any]],
        visions: list[dict[str, Any]],
        inference_runs: list[dict[str, Any]],
        model_registry: list[dict[str, Any]],
        acceptance_rules: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> list[tuple[str, list[list[str]]]]:
        measurement_rows = [["校核项", "实测值", "单位", "量测方法", "置信度"]]
        for item in measurements:
            measurement_rows.append([
                item["check_item"],
                str(item["measured_value"]),
                item["unit"],
                item["method"],
                str(item["confidence"]),
            ])
        check_rows = [["校核项", "设计值", "实测值", "偏差", "阈值", "状态", "等级"]]
        for item in checks:
            check_rows.append([
                item["check_item"],
                str(item["design_value"]),
                str(item["measured_value"]),
                str(item["deviation"]),
                str(item["threshold"]),
                item["status"],
                item["level"],
            ])
        vision_rows = [["目标", "缺陷", "综合置信度", "模型分数", "规则分数", "规则编号", "状态", "等级", "证据图"]]
        for item in visions:
            vision_rows.append([
                item["target_type"],
                item["defect_type"],
                str(item["confidence"]),
                str(item.get("model_score", "")),
                str(item.get("rule_score", "")),
                item.get("rule_id", ""),
                item["status"],
                item["level"],
                item["snapshot_path"],
            ])
        inference_rows = [["照片编号", "模型", "版本", "设备", "状态", "耗时(ms)", "异常信息"]]
        for item in inference_runs:
            inference_rows.append([
                item["image_id"],
                item["model_id"],
                item["model_revision"],
                item["device"],
                item["status"],
                str(item["duration_ms"]),
                item["error_message"],
            ])
        model_rows = [["模型", "版本", "许可证", "安装状态", "推理设备", "本地目录"]]
        for item in model_registry:
            model_rows.append([
                item["display_name"],
                item["revision"],
                item["license"],
                item["install_status"],
                item["device"],
                item["local_path"],
            ])
        rule_rows = [["规则编号", "分类", "名称", "严重度", "版本", "启用状态", "标准依据"]]
        for item in acceptance_rules:
            rule_rows.append([
                item["id"],
                item["module"],
                item["name"],
                item["severity"],
                str(item["version"]),
                "启用" if item["enabled"] else "停用",
                item["standard_basis"],
            ])
        issue_rows = [["问题类型", "等级", "复核状态", "整改状态", "说明"]]
        for item in issues:
            issue_rows.append([item["issue_type"], item["level"], item["review_status"], item["rectify_status"], item["description"]])
        return [
            ("点云量测结果", measurement_rows),
            ("模型点云偏差校核结果", check_rows),
            ("影像模型运行记录", inference_rows),
            ("AI模型登记信息", model_rows),
            ("验收规则版本", rule_rows),
            ("影像缺陷候选", vision_rows),
            ("问题台账", issue_rows),
        ]

    def _markdown(self, title: str, paragraphs: list[str], tables: list[tuple[str, list[list[str]]]]) -> str:
        lines = [f"# {title}", ""]
        lines.extend(paragraphs)
        lines.append("")
        for table_title, rows in tables:
            lines.extend([f"## {table_title}", ""])
            header = rows[0]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("| " + " | ".join("---" for _ in header) + " |")
            for row in rows[1:]:
                lines.append("| " + " | ".join(str(cell).replace("|", "/") for cell in row) + " |")
            lines.append("")
        return "\n".join(lines)
