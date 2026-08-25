from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from ..ids import new_id, now_text
from .common import ServiceBase


class AssetService(ServiceBase):
    def import_uploaded_pointcloud(
        self,
        task_id: str,
        file_name: str,
        content: bytes,
        coordinate_system: str = "CGCS2000",
        operator: str = "资料管理员",
    ) -> dict[str, Any]:
        task = self.require_task(task_id)
        if not content:
            raise ValueError("上传的点云文件为空")
        if Path(file_name).suffix.lower() != ".csv":
            raise ValueError("第一阶段仅支持 CSV 点云")
        try:
            header = content.decode("utf-8-sig").splitlines()[0].lower().replace(" ", "")
        except (UnicodeDecodeError, IndexError) as exc:
            raise ValueError("点云文件不是有效的 UTF-8 CSV") from exc
        required = {"x", "y", "z", "class", "intensity"}
        if not required.issubset(set(header.split(","))):
            raise ValueError("CSV 点云必须包含 x,y,z,class,intensity 字段")
        target_dir = self.root_dir / "storage" / "projects" / task["task_no"] / "pointcloud"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{new_id('FILE')}_{safe_file_stem(file_name)}.csv"
        target.write_bytes(content)
        return self.import_pointcloud(
            task_id,
            {
                "file_name": file_name,
                "file_path": self.relative_path(target),
                "coordinate_system": coordinate_system,
            },
            operator=operator,
        )

    def import_pointcloud(self, task_id: str, payload: dict[str, Any], operator: str = "资料管理员") -> dict[str, Any]:
        self.require_task(task_id)
        file_path = payload.get("file_path") or "sample_data/pointcloud.csv"
        metrics = self._pointcloud_metrics(file_path, payload)
        asset_id = new_id("PC")
        file_name = payload.get("file_name") or Path(file_path).name
        coordinate_system = payload.get("coordinate_system", "CGCS2000")
        status, message = self._quality_status(metrics["point_count"], metrics["density"], coordinate_system)
        self.db.execute(
            """
            INSERT INTO pointcloud_asset
            (id, task_id, file_name, file_path, point_count, coordinate_system,
             density, quality_status, quality_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                task_id,
                file_name,
                file_path,
                metrics["point_count"],
                coordinate_system,
                metrics["density"],
                status,
                message,
                now_text(),
            ),
        )
        self.log(operator, "导入点云资料", "pointcloud_asset", asset_id, status, metrics)
        return self.db.one("SELECT * FROM pointcloud_asset WHERE id = ?", (asset_id,))

    def import_images(self, task_id: str, payload: dict[str, Any], operator: str = "资料管理员") -> list[dict[str, Any]]:
        self.require_task(task_id)
        images = payload.get("images") or default_images()
        inserted: list[dict[str, Any]] = []
        for item in images:
            image_id = new_id("IMG")
            clarity = float(item.get("clarity_score", 0.82))
            source_type = item.get("source_type", "照片")
            status = "已抽帧" if source_type == "视频抽帧" else "待处理"
            if clarity < 0.45:
                status = "识别失败"
            self.db.execute(
                """
                INSERT INTO image_asset
                (id, task_id, file_name, file_path, source_type, frame_time, shoot_position,
                 clarity_score, process_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    image_id,
                    task_id,
                    item.get("file_name", "现场照片.jpg"),
                    item.get("file_path", "sample_data/images/现场照片.jpg"),
                    source_type,
                    item.get("frame_time", ""),
                    item.get("shoot_position", "T001 杆塔小号侧"),
                    clarity,
                    status,
                    now_text(),
                ),
            )
            inserted.append(self.db.one("SELECT * FROM image_asset WHERE id = ?", (image_id,)))
        self.log(operator, "导入影像资料", "image_asset", task_id, "成功", {"count": len(inserted)})
        return inserted

    def pointclouds(self, task_id: str) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM pointcloud_asset WHERE task_id = ? ORDER BY created_at DESC", (task_id,))

    def images(self, task_id: str) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM image_asset WHERE task_id = ? ORDER BY created_at DESC", (task_id,))

    def _pointcloud_metrics(self, file_path: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = self.resolve_path(file_path)
        if path.exists():
            return inspect_pointcloud_csv(path)
        return {
            "point_count": int(payload.get("point_count", 0)),
            "density": float(payload.get("density", 0)),
            "bounds": payload.get("bounds", [0, 0, 0, 0, 0, 0]),
            "class_distribution": {},
        }

    def _quality_status(self, point_count: int, density: float, coordinate_system: str) -> tuple[str, str]:
        if not coordinate_system:
            return "检查失败", "缺少坐标系信息，不能进入配准流程。"
        if point_count < 50:
            return "需复核", "点数较少，允许进入演示校核，但正式验收时需要补充原始点云。"
        if density < 0.02:
            return "需复核", "点云密度偏低，校核结论需要人工复核。"
        return "检查通过", "点云资料完整，密度和坐标信息满足本地校核要求。"


def inspect_pointcloud_csv(path: Path) -> dict[str, Any]:
    count = 0
    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")
    classes: Counter[str] = Counter()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            count += 1
            x = float(row.get("x", 0) or 0)
            y = float(row.get("y", 0) or 0)
            z = float(row.get("z", 0) or 0)
            cls = row.get("class", "unknown") or "unknown"
            classes[cls] += 1
            min_x, min_y, min_z = min(min_x, x), min(min_y, y), min(min_z, z)
            max_x, max_y, max_z = max(max_x, x), max(max_y, y), max(max_z, z)
    if count == 0:
        return {"point_count": 0, "density": 0.0, "bounds": [0, 0, 0, 0, 0, 0], "class_distribution": {}}
    width = max(max_x - min_x, 1)
    height = max(max_y - min_y, 1)
    density = count / (width * height)
    return {
        "point_count": count,
        "density": round(density, 4),
        "bounds": [round(min_x, 3), round(min_y, 3), round(min_z, 3), round(max_x, 3), round(max_y, 3), round(max_z, 3)],
        "class_distribution": dict(classes),
    }


def default_images() -> list[dict[str, Any]]:
    return [
        {
            "file_name": "T001_绝缘子串_A相.jpg",
            "file_path": "sample_data/images/T001_绝缘子串_A相.jpg",
            "source_type": "照片",
            "shoot_position": "T001 横担 A 相绝缘子串",
            "clarity_score": 0.88,
        },
        {
            "file_name": "T001_防震锤_小号侧.jpg",
            "file_path": "sample_data/images/T001_防震锤_小号侧.jpg",
            "source_type": "照片",
            "shoot_position": "T001 小号侧导线",
            "clarity_score": 0.79,
        },
    ]


def safe_file_stem(file_name: str) -> str:
    value = Path(file_name or "pointcloud").stem
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"})
    return cleaned or "pointcloud"
