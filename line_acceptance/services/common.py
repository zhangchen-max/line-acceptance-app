from __future__ import annotations

from pathlib import Path
from typing import Any

from ..database import Database, json_text
from ..ids import new_id, now_text


class ServiceBase:
    def __init__(self, db: Database, root_dir: Path | None = None):
        self.db = db
        self.root_dir = root_dir

    def log(
        self,
        operator: str,
        action: str,
        target_type: str,
        target_id: str,
        result: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO operation_log
            (id, operator, action, target_type, target_id, result, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("LOG"),
                operator or "system",
                action,
                target_type,
                target_id,
                result,
                json_text(detail or {}),
                now_text(),
            ),
        )

    def require_task(self, task_id: str) -> dict[str, Any]:
        task = self.db.one("SELECT * FROM acceptance_task WHERE id = ?", (task_id,))
        if not task:
            raise ValueError(f"验收任务不存在：{task_id}")
        return task

    def resolve_path(self, file_path: str | Path) -> Path:
        path = Path(file_path)
        if path.is_absolute():
            return path
        if self.root_dir:
            return self.root_dir / path
        return path

    def relative_path(self, file_path: str | Path) -> str:
        path = Path(file_path)
        if self.root_dir:
            try:
                return str(path.resolve().relative_to(self.root_dir.resolve())).replace("\\", "/")
            except ValueError:
                pass
        return str(path).replace("\\", "/")
