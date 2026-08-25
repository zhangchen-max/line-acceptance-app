from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..database import json_text
from ..ids import new_id, now_text
from ..rules import RuleBook
from .ai_model_service import AIModelService, ModelUnavailableError
from .common import ServiceBase
from .rule_service import RuleService


class VisionService(ServiceBase):
    def __init__(
        self,
        db,
        rules: RuleBook,
        rule_service: RuleService,
        ai_models: AIModelService,
        root_dir: Path,
        evidence_dir: Path,
        storage_dir: Path,
    ):
        super().__init__(db, root_dir)
        self.rules = rules
        self.rule_service = rule_service
        self.ai_models = ai_models
        self.evidence_dir = evidence_dir
        self.storage_dir = storage_dir

    def analyze_uploaded_photo(
        self,
        task_id: str,
        file_name: str,
        content: bytes,
        shoot_position: str = "现场照片",
        source_type: str = "照片",
        operator: str = "验收工程师",
    ) -> dict[str, Any]:
        task = self.require_task(task_id)
        if not content:
            raise ValueError("上传照片为空")
        pil_image = open_image_bytes(content)
        features = image_features(pil_image)
        image_id = new_id("IMG")
        saved_path = self._save_uploaded_image(task, image_id, file_name, pil_image)
        self.db.execute(
            """
            INSERT INTO image_asset
            (id, task_id, file_name, file_path, source_type, frame_time, shoot_position,
             clarity_score, quality_json, process_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                image_id,
                task_id,
                file_name or saved_path.name,
                self.relative_path(saved_path),
                source_type,
                "",
                shoot_position or "现场照片",
                features["clarity"],
                json_text(features),
                "待诊断",
                now_text(),
            ),
        )
        image = self.db.one("SELECT * FROM image_asset WHERE id = ?", (image_id,))
        analysis = self._analyze_image_record(task_id, image, pil_image=pil_image, features=features)
        acceptance = photo_acceptance(
            analysis["results"],
            features,
            analysis["run"],
            len(analysis["detections"]),
        )
        self._record_run(
            task_id,
            "现场照片AI验收",
            analysis["run"]["status"],
            {"file_name": file_name, "shoot_position": shoot_position},
            {
                "result_count": len(analysis["results"]),
                "detection_count": len(analysis["detections"]),
                "conclusion": acceptance["conclusion"],
                "model_id": analysis["run"]["model_id"],
            },
        )
        self.log(operator, "上传现场照片并执行AI验收", "image_asset", image_id, acceptance["conclusion"], acceptance)
        return {
            "image": self.db.one("SELECT * FROM image_asset WHERE id = ?", (image_id,)),
            "results": analysis["results"],
            "detections": analysis["detections"],
            "features": features,
            "inference_run": analysis["run"],
            "acceptance": acceptance,
            "model_status": self.ai_models.status(),
        }

    def analyze_task_images(
        self,
        task_id: str,
        payload: dict[str, Any] | None = None,
        operator: str = "验收工程师",
        demo: bool = False,
    ) -> list[dict[str, Any]]:
        payload = payload or {}
        self.require_task(task_id)
        images = self.db.all("SELECT * FROM image_asset WHERE task_id = ? ORDER BY created_at", (task_id,))
        requested_ids = set(payload.get("image_ids") or [])
        if requested_ids:
            images = [image for image in images if image["id"] in requested_ids]
        if not images:
            raise ValueError("请先导入或上传影像资料")

        results: list[dict[str, Any]] = []
        successful = 0
        for image in images:
            analysis = self._analyze_image_record(task_id, image, demo=demo)
            results.extend(analysis["results"])
            successful += int(analysis["run"]["status"] in {"成功", "质量不满足"})
        self._record_run(
            task_id,
            "影像资料AI缺陷诊断",
            "成功" if successful else "未完成",
            {"image_count": len(images), "demo": demo},
            {"defect_count": len(results), "successful_images": successful},
        )
        self.log(operator, "执行影像AI诊断", "vision_defect_result", task_id, "成功", {"count": len(results)})
        return results

    def results(self, task_id: str) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM vision_defect_result WHERE task_id = ? ORDER BY created_at DESC", (task_id,))

    def inference_runs(self, task_id: str) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM vision_inference_run WHERE task_id = ? ORDER BY created_at DESC", (task_id,))

    def task_acceptance(self, task_id: str) -> dict[str, Any]:
        self.require_task(task_id)
        images = self.db.all("SELECT * FROM image_asset WHERE task_id = ? ORDER BY created_at DESC", (task_id,))
        if not images:
            return acceptance_result("未验收", "无影像资料", "一般", "当前任务尚未上传现场影像。", True, False)

        runs = self.inference_runs(task_id)
        latest_by_image: dict[str, dict[str, Any]] = {}
        for run in runs:
            latest_by_image.setdefault(run["image_id"], run)
        if len(latest_by_image) < len(images):
            return acceptance_result(
                "资料不足",
                "存在未诊断影像",
                "关注",
                "当前任务仍有照片未完成AI诊断，不能形成最终验收结论。",
                True,
                False,
            )
        blocked = [run for run in latest_by_image.values() if run["status"] != "成功"]
        if blocked:
            reasons = "、".join(sorted({run["status"] for run in blocked}))
            return acceptance_result(
                "资料不足",
                reasons,
                "关注",
                "部分照片因质量、模型或运行环境问题未完成有效诊断。",
                True,
                False,
            )

        issues = self.db.all(
            "SELECT * FROM acceptance_issue WHERE task_id = ? AND source_type = 'vision' ORDER BY created_at",
            (task_id,),
        )
        pending = [issue for issue in issues if issue["review_status"] == "待复核"]
        confirmed = [issue for issue in issues if issue["review_status"] == "已确认"]
        if pending:
            names = "、".join(sorted({item["issue_type"] for item in pending}))
            return acceptance_result(
                "需人工复核",
                "AI发现缺陷候选",
                "严重" if any(item["level"] == "严重" for item in pending) else "关注",
                f"AI识别到 {names}，须由验收人员查看证据图并确认。",
                True,
                False,
            )
        if confirmed:
            names = "、".join(sorted({item["issue_type"] for item in confirmed}))
            return acceptance_result(
                "不符合验收标准",
                "缺陷已由人工确认",
                "严重" if any(item["level"] == "严重" for item in confirmed) else "关注",
                f"人工已确认 {names}，应进入整改闭环。",
                False,
                True,
                final_conclusion="不符合验收标准",
            )
        return acceptance_result(
            "AI初判符合",
            "未发现有效缺陷候选",
            "一般",
            "影像质量满足要求，AI构件检测已完成，当前缺陷候选均已排除或未达到规则阈值。",
            False,
            bool(issues),
            final_conclusion="符合影像验收标准" if issues else "",
        )

    def _analyze_image_record(
        self,
        task_id: str,
        image: dict[str, Any],
        pil_image: Image.Image | None = None,
        features: dict[str, Any] | None = None,
        demo: bool = False,
    ) -> dict[str, Any]:
        self._clear_image_results(task_id, image["id"])
        if pil_image is None:
            path = self.resolve_path(image["file_path"])
            if not path.exists():
                raise ValueError(f"影像文件不存在：{image['file_path']}")
            pil_image = Image.open(path).convert("RGB")
        features = features or image_features(pil_image)
        settings = self.rule_service.vision_settings()
        quality_rule = settings["vision.quality"]
        quality_message = quality_gate(features, quality_rule["parameters"])

        run_id = new_id("AIR")
        detections: list[dict[str, Any]] = []
        output: dict[str, Any] = {}
        run_status = "成功"
        error_message = ""
        if quality_message and not demo:
            run_status = "质量不满足"
            candidates = [quality_candidate(quality_message, quality_rule)]
            output = {
                "model_id": "image-quality-gate",
                "model_revision": "1.0",
                "device": "cpu",
                "duration_ms": 0,
                "prompt_text": "",
            }
        else:
            detector = settings["vision.detector"]["parameters"]
            try:
                output = (
                    demo_detection_output(image, pil_image)
                    if demo
                    else self.ai_models.detect(
                        pil_image,
                        detector["prompts"],
                        box_threshold=float(detector["box_threshold"]),
                        text_threshold=float(detector["text_threshold"]),
                    )
                )
                detections = output["detections"]
                candidates = diagnose_detections(pil_image, detections, features, settings)
            except ModelUnavailableError as exc:
                run_status = "模型未就绪"
                error_message = str(exc)
                candidates = []
                output = {
                    "model_id": self.ai_models.status(persist=False)["model_id"],
                    "model_revision": self.ai_models.status(persist=False)["revision"],
                    "device": "未加载",
                    "duration_ms": 0,
                    "prompt_text": "",
                }
            except Exception as exc:
                run_status = "推理失败"
                error_message = str(exc)
                candidates = []
                output = {
                    "model_id": self.ai_models.status(persist=False)["model_id"],
                    "model_revision": self.ai_models.status(persist=False)["revision"],
                    "device": "运行异常",
                    "duration_ms": 0,
                    "prompt_text": "",
                }

        run = self._insert_inference_run(
            run_id,
            task_id,
            image["id"],
            output,
            run_status,
            detections,
            error_message,
        )
        results: list[dict[str, Any]] = []
        for candidate in candidates:
            result = self._store_candidate(task_id, image, pil_image, features, run_id, candidate)
            results.append(result)
        process_status = {
            "成功": "已完成AI诊断" if results else "未发现缺陷候选",
            "质量不满足": "影像质量不足",
            "模型未就绪": "AI模型未就绪",
            "推理失败": "AI诊断失败",
        }[run_status]
        self.db.execute(
            "UPDATE image_asset SET process_status = ?, clarity_score = ?, quality_json = ? WHERE id = ?",
            (process_status, round(features["clarity"], 4), json_text(features), image["id"]),
        )
        return {"results": results, "detections": detections, "run": run, "features": features}

    def _store_candidate(
        self,
        task_id: str,
        image: dict[str, Any],
        pil_image: Image.Image,
        features: dict[str, Any],
        run_id: str,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        confidence = candidate_confidence(candidate, features)
        level = candidate.get("severity", "关注") if confidence >= self.rules.vision_threshold else "一般"
        status = "待复核" if confidence >= self.rules.vision_threshold else "低置信度"
        result_id = new_id("VIS")
        snapshot_url = self._write_snapshot(task_id, result_id, pil_image, candidate, confidence)
        diagnosis = {
            "feature_reason": candidate.get("feature_reason", ""),
            "metrics": candidate.get("metrics", {}),
            "standard_basis": candidate.get("standard_basis", ""),
            "rule_version": candidate.get("rule_version", 1),
        }
        self.db.execute(
            """
            INSERT INTO vision_defect_result
            (id, task_id, image_id, target_type, defect_type, bbox_json, confidence,
             level, snapshot_path, status, inference_run_id, model_label, model_score,
             rule_id, rule_score, diagnosis_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                task_id,
                image["id"],
                candidate["target_type"],
                candidate["defect_type"],
                json_text(candidate["bbox"]),
                confidence,
                level,
                snapshot_url,
                status,
                run_id,
                candidate.get("model_label", ""),
                float(candidate.get("model_score", 0)),
                candidate["rule_id"],
                float(candidate.get("rule_score", 0)),
                json_text(diagnosis),
                now_text(),
            ),
        )
        result = self.db.one("SELECT * FROM vision_defect_result WHERE id = ?", (result_id,))
        if status == "待复核":
            self._create_issue(task_id, result, image, features, candidate)
        return result

    def _insert_inference_run(
        self,
        run_id: str,
        task_id: str,
        image_id: str,
        output: dict[str, Any],
        status: str,
        detections: list[dict[str, Any]],
        error_message: str,
    ) -> dict[str, Any]:
        self.db.execute(
            """
            INSERT INTO vision_inference_run
            (id, task_id, image_id, model_id, model_revision, device, status,
             prompt_json, raw_output_json, duration_ms, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                task_id,
                image_id,
                output.get("model_id", "unknown"),
                output.get("model_revision", ""),
                output.get("device", ""),
                status,
                json_text({"text": output.get("prompt_text", "")}),
                json_text({"detections": detections, "precision": output.get("precision", "")}),
                int(output.get("duration_ms", 0)),
                error_message,
                now_text(),
            ),
        )
        return self.db.one("SELECT * FROM vision_inference_run WHERE id = ?", (run_id,))

    def _save_uploaded_image(self, task: dict[str, Any], image_id: str, file_name: str, image: Image.Image) -> Path:
        target_dir = self.storage_dir / task["task_no"] / "images"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{image_id}_{safe_name(Path(file_name or '现场照片').stem)}.png"
        image.save(target)
        return target

    def _clear_image_results(self, task_id: str, image_id: str) -> None:
        self.db.execute(
            """
            DELETE FROM acceptance_issue
            WHERE task_id = ? AND source_type = 'vision'
              AND source_id IN (SELECT id FROM vision_defect_result WHERE task_id = ? AND image_id = ?)
            """,
            (task_id, task_id, image_id),
        )
        self.db.execute("DELETE FROM vision_defect_result WHERE task_id = ? AND image_id = ?", (task_id, image_id))

    def _write_snapshot(
        self,
        task_id: str,
        result_id: str,
        image: Image.Image,
        candidate: dict[str, Any],
        confidence: float,
    ) -> str:
        target_dir = self.evidence_dir / task_id
        target_dir.mkdir(parents=True, exist_ok=True)
        output = target_dir / f"{result_id}_{safe_name(candidate['defect_type'])}.png"
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)
        width, height = annotated.size
        rect = bbox_pixels(candidate["bbox"], width, height)
        line_width = max(3, round(min(width, height) / 180))
        color = (181, 49, 47) if candidate.get("severity") == "严重" else (190, 113, 26)
        draw.rectangle(rect, outline=color, width=line_width)
        label = f"{candidate['defect_type']}  {confidence:.2f}"
        font = annotation_font(max(16, round(min(width, height) / 28)))
        text_bbox = draw.textbbox((0, 0), label, font=font)
        label_width = text_bbox[2] - text_bbox[0] + 20
        label_height = text_bbox[3] - text_bbox[1] + 14
        label_x = min(rect[0], max(0, width - label_width))
        label_y = max(0, rect[1] - label_height)
        draw.rectangle((label_x, label_y, label_x + label_width, label_y + label_height), fill=color)
        draw.text((label_x + 10, label_y + 6), label, fill=(255, 255, 255), font=font)
        annotated.save(output)
        return f"/evidence/{task_id}/{output.name}"

    def _create_issue(
        self,
        task_id: str,
        result: dict[str, Any],
        image: dict[str, Any],
        features: dict[str, Any],
        candidate: dict[str, Any],
    ) -> None:
        issue_id = new_id("ISS")
        evidence = {
            "image_id": image["id"],
            "file_name": image["file_name"],
            "bbox": result["bbox_json"],
            "confidence": result["confidence"],
            "model_score": result["model_score"],
            "rule_score": result["rule_score"],
            "rule_id": result["rule_id"],
            "shoot_position": image["shoot_position"],
            "snapshot_path": result["snapshot_path"],
            "features": features,
            "diagnosis": result["diagnosis_json"],
        }
        description = (
            f"{image['file_name']}：AI初判发现 {result['target_type']} 存在 {result['defect_type']} 候选，"
            f"综合置信度 {result['confidence']}，需人工复核。"
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
                "vision",
                result["id"],
                result["defect_type"],
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


def open_image_bytes(content: bytes) -> Image.Image:
    try:
        return Image.open(BytesIO(content)).convert("RGB")
    except Exception as exc:
        raise ValueError("上传文件不是可识别的图片") from exc


def image_features(image: Image.Image) -> dict[str, Any]:
    arr = np.asarray(image, dtype=np.float32) / 255.0
    gray = arr.mean(axis=2)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    gy, gx = np.gradient(gray)
    gradient = np.sqrt(gx * gx + gy * gy)
    edge_strength = float(gradient.mean())
    edge_density = float(np.mean(gradient > 0.08))
    clarity = min(1.0, max(0.0, 0.42 + edge_strength * 7.5 + contrast * 0.75))
    return {
        "width": image.width,
        "height": image.height,
        "brightness": round(brightness, 4),
        "contrast": round(contrast, 4),
        "edge_strength": round(edge_strength, 4),
        "edge_density": round(edge_density, 4),
        "clarity": round(clarity, 4),
    }


def quality_gate(features: dict[str, Any], parameters: dict[str, Any]) -> str:
    if features["clarity"] < float(parameters["min_clarity"]):
        return "照片清晰度不足，不能作为可靠的AI验收依据"
    if features["brightness"] < float(parameters["min_brightness"]):
        return "照片整体过暗，线路构件细节不可可靠辨认"
    if features["brightness"] > float(parameters["max_brightness"]):
        return "照片存在明显过曝，线路构件细节不可可靠辨认"
    return ""


def quality_candidate(message: str, rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_type": "现场影像",
        "defect_type": "影像质量不足",
        "bbox": [0.04, 0.05, 0.92, 0.90],
        "model_label": "image quality",
        "model_score": 1.0,
        "rule_id": rule["id"],
        "rule_score": 1.0,
        "severity": rule["severity"],
        "feature_reason": message,
        "metrics": {},
        "standard_basis": rule["standard_basis"],
        "rule_version": rule["version"],
    }


def diagnose_detections(
    image: Image.Image,
    detections: list[dict[str, Any]],
    features: dict[str, Any],
    settings: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    rust_rule = settings["vision.rust"]
    if rust_rule["enabled"]:
        for detection in detections:
            if detection["prompt_id"] not in {"fitting", "tower", "damper", "bolt"}:
                continue
            ratio = crop_rust_ratio(image, detection["bbox"])
            minimum = float(rust_rule["parameters"]["min_rust_ratio"])
            if ratio >= minimum:
                score = min(0.98, 0.55 + ratio / max(minimum, 0.001) * 0.16)
                candidates.append(
                    make_candidate(
                        detection,
                        "锈蚀",
                        rust_rule,
                        score,
                        f"AI定位的{detection['target_type']}区域内红褐色像素占比 {ratio:.3f}",
                        {"rust_ratio": round(ratio, 4), "threshold": minimum},
                    )
                )

    insulator_rule = settings["vision.insulator_damage"]
    if insulator_rule["enabled"]:
        for detection in [item for item in detections if item["prompt_id"] == "insulator"]:
            density = crop_edge_density(image, detection["bbox"])
            low = float(insulator_rule["parameters"]["min_edge_density"])
            high = float(insulator_rule["parameters"]["max_edge_density"])
            color_break = crop_red_ratio(image, detection["bbox"])
            abnormal = density < low or density > high or color_break > 0.012
            if abnormal:
                score = max(float(insulator_rule["parameters"]["candidate_score"]), min(0.92, 0.58 + color_break * 5))
                candidates.append(
                    make_candidate(
                        detection,
                        "绝缘子疑似破损",
                        insulator_rule,
                        score,
                        "绝缘子区域边缘连续性或局部颜色特征异常",
                        {"edge_density": round(density, 4), "red_break_ratio": round(color_break, 4)},
                    )
                )

    damper_rule = settings["vision.damper_position"]
    conductors = [item for item in detections if item["prompt_id"] == "conductor"]
    if damper_rule["enabled"] and conductors:
        for detection in [item for item in detections if item["prompt_id"] == "damper"]:
            distance = min(center_distance(detection["bbox"], conductor["bbox"]) for conductor in conductors)
            maximum = float(damper_rule["parameters"]["max_conductor_distance_ratio"])
            if distance > maximum:
                candidates.append(
                    make_candidate(
                        detection,
                        "防震锤位置异常",
                        damper_rule,
                        float(damper_rule["parameters"]["candidate_score"]),
                        "防震锤中心与最近导线目标的相对距离超过示例规则阈值",
                        {"relative_distance": round(distance, 4), "threshold": maximum},
                    )
                )

    bolt_rule = settings["vision.bolt_presence"]
    bolts = [item for item in detections if item["prompt_id"] == "bolt"]
    if bolt_rule["enabled"]:
        for fitting in [item for item in detections if item["prompt_id"] == "fitting"]:
            required = int(bolt_rule["parameters"]["required_count"])
            minimum_score = float(bolt_rule["parameters"]["min_bolt_score"])
            count = sum(
                1
                for bolt in bolts
                if bolt["model_score"] >= minimum_score and center_inside(bolt["bbox"], fitting["bbox"], expansion=0.35)
            )
            if count < required:
                candidates.append(
                    make_candidate(
                        fitting,
                        "螺栓疑似缺失",
                        bolt_rule,
                        float(bolt_rule["parameters"]["candidate_score"]),
                        "已定位连接金具，但其邻域内未检出满足置信度要求的预期螺栓",
                        {"detected_count": count, "required_count": required, "min_bolt_score": minimum_score},
                    )
                )
    return candidates


def make_candidate(
    detection: dict[str, Any],
    defect_type: str,
    rule: dict[str, Any],
    rule_score: float,
    reason: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "target_type": detection["target_type"],
        "defect_type": defect_type,
        "bbox": detection["bbox"],
        "model_label": detection["model_label"],
        "model_score": detection["model_score"],
        "rule_id": rule["id"],
        "rule_score": round(rule_score, 4),
        "severity": rule["severity"],
        "feature_reason": reason,
        "metrics": metrics,
        "standard_basis": rule["standard_basis"],
        "rule_version": rule["version"],
    }


def candidate_confidence(candidate: dict[str, Any], features: dict[str, Any]) -> float:
    model_score = float(candidate.get("model_score", 0.5))
    rule_score = float(candidate.get("rule_score", 0.5))
    clarity_factor = 0.78 + min(float(features.get("clarity", 0.5)), 1.0) * 0.22
    return round(min(0.98, max(0.20, (model_score * 0.48 + rule_score * 0.52) * clarity_factor)), 4)


def photo_acceptance(
    results: list[dict[str, Any]],
    features: dict[str, Any],
    run: dict[str, Any],
    detection_count: int,
) -> dict[str, Any]:
    if run["status"] == "模型未就绪":
        return acceptance_result("资料不足", "AI模型未就绪", "关注", run["error_message"], True, False)
    if run["status"] == "推理失败":
        return acceptance_result("资料不足", "AI推理失败", "关注", run["error_message"], True, False)
    if run["status"] == "质量不满足":
        reason = results[0]["diagnosis_json"].get("feature_reason", "影像质量不满足诊断要求") if results else "影像质量不满足诊断要求"
        return acceptance_result("资料不足", "影像质量不足", "关注", reason, True, False)
    if detection_count == 0:
        return acceptance_result(
            "资料不足",
            "未检出可验收线路构件",
            "关注",
            "模型已完成推理，但照片中未定位到规则库要求的线路构件，请检查拍摄距离和角度。",
            True,
            False,
        )
    severe = [item for item in results if item["status"] == "待复核" and item["level"] == "严重"]
    if severe:
        names = "、".join(sorted({item["defect_type"] for item in severe}))
        return acceptance_result(
            "AI初判不符合",
            "发现严重缺陷候选",
            "严重",
            f"AI与规则库识别到 {names}，已进入问题台账，最终结论须由验收人员确认。",
            True,
            False,
        )
    pending = [item for item in results if item["status"] == "待复核"]
    if pending:
        names = "、".join(sorted({item["defect_type"] for item in pending}))
        return acceptance_result(
            "需人工复核",
            "发现关注缺陷候选",
            "关注",
            f"AI与规则库识别到 {names}，请结合证据图确认。",
            True,
            False,
        )
    return acceptance_result(
        "AI初判符合",
        "未发现超过阈值的缺陷候选",
        "一般",
        "照片质量满足要求，模型已定位线路构件，当前缺陷特征未超过启用规则阈值。",
        False,
        False,
    )


def acceptance_result(
    conclusion: str,
    standard_status: str,
    level: str,
    basis: str,
    requires_review: bool,
    is_final: bool,
    final_conclusion: str = "",
) -> dict[str, Any]:
    return {
        "conclusion": conclusion,
        "system_conclusion": conclusion,
        "final_conclusion": final_conclusion,
        "standard_status": standard_status,
        "level": level,
        "basis": basis,
        "requires_review": requires_review,
        "is_final": is_final,
    }


def demo_detection_output(image_record: dict[str, Any], image: Image.Image) -> dict[str, Any]:
    name = image_record["file_name"]
    if "防震锤" in name:
        detections = [
            detection("damper", "防震锤", "vibration damper", 0.88, [0.45, 0.43, 0.19, 0.18]),
            detection("conductor", "导线", "power conductor wire", 0.91, [0.08, 0.40, 0.84, 0.10]),
        ]
    else:
        detections = [
            detection("insulator", "绝缘子串", "insulator string", 0.91, [0.33, 0.25, 0.30, 0.31]),
            detection("fitting", "连接金具", "power line fitting", 0.82, [0.58, 0.34, 0.16, 0.18]),
            detection("conductor", "导线", "power conductor wire", 0.87, [0.12, 0.16, 0.76, 0.10]),
        ]
    return {
        "detections": detections,
        "duration_ms": 18,
        "model_id": "demo-explicit-detector",
        "model_revision": "1.0",
        "device": "cpu",
        "precision": "fp32",
        "prompt_text": "demo fixtures only",
    }


def detection(prompt_id: str, target_type: str, label: str, score: float, bbox: list[float]) -> dict[str, Any]:
    return {
        "prompt_id": prompt_id,
        "target_type": target_type,
        "model_label": label,
        "model_score": score,
        "bbox": bbox,
    }


def crop_array(image: Image.Image, bbox: list[float]) -> np.ndarray:
    rect = bbox_pixels(bbox, image.width, image.height)
    crop = image.crop(rect).convert("RGB")
    return np.asarray(crop, dtype=np.float32) / 255.0


def crop_rust_ratio(image: Image.Image, bbox: list[float]) -> float:
    arr = crop_array(image, bbox)
    red, green, blue = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mask = (
        (red > 0.28)
        & (red < 0.86)
        & (green > 0.10)
        & (green < 0.62)
        & (red > green * 1.16)
        & (green > blue * 0.72)
    )
    return float(mask.mean())


def crop_red_ratio(image: Image.Image, bbox: list[float]) -> float:
    arr = crop_array(image, bbox)
    mask = (arr[:, :, 0] > arr[:, :, 1] + 0.18) & (arr[:, :, 0] > arr[:, :, 2] + 0.16)
    return float(mask.mean())


def crop_edge_density(image: Image.Image, bbox: list[float]) -> float:
    arr = crop_array(image, bbox)
    gray = arr.mean(axis=2)
    gy, gx = np.gradient(gray)
    return float(np.mean(np.sqrt(gx * gx + gy * gy) > 0.08))


def center_distance(first: list[float], second: list[float]) -> float:
    first_center = (first[0] + first[2] / 2, first[1] + first[3] / 2)
    second_center = (second[0] + second[2] / 2, second[1] + second[3] / 2)
    return float(np.hypot(first_center[0] - second_center[0], first_center[1] - second_center[1]))


def center_inside(candidate: list[float], container: list[float], expansion: float = 0.0) -> bool:
    cx = candidate[0] + candidate[2] / 2
    cy = candidate[1] + candidate[3] / 2
    margin_x = container[2] * expansion
    margin_y = container[3] * expansion
    return (
        container[0] - margin_x <= cx <= container[0] + container[2] + margin_x
        and container[1] - margin_y <= cy <= container[1] + container[3] + margin_y
    )


def bbox_pixels(bbox: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = bbox
    x1 = max(0, min(width - 1, int(x * width)))
    y1 = max(0, min(height - 1, int(y * height)))
    x2 = max(x1 + 1, min(width, int((x + w) * width)))
    y2 = max(y1 + 1, min(height, int((y + h) * height)))
    return x1, y1, x2, y2


def annotation_font(size: int):
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def safe_name(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"})
    return cleaned or "photo"
