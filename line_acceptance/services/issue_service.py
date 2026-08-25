from __future__ import annotations

from typing import Any

from ..ids import now_text
from .common import ServiceBase


class IssueService(ServiceBase):
    def list_issues(self, task_id: str | None = None, level: str | None = None, keyword: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        if level:
            clauses.append("level = ?")
            params.append(level)
        if keyword:
            clauses.append("(issue_type LIKE ? OR description LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return self.db.all(f"SELECT * FROM acceptance_issue{where} ORDER BY updated_at DESC", params)

    def review_issue(self, issue_id: str, payload: dict[str, Any], operator: str = "复核人员") -> dict[str, Any]:
        issue = self._require_issue(issue_id)
        action = payload.get("action", "确认")
        if action not in {"确认", "修改后确认", "驳回"}:
            raise ValueError("复核动作仅支持：确认、修改后确认、驳回")
        if issue["review_status"] in {"已确认", "已驳回"} and not payload.get("allow_repeat"):
            raise ValueError("该问题已经完成复核，不能重复复核")
        review_status = "已驳回" if action == "驳回" else "已确认"
        rectify_status = "不需整改" if action == "驳回" else payload.get("rectify_status", "待整改")
        description = payload.get("description", issue["description"])
        now = now_text()
        self.db.execute(
            """
            UPDATE acceptance_issue
            SET review_status = ?, rectify_status = ?, reviewer = ?, review_opinion = ?,
                description = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                review_status,
                rectify_status,
                payload.get("reviewer", operator),
                payload.get("opinion", ""),
                description,
                now,
                issue_id,
            ),
        )
        self.log(operator, "复核验收问题", "acceptance_issue", issue_id, review_status, payload)
        return self._require_issue(issue_id)

    def update_rectify_status(self, issue_id: str, status: str, operator: str = "复核人员") -> dict[str, Any]:
        issue = self._require_issue(issue_id)
        allowed = {"待整改", "整改中", "已整改", "已关闭", "不需整改", "未整改"}
        if status not in allowed:
            raise ValueError("整改状态不合法")
        if issue["review_status"] == "待复核" and status != "未整改":
            raise ValueError("问题尚未复核确认，不能进入整改闭环")
        self.db.execute(
            "UPDATE acceptance_issue SET rectify_status = ?, updated_at = ? WHERE id = ?",
            (status, now_text(), issue_id),
        )
        self.log(operator, "更新整改状态", "acceptance_issue", issue_id, "成功", {"status": status})
        return self._require_issue(issue_id)

    def _require_issue(self, issue_id: str) -> dict[str, Any]:
        issue = self.db.one("SELECT * FROM acceptance_issue WHERE id = ?", (issue_id,))
        if not issue:
            raise ValueError(f"验收问题不存在：{issue_id}")
        return issue
