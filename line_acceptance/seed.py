from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

from .app_context import AppContext


def seed_demo(context: AppContext, reset: bool = False) -> dict:
    ensure_sample_files(context.config.root_dir)
    if reset:
        context.db.reset()
        context.rule_service.ensure_seeded()
    existing = context.tasks.list_tasks()
    if existing and not reset:
        task = context.tasks.get_task(existing[0]["id"])
        if not task["measurements"]:
            return complete_demo_workflow(context, task["id"])
        return task

    task = context.tasks.create_task(
        {
            "project_name": "华东示范线路竣工验收工程",
            "line_name": "220kV 东湖-南桥线路",
            "section_name": "一标段 T001-T006",
            "batch_no": "YS-2026-07",
            "construction_unit": "示例施工单位",
            "owner": "验收工程师",
            "acceptance_scope": "GIM-like 模型、点云、影像资料及问题台账校核",
        },
        operator="system",
    )
    task_id = task["id"]
    context.models.import_design_model(task_id, {"file_path": "sample_data/design_model.json", "model_version": "GIM-2026.07"}, operator="system")
    context.assets.import_pointcloud(
        task_id,
        {
            "file_name": "T001_T006_pointcloud.csv",
            "file_path": "sample_data/pointcloud.csv",
            "coordinate_system": "CGCS2000",
        },
        operator="system",
    )
    context.assets.import_images(task_id, {}, operator="system")
    return complete_demo_workflow(context, task_id)


def complete_demo_workflow(context: AppContext, task_id: str) -> dict:
    context.tasks.set_status(task_id, "待校核", operator="system")
    context.pointcloud.process_task_pointcloud(task_id, {"grid_size": 40}, operator="system")
    context.registration.run_registration(task_id, {"control_point_count": 5, "base_residual": 0.078}, operator="system")
    context.checks.run_model_pointcloud_compare(task_id, {}, operator="system")
    context.vision.analyze_task_images(task_id, {}, operator="system", demo=True)
    context.fusion.build_scene(task_id, persist=True)
    issues = context.issues.list_issues(task_id=task_id)
    context.tasks.set_status(task_id, "待复核" if issues else "校核通过", operator="system")
    context.reports.export_report(task_id, {"format": "docx"}, operator="system")
    return context.tasks.get_task(task_id)


def ensure_sample_files(root_dir: Path) -> None:
    sample_dir = root_dir / "sample_data"
    image_dir = sample_dir / "images"
    sample_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / "design_model.json").write_text(json.dumps(design_model_data(), ensure_ascii=False, indent=2), encoding="utf-8")
    (sample_dir / "pointcloud.csv").write_text(pointcloud_csv(), encoding="utf-8")
    write_insulator_image(image_dir / "T001_绝缘子串_A相.jpg")
    write_damper_image(image_dir / "T001_防震锤_小号侧.jpg")


def design_model_data() -> dict:
    return {
        "model_type": "GIM-like JSON",
        "model_version": "GIM-2026.07",
        "coordinate_system": "CGCS2000",
        "components": [
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
        ],
    }


def pointcloud_csv() -> str:
    rows = ["x,y,z,class,intensity"]
    for x in range(-10, 421, 20):
        for y in range(-18, 31, 12):
            rows.append(f"{x:.2f},{y:.2f},0.20,ground,0.35")
    for x in (-4.02, 4.02):
        for y in (-4.02, 4.02):
            for dz in (0.0, 0.25, 0.5):
                rows.append(f"{x:.2f},{y:.2f},{dz:.2f},foundation,0.72")
    for z in [i * 2.0 for i in range(19)]:
        ratio = z / 36.0
        cx = 0.18 * ratio
        cy = 0.05 * ratio
        for angle in (0, 2.09, 4.18):
            x = cx + math.cos(angle) * 0.55
            y = cy + math.sin(angle) * 0.55
            rows.append(f"{x:.3f},{y:.3f},{z:.3f},tower,0.86")
    sag = 10.21
    for i in range(83):
        x = 410 * i / 82
        t = x / 410
        y = math.sin(t * math.pi) * 0.45
        z = 35 - sag * 4 * t * (1 - t)
        rows.append(f"{x:.3f},{y:.3f},{z:.3f},conductor,0.80")
    for x in range(134, 157, 3):
        for y in range(-6, 7, 3):
            z = 17.92 + (0.08 if y == 0 else 0.0)
            rows.append(f"{x:.2f},{y:.2f},{z:.2f},crossing,0.58")
    for x in (196.0, 201.0, 205.0, 209.0, 214.0):
        for y in (2.41, 4.2, 6.4, 8.1):
            z = 13.5 + (x - 196.0) * 0.05 + y * 0.08
            rows.append(f"{x:.2f},{y:.2f},{z:.2f},vegetation,0.62")
    return "\n".join(rows) + "\n"


def write_insulator_image(path: Path) -> None:
    image = Image.new("RGB", (960, 540), (236, 242, 246))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 355, 960, 540), fill=(210, 224, 213))
    draw.line((120, 110, 840, 96), fill=(72, 92, 111), width=5)
    draw.line((250, 130, 690, 128), fill=(78, 78, 78), width=8)
    for i in range(8):
        cx = 340 + i * 34
        cy = 165 + i * 16
        draw.ellipse((cx - 18, cy - 10, cx + 18, cy + 10), fill=(238, 246, 250), outline=(74, 99, 122), width=3)
    draw.line((475, 222, 505, 252), fill=(164, 43, 43), width=5)
    draw.line((478, 250, 515, 224), fill=(164, 43, 43), width=4)
    draw.ellipse((600, 215, 630, 245), fill=(40, 43, 46))
    image.save(path, quality=92)


def write_damper_image(path: Path) -> None:
    image = Image.new("RGB", (960, 540), (232, 240, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 370, 960, 540), fill=(219, 229, 218))
    draw.line((80, 242, 890, 242), fill=(68, 72, 76), width=7)
    draw.line((490, 242, 560, 304), fill=(54, 57, 60), width=6)
    draw.ellipse((538, 292, 610, 330), fill=(51, 54, 57), outline=(28, 30, 32), width=3)
    draw.ellipse((440, 238, 490, 266), fill=(52, 55, 58), outline=(30, 32, 34), width=3)
    draw.line((610, 242, 704, 242), fill=(158, 46, 46), width=4)
    image.save(path, quality=92)
