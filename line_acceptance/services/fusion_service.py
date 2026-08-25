from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ..database import json_text
from ..ids import new_id, now_text
from .common import ServiceBase
from .pointcloud_service import PointCloudData, read_pointcloud_csv


MAX_SCENE_POINTS = 15_000
MAX_PROFILE_POINTS = 4_500
CHECK_LABELS = {
    "foundation_span": "基础根开偏差",
    "tower_inclination": "杆塔倾斜度",
    "conductor_sag": "导线弧垂",
    "crossing_clearance": "交叉跨越净空",
    "channel_distance": "通道物距",
}
CLASS_LABELS = {
    "ground": "地面",
    "foundation": "基础",
    "tower": "杆塔",
    "conductor": "导线",
    "crossing": "交跨对象",
    "vegetation": "植被",
    "unknown": "未分类",
}


class FusionService(ServiceBase):
    def __init__(self, db, root_dir: Path | None = None):
        super().__init__(db, root_dir)

    def build_scene(self, task_id: str, persist: bool = False) -> dict[str, Any]:
        self.require_task(task_id)
        components = self.db.all("SELECT * FROM model_component WHERE task_id = ? ORDER BY component_code", (task_id,))
        assets = self.db.all("SELECT * FROM pointcloud_asset WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        slices = self.db.all("SELECT * FROM pointcloud_slice WHERE task_id = ? ORDER BY grid_x, grid_y", (task_id,))
        measurements = self.db.all("SELECT * FROM pointcloud_measurement WHERE task_id = ? ORDER BY check_item", (task_id,))
        checks = self.db.all("SELECT * FROM geometry_check_result WHERE task_id = ? ORDER BY check_item", (task_id,))
        markers = self.db.all("SELECT * FROM heatmap_marker WHERE task_id = ? ORDER BY value DESC", (task_id,))
        images = self.db.all("SELECT * FROM image_asset WHERE task_id = ? ORDER BY created_at", (task_id,))
        visions = self.db.all("SELECT * FROM vision_defect_result WHERE task_id = ? ORDER BY created_at", (task_id,))
        issues = self.db.all("SELECT * FROM acceptance_issue WHERE task_id = ? ORDER BY updated_at DESC", (task_id,))

        warnings: list[dict[str, str]] = []
        data = self._load_pointcloud(assets, warnings)
        if not components:
            warnings.append(warning("missing_model", "尚未导入设计模型，无法显示设计构件。", "warning"))
        if not assets:
            warnings.append(warning("missing_pointcloud", "尚未导入点云，纵断面仅显示设计资料。", "warning"))
        elif not slices:
            warnings.append(warning("unprocessed_pointcloud", "点云已导入但尚未处理，请先执行点云处理。", "warning"))
        if not checks:
            warnings.append(warning("missing_checks", "尚未执行模型点云校核，暂不显示验收偏差。", "info"))

        localized_images, unlocated_images = build_image_layers(images, visions, components, data)
        if unlocated_images:
            warnings.append(warning("unlocated_images", f"{len(unlocated_images)} 张影像没有可识别的构件位置，已归入待定位证据。", "info"))

        sampled = sample_pointcloud(data, MAX_SCENE_POINTS)
        profile = build_profile(components, measurements, checks, issues, sampled, unlocated_images)
        scene3d = build_scene3d(components, profile, sampled, data.count if data else 0)
        selection_index = build_selection_index(
            components,
            measurements,
            checks,
            issues,
            localized_images,
            unlocated_images,
            visions,
            profile,
        )
        bounds = scene_bounds(components, slices, markers)
        coordinate_system = assets[0]["coordinate_system"] if assets else "未提供"
        scene = {
            "schema_version": "2.0",
            "task_id": task_id,
            "bounds": bounds,
            "layers": {
                "model": [component_layer(item) for item in components],
                "pointcloud": [slice_layer(item) for item in slices],
                "heatmap": [marker_layer(item) for item in markers],
                "images": localized_images,
                "issues": [issue_layer(item) for item in issues],
            },
            "profile": profile,
            "scene3d": scene3d,
            "selection_index": selection_index,
            "warnings": warnings,
            "coordinate_info": {
                "coordinate_system": coordinate_system,
                "horizontal_unit": "m",
                "vertical_unit": "m",
                "source": "GIM-like JSON + CSV 点云",
                "contains_inferred_geometry": bool(profile["inferred_geometry"]),
                "inference_note": "缺失的线路支撑端及构件外形根据设计参数生成，仅用于空间表达。",
            },
            "statistics": {
                "component_count": len(components),
                "slice_count": len(slices),
                "measurement_count": len(measurements),
                "heatmap_count": len(markers),
                "image_count": len(images),
                "localized_image_count": len(localized_images),
                "unlocated_image_count": len(unlocated_images),
                "defect_count": len(visions),
                "issue_count": len(issues),
                "source_point_count": data.count if data else 0,
                "scene_point_count": sampled.count if sampled else 0,
            },
            "legend": [
                {"key": "design", "label": "设计模型", "color": "#63c7ff"},
                {"key": "measured", "label": "实测点云", "color": "#8de3cf"},
                {"key": "qualified", "label": "符合", "color": "#45d483"},
                {"key": "attention", "label": "关注", "color": "#f4b84a"},
                {"key": "serious", "label": "严重", "color": "#ff6674"},
            ],
        }
        if persist:
            self.db.execute(
                """
                INSERT INTO fusion_scene (id, task_id, scene_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (new_id("FS"), task_id, json_text(scene), now_text()),
            )
        return scene

    def _load_pointcloud(
        self,
        assets: list[dict[str, Any]],
        warnings: list[dict[str, str]],
    ) -> PointCloudData | None:
        if not assets:
            return None
        path = self.resolve_path(assets[0]["file_path"])
        if not path.exists():
            warnings.append(warning("pointcloud_file_missing", f"点云文件不存在：{assets[0]['file_path']}", "error"))
            return None
        try:
            data = read_pointcloud_csv(path)
        except (OSError, UnicodeError, ValueError) as exc:
            warnings.append(warning("pointcloud_read_failed", f"点云读取失败：{exc}", "error"))
            return None
        return data if data.count else None


def warning(code: str, message: str, level: str) -> dict[str, str]:
    return {"code": code, "message": message, "level": level}


def component_layer(item: dict[str, Any]) -> dict[str, Any]:
    bbox = item.get("bbox_json") or [0, 0, 0, 0]
    return {
        "id": item["id"],
        "code": item["component_code"],
        "type": item["component_type"],
        "bbox": bbox,
        "properties": item.get("properties_json") or {},
        "label": f"{item['component_code']} {item['component_type']}",
        "design_value": item["design_value"],
        "unit": item["unit"],
    }


def slice_layer(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "grid": [item["grid_x"], item["grid_y"]],
        "bbox": item.get("bounds_json") or [0, 0, 0, 0, 0, 0],
        "density": item["density"],
        "point_count": item["point_count"],
        "dominant_class": item["dominant_class"],
        "z_range": [item["min_z"], item["max_z"]],
    }


def marker_layer(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "source_id": item["source_id"],
        "x": item["x"],
        "y": item["y"],
        "value": item["value"],
        "level": item["level"],
        "label": item["label"],
        "check_item": item["check_item"],
    }


def build_image_layers(
    images: list[dict[str, Any]],
    visions: list[dict[str, Any]],
    components: list[dict[str, Any]],
    data: PointCloudData | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in visions:
        by_image[item["image_id"]].append(item)
    component_by_code = {item["component_code"].upper(): item for item in components}
    localized: list[dict[str, Any]] = []
    unlocated: list[dict[str, Any]] = []
    for index, image in enumerate(images):
        match = re.search(r"(?<![A-Za-z0-9])([A-Za-z]+\d+)(?![A-Za-z0-9])", image.get("shoot_position") or "")
        component = component_by_code.get(match.group(1).upper()) if match else None
        base = {
            "id": image["id"],
            "file_name": image["file_name"],
            "file_path": image["file_path"],
            "label": f"IMG-{index + 1:02d}",
            "shoot_position": image["shoot_position"],
            "status": image["process_status"],
            "defects": by_image.get(image["id"], []),
            "component_id": component["id"] if component else None,
            "component_code": component["component_code"] if component else None,
        }
        if component:
            x, y = bbox_center(component.get("bbox_json") or [])
            z = terrain_height(data, x) + component_height(component, data)
            localized.append({**base, "located": True, "x": x, "y": y, "z": z + 2.5})
        else:
            unlocated.append({**base, "located": False, "x": None, "y": None, "z": None})
    return localized, unlocated


def issue_layer(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence_json") or {}
    has_position = evidence.get("x") is not None and evidence.get("y") is not None
    return {
        "id": item["id"],
        "source_id": item["source_id"],
        "source_type": item["source_type"],
        "issue_type": item["issue_type"],
        "level": item["level"],
        "review_status": item["review_status"],
        "rectify_status": item["rectify_status"],
        "located": has_position,
        "x": float(evidence["x"]) if has_position else None,
        "y": float(evidence["y"]) if has_position else None,
        "description": item["description"],
    }


def sample_pointcloud(data: PointCloudData | None, limit: int) -> PointCloudData | None:
    if data is None or data.count <= limit:
        return data
    min_x, min_y = float(np.min(data.x)), float(np.min(data.y))
    width = max(float(np.ptp(data.x)), 1.0)
    height = max(float(np.ptp(data.y)), 1.0)
    grid_count = max(4, int(math.sqrt(limit / max(len(set(data.cls.tolist())), 1))))
    gx = np.minimum(((data.x - min_x) / width * grid_count).astype(int), grid_count - 1)
    gy = np.minimum(((data.y - min_y) / height * grid_count).astype(int), grid_count - 1)
    buckets: dict[tuple[str, int, int], list[int]] = defaultdict(list)
    for index, key in enumerate(zip(data.cls.tolist(), gx.tolist(), gy.tolist())):
        buckets[(str(key[0]), int(key[1]), int(key[2]))].append(index)
    keys = sorted(buckets)
    selected: list[int] = []
    cursor = 0
    while len(selected) < limit:
        added = False
        for key in keys:
            values = buckets[key]
            if cursor < len(values):
                selected.append(values[cursor])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        cursor += 1
    indexes = np.array(sorted(selected), dtype=int)
    return subset(data, indexes)


def subset(data: PointCloudData, indexes: np.ndarray) -> PointCloudData:
    return PointCloudData(
        x=data.x[indexes],
        y=data.y[indexes],
        z=data.z[indexes],
        cls=data.cls[indexes],
        intensity=data.intensity[indexes],
    )


def build_profile(
    components: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    data: PointCloudData | None,
    unlocated_images: list[dict[str, Any]],
) -> dict[str, Any]:
    terrain = aggregate_class_profile(data, "ground", 180)
    measured_conductor = aggregate_class_profile(data, "conductor", 320, include_y=True)
    towers = build_towers(components, data)
    design_conductors = build_design_conductors(components, towers, data)
    inferred_geometry = [item["id"] for item in towers if item.get("inferred")]
    semantic_objects = build_semantic_objects(data, components)
    checks_by_item = {item["check_item"]: item for item in checks}
    measurements_by_item = {item["check_item"]: item for item in measurements}
    dimensions = []
    for check_item in CHECK_LABELS:
        check = checks_by_item.get(check_item)
        measurement = measurements_by_item.get(check_item)
        if not check and not measurement:
            continue
        evidence = (check or {}).get("evidence_json") or (measurement or {}).get("evidence_json") or {}
        x = float(evidence.get("x", default_check_position(check_item)))
        dimensions.append(
            {
                "id": (check or measurement)["id"],
                "check_item": check_item,
                "label": CHECK_LABELS[check_item],
                "x": x,
                "y": float(evidence.get("y", 0)),
                "z": profile_z_at(check_item, x, terrain, measured_conductor, towers, semantic_objects),
                "design_value": (check or {}).get("design_value"),
                "measured_value": (check or {}).get("measured_value", (measurement or {}).get("measured_value")),
                "deviation": (check or {}).get("deviation"),
                "threshold": (check or {}).get("threshold"),
                "unit": (measurement or {}).get("unit", ""),
                "status": (check or {}).get("status", "待校核"),
                "level": (check or {}).get("level", "待校核"),
                "confidence": (measurement or {}).get("confidence"),
                "method": (measurement or {}).get("method", ""),
                "suggestion": evidence.get("suggestion", ""),
            }
        )
    issue_markers = []
    for item in issues:
        evidence = item.get("evidence_json") or {}
        if evidence.get("x") is None:
            continue
        x = float(evidence["x"])
        check_item = check_item_for_source(item["source_id"], checks)
        issue_markers.append(
            {
                "id": item["id"],
                "source_id": item["source_id"],
                "x": x,
                "y": float(evidence.get("y", 0)),
                "z": profile_z_at(check_item, x, terrain, measured_conductor, towers, semantic_objects),
                "label": item["issue_type"],
                "level": item["level"],
                "review_status": item["review_status"],
            }
        )
    profile_points = point_rows(sample_pointcloud(data, min(MAX_PROFILE_POINTS, data.count)) if data else None, profile=True)
    bounds = profile_bounds(components, data, towers, design_conductors)
    return {
        "bounds": bounds,
        "terrain": terrain,
        "pointcloud": profile_points,
        "towers": towers,
        "conductors": design_conductors,
        "measured_conductor": measured_conductor,
        "objects": semantic_objects,
        "dimensions": dimensions,
        "issues": issue_markers,
        "unlocated_images": unlocated_images,
        "inferred_geometry": inferred_geometry,
    }


def build_scene3d(
    components: list[dict[str, Any]],
    profile: dict[str, Any],
    data: PointCloudData | None,
    source_point_count: int,
) -> dict[str, Any]:
    components_3d = []
    for item in components:
        bbox = normalize_bbox3d(item.get("bbox_json") or [])
        x, y = bbox_center(item.get("bbox_json") or [])
        base_z = terrain_height(data, x)
        components_3d.append(
            {
                **component_layer(item),
                "bbox3d": bbox,
                "position": [x, y, base_z],
                "height": component_height(item, data),
                "inferred": False,
            }
        )
    for tower in profile["towers"]:
        if not tower.get("inferred"):
            continue
        components_3d.append(
            {
                "id": tower["id"],
                "code": tower["code"],
                "type": "推算支撑端",
                "label": tower["label"],
                "bbox": [tower["x"] - 2, tower["y"] - 2, tower["x"] + 2, tower["y"] + 2],
                "bbox3d": [tower["x"] - 2, tower["y"] - 2, tower["base_z"], tower["x"] + 2, tower["y"] + 2, tower["base_z"] + tower["height"]],
                "position": [tower["x"], tower["y"], tower["base_z"]],
                "height": tower["height"],
                "inferred": True,
                "properties": {},
                "design_value": 0,
                "unit": "m",
            }
        )
    return {
        "bounds": bounds3d(data, components_3d),
        "pointcloud": {
            "positions": point_positions(data),
            "classes": data.cls.tolist() if data else [],
            "intensities": rounded_list(data.intensity) if data else [],
            "source_count": source_point_count,
            "sample_count": data.count if data else 0,
        },
        "components": components_3d,
        "conductors": profile["conductors"],
        "terrain": profile["terrain"],
        "markers": profile["issues"],
    }


def build_selection_index(
    components: list[dict[str, Any]],
    measurements: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    localized_images: list[dict[str, Any]],
    unlocated_images: list[dict[str, Any]],
    visions: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    dimensions = {item["check_item"]: item for item in profile["dimensions"]}
    checks_by_id = {item["id"]: item for item in checks}
    measurements_by_item = {item["check_item"]: item for item in measurements}
    visions_by_id = {item["id"]: item for item in visions}
    images = {item["id"]: item for item in [*localized_images, *unlocated_images]}
    for component in components:
        x, y = bbox_center(component.get("bbox_json") or [])
        result[component["id"]] = {
            "id": component["id"],
            "kind": "component",
            "title": f"{component['component_code']} {component['component_type']}",
            "subtitle": "设计模型构件",
            "level": "正常",
            "location": [x, y, 0],
            "details": [
                {"label": "构件编号", "value": component["component_code"]},
                {"label": "构件类型", "value": component["component_type"]},
                {"label": "设计值", "value": value_with_unit(component["design_value"], component["unit"])},
                {"label": "数据来源", "value": "GIM-like JSON"},
            ],
            "evidence": [],
        }
    for check in checks:
        measurement = measurements_by_item.get(check["check_item"]) or {}
        dimension = dimensions.get(check["check_item"]) or {}
        evidence = check.get("evidence_json") or {}
        result[check["id"]] = {
            "id": check["id"],
            "kind": "check",
            "title": CHECK_LABELS.get(check["check_item"], check["check_item"]),
            "subtitle": evidence.get("position", "模型点云偏差校核"),
            "level": check["level"],
            "status": check["status"],
            "location": [dimension.get("x", 0), dimension.get("y", 0), dimension.get("z", 0)],
            "details": check_details(check, measurement, evidence),
            "evidence": [],
        }
    for issue in issues:
        source_check = checks_by_id.get(issue["source_id"])
        source_vision = visions_by_id.get(issue["source_id"])
        evidence = issue.get("evidence_json") or {}
        location = None
        if evidence.get("x") is not None:
            check_item = source_check["check_item"] if source_check else ""
            dimension = dimensions.get(check_item) or {}
            location = [float(evidence["x"]), float(evidence.get("y", 0)), dimension.get("z", 0)]
        evidence_items = []
        if source_vision:
            image = images.get(source_vision["image_id"])
            if image:
                evidence_items.append(
                    {
                        "type": "image",
                        "image_id": image["id"],
                        "title": image["file_name"],
                        "url": source_vision.get("snapshot_path") or image["file_path"],
                    }
                )
        details = [
            {"label": "问题类型", "value": issue["issue_type"]},
            {"label": "复核状态", "value": issue["review_status"]},
            {"label": "整改状态", "value": issue["rectify_status"]},
            {"label": "问题说明", "value": issue["description"]},
        ]
        if source_check:
            details.extend(check_details(source_check, measurements_by_item.get(source_check["check_item"]) or {}, source_check.get("evidence_json") or {}))
        result[issue["id"]] = {
            "id": issue["id"],
            "kind": "issue",
            "title": issue["issue_type"],
            "subtitle": issue["description"],
            "level": issue["level"],
            "status": issue["review_status"],
            "location": location,
            "details": details,
            "evidence": evidence_items,
        }
    for image in [*localized_images, *unlocated_images]:
        result[image["id"]] = {
            "id": image["id"],
            "kind": "image",
            "title": image["file_name"],
            "subtitle": image["shoot_position"] or "未填写拍摄位置",
            "level": "正常" if image["located"] else "待定位",
            "status": image["status"],
            "location": [image["x"], image["y"], image["z"]] if image["located"] else None,
            "details": [
                {"label": "拍摄位置", "value": image["shoot_position"] or "未填写"},
                {"label": "关联构件", "value": image["component_code"] or "未关联"},
                {"label": "处理状态", "value": image["status"]},
                {"label": "缺陷候选", "value": len(image["defects"])},
            ],
            "evidence": [{"type": "image", "image_id": image["id"], "title": image["file_name"], "url": image["file_path"]}],
        }
    return result


def check_details(check: dict[str, Any], measurement: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    unit = measurement.get("unit", "")
    return [
        {"label": "设计值", "value": value_with_unit(check.get("design_value"), unit)},
        {"label": "实测值", "value": value_with_unit(check.get("measured_value"), unit)},
        {"label": "偏差", "value": value_with_unit(check.get("deviation"), unit)},
        {"label": "允许阈值", "value": value_with_unit(check.get("threshold"), unit)},
        {"label": "验收结论", "value": check.get("status", "待校核")},
        {"label": "量测置信度", "value": measurement.get("confidence", "-")},
        {"label": "量测方法", "value": measurement.get("method", "-")},
        {"label": "复核建议", "value": evidence.get("suggestion", "-")},
    ]


def value_with_unit(value: Any, unit: str) -> str:
    if value is None:
        return "-"
    try:
        number = round(float(value), 4)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:g} {unit}".strip()


def aggregate_class_profile(
    data: PointCloudData | None,
    class_name: str,
    max_points: int,
    include_y: bool = False,
) -> list[dict[str, float]]:
    if data is None:
        return []
    indexes = np.flatnonzero(data.cls == class_name)
    if not indexes.size:
        return []
    order = indexes[np.argsort(data.x[indexes])]
    if order.size > max_points:
        groups = np.array_split(order, max_points)
        order = np.array([group[len(group) // 2] for group in groups if group.size], dtype=int)
    result = []
    for index in order:
        item = {"x": round(float(data.x[index]), 3), "z": round(float(data.z[index]), 3)}
        if include_y:
            item["y"] = round(float(data.y[index]), 3)
        result.append(item)
    return result


def build_towers(components: list[dict[str, Any]], data: PointCloudData | None) -> list[dict[str, Any]]:
    result = []
    for item in components:
        if "杆塔" not in item["component_type"]:
            continue
        x, y = bbox_center(item.get("bbox_json") or [])
        height = component_height(item, data)
        result.append(
            {
                "id": item["id"],
                "code": item["component_code"],
                "label": f"{item['component_code']} 杆塔",
                "x": x,
                "y": y,
                "base_z": terrain_height(data, x),
                "height": height,
                "inferred": False,
            }
        )
    conductor_components = [item for item in components if "导线" in item["component_type"]]
    for conductor in conductor_components:
        bbox = conductor.get("bbox_json") or []
        if len(bbox) < 4:
            continue
        for endpoint, suffix in ((float(bbox[0]), "起点"), (float(bbox[2]), "终点")):
            if any(abs(item["x"] - endpoint) <= 8 for item in result):
                continue
            reference_height = result[0]["height"] if result else conductor_endpoint_height(data, endpoint)
            result.append(
                {
                    "id": f"inferred-support-{conductor['id']}-{suffix}",
                    "code": "推算支撑端",
                    "label": f"{conductor['component_code']} {suffix}（推算）",
                    "x": endpoint,
                    "y": 0,
                    "base_z": terrain_height(data, endpoint),
                    "height": reference_height,
                    "inferred": True,
                }
            )
    return sorted(result, key=lambda item: item["x"])


def build_design_conductors(
    components: list[dict[str, Any]],
    towers: list[dict[str, Any]],
    data: PointCloudData | None,
) -> list[dict[str, Any]]:
    result = []
    for item in components:
        if "导线" not in item["component_type"]:
            continue
        bbox = item.get("bbox_json") or []
        if len(bbox) < 4:
            continue
        start_x, end_x = float(bbox[0]), float(bbox[2])
        start_tower = nearest_tower(towers, start_x)
        end_tower = nearest_tower(towers, end_x)
        start_z = (start_tower["base_z"] + start_tower["height"] - 1.5) if start_tower else conductor_endpoint_height(data, start_x)
        end_z = (end_tower["base_z"] + end_tower["height"] - 1.5) if end_tower else conductor_endpoint_height(data, end_x)
        sag = max(float(item.get("design_value") or 0), 0)
        phases = str((item.get("properties_json") or {}).get("phase", "A/B/C")).split("/")
        curves = []
        for phase_index, phase in enumerate(phases):
            y_offset = (phase_index - (len(phases) - 1) / 2) * 2.2
            points = []
            for step in range(65):
                t = step / 64
                x = start_x + (end_x - start_x) * t
                z = start_z + (end_z - start_z) * t - sag * 4 * t * (1 - t)
                points.append([round(x, 3), round(y_offset, 3), round(z, 3)])
            curves.append({"phase": phase.strip() or chr(65 + phase_index), "points": points})
        result.append(
            {
                "id": item["id"],
                "code": item["component_code"],
                "label": f"{item['component_code']} 设计导线",
                "design_sag": sag,
                "unit": item.get("unit") or "m",
                "start_x": start_x,
                "end_x": end_x,
                "curves": curves,
                "inferred_support": bool((start_tower and start_tower.get("inferred")) or (end_tower and end_tower.get("inferred"))),
            }
        )
    return result


def build_semantic_objects(
    data: PointCloudData | None,
    components: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if data is None:
        return []
    result = []
    for class_name in sorted(set(data.cls.tolist())):
        if class_name in {"ground", "conductor"}:
            continue
        mask = data.cls == class_name
        if not np.any(mask):
            continue
        component = component_for_class(class_name, components)
        result.append(
            {
                "id": component["id"] if component else f"pointcloud-{class_name}",
                "class": class_name,
                "label": CLASS_LABELS.get(class_name, class_name),
                "bbox": [
                    round(float(np.min(data.x[mask])), 3),
                    round(float(np.min(data.y[mask])), 3),
                    round(float(np.min(data.z[mask])), 3),
                    round(float(np.max(data.x[mask])), 3),
                    round(float(np.max(data.y[mask])), 3),
                    round(float(np.max(data.z[mask])), 3),
                ],
                "point_count": int(np.sum(mask)),
            }
        )
    return result


def component_for_class(class_name: str, components: list[dict[str, Any]]) -> dict[str, Any] | None:
    type_fragments = {
        "tower": "杆塔",
        "foundation": "基础",
        "crossing": "交跨",
        "vegetation": "通道",
    }
    fragment = type_fragments.get(class_name)
    if not fragment:
        return None
    return next((item for item in components if fragment in item["component_type"]), None)


def point_rows(data: PointCloudData | None, profile: bool = False) -> list[list[Any]]:
    if data is None:
        return []
    if profile:
        return [
            [round(float(x), 3), round(float(z), 3), str(cls), round(float(intensity), 3)]
            for x, z, cls, intensity in zip(data.x, data.z, data.cls, data.intensity)
        ]
    return [
        [round(float(x), 3), round(float(y), 3), round(float(z), 3), str(cls), round(float(intensity), 3)]
        for x, y, z, cls, intensity in zip(data.x, data.y, data.z, data.cls, data.intensity)
    ]


def point_positions(data: PointCloudData | None) -> list[list[float]]:
    if data is None:
        return []
    return [[round(float(x), 3), round(float(y), 3), round(float(z), 3)] for x, y, z in zip(data.x, data.y, data.z)]


def rounded_list(values: np.ndarray) -> list[float]:
    return [round(float(value), 3) for value in values]


def bbox_center(bbox: list[Any]) -> tuple[float, float]:
    if len(bbox) < 4:
        return 0.0, 0.0
    return round((float(bbox[0]) + float(bbox[2])) / 2, 3), round((float(bbox[1]) + float(bbox[3])) / 2, 3)


def normalize_bbox3d(bbox: list[Any]) -> list[float]:
    if len(bbox) >= 6:
        return [round(float(value), 3) for value in bbox[:6]]
    if len(bbox) >= 4:
        return [float(bbox[0]), float(bbox[1]), 0.0, float(bbox[2]), float(bbox[3]), 1.0]
    return [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]


def component_height(component: dict[str, Any], data: PointCloudData | None) -> float:
    properties = component.get("properties_json") or {}
    if properties.get("tower_height"):
        return float(properties["tower_height"])
    if "杆塔" in component["component_type"] and data is not None and np.any(data.cls == "tower"):
        values = data.z[data.cls == "tower"]
        return max(round(float(np.ptp(values)), 3), 8.0)
    return 1.2


def terrain_height(data: PointCloudData | None, x: float) -> float:
    if data is None or not np.any(data.cls == "ground"):
        return 0.0
    mask = (data.cls == "ground") & (np.abs(data.x - x) <= max(float(np.ptp(data.x)) / 40, 5.0))
    values = data.z[mask] if np.any(mask) else data.z[data.cls == "ground"]
    return round(float(np.median(values)), 3)


def conductor_endpoint_height(data: PointCloudData | None, x: float) -> float:
    if data is None or not np.any(data.cls == "conductor"):
        return 35.0
    mask = (data.cls == "conductor") & (np.abs(data.x - x) <= max(float(np.ptp(data.x)) / 40, 5.0))
    values = data.z[mask] if np.any(mask) else data.z[data.cls == "conductor"]
    return round(float(np.max(values)), 3)


def nearest_tower(towers: list[dict[str, Any]], x: float) -> dict[str, Any] | None:
    return min(towers, key=lambda item: abs(item["x"] - x)) if towers else None


def default_check_position(check_item: str) -> float:
    return {
        "foundation_span": 0.0,
        "tower_inclination": 0.0,
        "conductor_sag": 205.0,
        "crossing_clearance": 145.0,
        "channel_distance": 205.0,
    }.get(check_item, 0.0)


def profile_z_at(
    check_item: str,
    x: float,
    terrain: list[dict[str, float]],
    conductor: list[dict[str, float]],
    towers: list[dict[str, Any]],
    objects: list[dict[str, Any]],
) -> float:
    if check_item in {"conductor_sag", "crossing_clearance", "channel_distance"} and conductor:
        return min(conductor, key=lambda item: abs(item["x"] - x))["z"]
    if check_item == "tower_inclination" and towers:
        tower = min(towers, key=lambda item: abs(item["x"] - x))
        return tower["base_z"] + tower["height"] * 0.65
    if check_item == "foundation_span" and towers:
        tower = min(towers, key=lambda item: abs(item["x"] - x))
        return tower["base_z"] + 1.0
    if terrain:
        return min(terrain, key=lambda item: abs(item["x"] - x))["z"]
    for item in objects:
        if item["bbox"][0] <= x <= item["bbox"][3]:
            return float(item["bbox"][5])
    return 0.0


def check_item_for_source(source_id: str, checks: list[dict[str, Any]]) -> str:
    return next((item["check_item"] for item in checks if item["id"] == source_id), "")


def profile_bounds(
    components: list[dict[str, Any]],
    data: PointCloudData | None,
    towers: list[dict[str, Any]],
    conductors: list[dict[str, Any]],
) -> list[float]:
    xs: list[float] = []
    zs: list[float] = []
    if data is not None:
        xs.extend([float(np.min(data.x)), float(np.max(data.x))])
        zs.extend([float(np.min(data.z)), float(np.max(data.z))])
    for component in components:
        bbox = component.get("bbox_json") or []
        if len(bbox) >= 4:
            xs.extend([float(bbox[0]), float(bbox[2])])
    for tower in towers:
        xs.append(float(tower["x"]))
        zs.extend([float(tower["base_z"]), float(tower["base_z"] + tower["height"])])
    for conductor in conductors:
        for curve in conductor["curves"]:
            xs.extend([curve["points"][0][0], curve["points"][-1][0]])
            zs.extend(point[2] for point in curve["points"])
    if not xs:
        return [0.0, 0.0, 100.0, 50.0]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = (min(zs), max(zs)) if zs else (0.0, 50.0)
    x_pad = max((max_x - min_x) * 0.035, 8.0)
    z_pad = max((max_z - min_z) * 0.1, 4.0)
    return [round(min_x - x_pad, 3), round(min_z - z_pad, 3), round(max_x + x_pad, 3), round(max_z + z_pad, 3)]


def bounds3d(data: PointCloudData | None, components: list[dict[str, Any]]) -> list[float]:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    if data is not None:
        xs.extend([float(np.min(data.x)), float(np.max(data.x))])
        ys.extend([float(np.min(data.y)), float(np.max(data.y))])
        zs.extend([float(np.min(data.z)), float(np.max(data.z))])
    for item in components:
        bbox = item["bbox3d"]
        xs.extend([bbox[0], bbox[3]])
        ys.extend([bbox[1], bbox[4]])
        zs.extend([bbox[2], bbox[5]])
    if not xs:
        return [0, 0, 0, 100, 50, 50]
    return [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3), round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)]


def scene_bounds(components: list[dict[str, Any]], slices: list[dict[str, Any]], markers: list[dict[str, Any]]) -> list[float]:
    xs: list[float] = []
    ys: list[float] = []
    for component in components:
        bbox = component.get("bbox_json") or []
        if len(bbox) >= 4:
            xs.extend([float(bbox[0]), float(bbox[2])])
            ys.extend([float(bbox[1]), float(bbox[3])])
    for item in slices:
        bbox = item.get("bounds_json") or []
        if len(bbox) >= 5:
            xs.extend([float(bbox[0]), float(bbox[3])])
            ys.extend([float(bbox[1]), float(bbox[4])])
    for marker in markers:
        xs.append(float(marker["x"]))
        ys.append(float(marker["y"]))
    if not xs or not ys:
        return [-20.0, -20.0, 430.0, 80.0]
    return [min(xs) - 16.0, min(ys) - 16.0, max(xs) + 16.0, max(ys) + 16.0]
