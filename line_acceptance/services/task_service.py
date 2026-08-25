from __future__ import annotations

from typing import Any

from ..ids import new_id, now_text, task_no
from .common import ServiceBase


class TaskService(ServiceBase):
    def create_task(self, payload: dict[str, Any], operator: str = "资料管理员") -> dict[str, Any]:
        required = ["project_name", "line_name", "section_name", "batch_no", "owner"]
        missing = [field for field in required if not str(payload.get(field, "")).strip()]
        if missing:
            raise ValueError("缺少必填字段：" + "、".join(missing))
        task_id = new_id("T")
        now = now_text()
        self.db.execute(
            """
            INSERT INTO acceptance_task
            (id, task_no, project_name, line_name, section_name, batch_no,
             construction_unit, owner, acceptance_scope, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                task_no(),
                payload["project_name"].strip(),
                payload["line_name"].strip(),
                payload["section_name"].strip(),
                payload["batch_no"].strip(),
                payload.get("construction_unit", "").strip(),
                payload["owner"].strip(),
                payload.get("acceptance_scope", "线路工程竣工验收资料校核").strip(),
                "待导入",
                now,
                now,
            ),
        )
        self.log(operator, "创建验收任务", "acceptance_task", task_id, "成功", payload)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        task = self.require_task(task_id)
        task["models"] = self.db.all("SELECT * FROM design_model WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        task["components"] = self.db.all("SELECT * FROM model_component WHERE task_id = ? ORDER BY component_type, component_code", (task_id,))
        task["pointclouds"] = self.db.all("SELECT * FROM pointcloud_asset WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        task["pointcloud_slices"] = self.db.all("SELECT * FROM pointcloud_slice WHERE task_id = ? ORDER BY grid_x, grid_y", (task_id,))
        task["pointcloud_objects"] = self.db.all("SELECT * FROM pointcloud_object WHERE task_id = ? ORDER BY object_type, object_code", (task_id,))
        task["measurements"] = self.db.all("SELECT * FROM pointcloud_measurement WHERE task_id = ? ORDER BY check_item", (task_id,))
        task["images"] = self.db.all("SELECT * FROM image_asset WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        task["registrations"] = self.db.all("SELECT * FROM registration_result WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        task["geometry_results"] = self.db.all("SELECT * FROM geometry_check_result WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        task["heatmap_markers"] = self.db.all("SELECT * FROM heatmap_marker WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        task["vision_results"] = self.db.all("SELECT * FROM vision_defect_result WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        task["vision_inference_runs"] = self.db.all(
            "SELECT * FROM vision_inference_run WHERE task_id = ? ORDER BY created_at DESC",
            (task_id,),
        )
        task["issues"] = self.db.all("SELECT * FROM acceptance_issue WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        task["reports"] = self.db.all("SELECT * FROM report_export WHERE task_id = ? ORDER BY export_time DESC", (task_id,))
        return task

    def list_tasks(self) -> list[dict[str, Any]]:
        return self.db.all(
            """
            SELECT t.*,
                   (SELECT COUNT(*) FROM geometry_check_result g WHERE g.task_id = t.id) AS geometry_count,
                   (SELECT COUNT(*) FROM vision_defect_result v WHERE v.task_id = t.id) AS vision_count,
                   (SELECT COUNT(*) FROM acceptance_issue i WHERE i.task_id = t.id) AS issue_count,
                   (SELECT COUNT(*) FROM pointcloud_measurement m WHERE m.task_id = t.id) AS measurement_count
            FROM acceptance_task t
            ORDER BY t.created_at DESC
            """
        )

    def set_status(self, task_id: str, status: str, operator: str = "system") -> None:
        self.require_task(task_id)
        self.db.execute(
            "UPDATE acceptance_task SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_text(), task_id),
        )
        self.log(operator, "更新任务状态", "acceptance_task", task_id, "成功", {"status": status})

    def summary(self) -> dict[str, Any]:
        rows = self.db.all("SELECT status, COUNT(*) AS total FROM acceptance_task GROUP BY status ORDER BY status")
        issue_rows = self.db.all("SELECT level, COUNT(*) AS total FROM acceptance_issue GROUP BY level ORDER BY level")
        return {
            "task_count": sum(row["total"] for row in rows),
            "tasks_by_status": rows,
            "issues_by_level": issue_rows,
            "geometry_count": self.db.one("SELECT COUNT(*) AS total FROM geometry_check_result")["total"],
            "vision_count": self.db.one("SELECT COUNT(*) AS total FROM vision_defect_result")["total"],
            "measurement_count": self.db.one("SELECT COUNT(*) AS total FROM pointcloud_measurement")["total"],
            "report_count": self.db.one("SELECT COUNT(*) AS total FROM report_export")["total"],
        }
