from __future__ import annotations

import importlib.util
import os
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from PIL import Image

from ..database import json_text
from ..ids import now_text
from ..model_manifest import (
    MODEL_DISPLAY_NAME,
    MODEL_FILES,
    MODEL_ID,
    MODEL_LICENSE,
    MODEL_REVISION,
    MODEL_SOURCE_URL,
    MODEL_TOTAL_BYTES,
)


class ModelUnavailableError(RuntimeError):
    pass


class AIModelService:
    def __init__(self, db, model_dir: Path):
        self.db = db
        self.model_dir = model_dir
        self._processor = None
        self._model = None
        self._torch = None
        self._device = "未检测"
        self._precision = "fp32"
        self._lock = threading.RLock()

    def status(self, persist: bool = True) -> dict[str, Any]:
        missing: list[str] = []
        invalid: list[str] = []
        for name, expected in MODEL_FILES.items():
            path = self.model_dir / name
            if not path.is_file():
                missing.append(name)
            elif path.stat().st_size != int(expected["size"]):
                invalid.append(name)

        dependencies = {
            "torch": importlib.util.find_spec("torch") is not None,
            "transformers": importlib.util.find_spec("transformers") is not None,
            "safetensors": importlib.util.find_spec("safetensors") is not None,
        }
        installed = not missing and not invalid
        runtime_ready = installed and all(dependencies.values())
        device = self._runtime_device() if dependencies["torch"] else "未安装 PyTorch"
        if self._model is not None:
            device = self._device

        if missing:
            message = "模型权重未安装，请执行 python scripts/install_ai_model.py"
        elif invalid:
            message = "模型文件大小校验失败，请使用 --force 重新安装"
        elif not all(dependencies.values()):
            message = "AI运行依赖未安装，请执行 pip install -r requirements-ai.txt"
        elif self._model is None:
            message = "模型已就绪，将在首次影像诊断时加载"
        else:
            message = f"模型已加载，当前使用 {self._device} / {self._precision}"

        result = {
            "model_id": MODEL_ID,
            "display_name": MODEL_DISPLAY_NAME,
            "revision": MODEL_REVISION,
            "license": MODEL_LICENSE,
            "source_url": MODEL_SOURCE_URL,
            "local_path": str(self.model_dir),
            "expected_bytes": MODEL_TOTAL_BYTES,
            "installed": installed,
            "runtime_ready": runtime_ready,
            "loaded": self._model is not None,
            "device": device,
            "precision": self._precision,
            "missing_files": missing,
            "invalid_files": invalid,
            "dependencies": dependencies,
            "message": message,
        }
        if persist:
            self._persist_status(result)
        return result

    def detect(
        self,
        image: Image.Image,
        prompts: list[dict[str, str]],
        box_threshold: float = 0.30,
        text_threshold: float = 0.25,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            started = time.perf_counter()
            inference_image = image.convert("RGB")
            if max(inference_image.size) > 1600:
                inference_image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            prompt_text = " ".join(f"{item['prompt'].strip().lower().rstrip('.')}." for item in prompts)
            inputs = self._processor(images=inference_image, text=prompt_text, return_tensors="pt")
            inputs = inputs.to(self._device)
            autocast = (
                self._torch.autocast(device_type="cuda", dtype=self._torch.float16)
                if self._device == "cuda" and self._precision == "fp16"
                else nullcontext()
            )
            try:
                with self._torch.inference_mode(), autocast:
                    outputs = self._model(**inputs)
                try:
                    processed = self._processor.post_process_grounded_object_detection(
                        outputs,
                        inputs.input_ids,
                        threshold=float(box_threshold),
                        text_threshold=float(text_threshold),
                        target_sizes=[inference_image.size[::-1]],
                    )[0]
                except TypeError:
                    processed = self._processor.post_process_grounded_object_detection(
                        outputs,
                        inputs.input_ids,
                        box_threshold=float(box_threshold),
                        text_threshold=float(text_threshold),
                        target_sizes=[inference_image.size[::-1]],
                    )[0]
            except RuntimeError as exc:
                if "out of memory" in str(exc).lower() and self._device == "cuda":
                    self._torch.cuda.empty_cache()
                    raise ModelUnavailableError("GPU显存不足，请降低图片分辨率或设置 LINE_ACCEPT_AI_DEVICE=cpu") from exc
                raise

            labels = processed.get("text_labels", processed.get("labels", []))
            scores = processed.get("scores", [])
            boxes = processed.get("boxes", [])
            width, height = inference_image.size
            detections: list[dict[str, Any]] = []
            for label, score, box in zip(labels, scores, boxes):
                raw_label = str(label).strip().lower().rstrip(".")
                prompt = match_prompt(raw_label, prompts)
                values = box.detach().cpu().tolist() if hasattr(box, "detach") else list(box)
                x1, y1, x2, y2 = [float(value) for value in values]
                detections.append(
                    {
                        "prompt_id": prompt.get("id", "unknown"),
                        "target_type": prompt.get("target_type", raw_label or "未知目标"),
                        "model_label": raw_label,
                        "model_score": round(float(score), 4),
                        "bbox": [
                            round(max(0.0, x1 / width), 5),
                            round(max(0.0, y1 / height), 5),
                            round(max(0.0, (x2 - x1) / width), 5),
                            round(max(0.0, (y2 - y1) / height), 5),
                        ],
                    }
                )
            detections = non_maximum_suppression(detections, iou_threshold=0.55)
            return {
                "detections": detections,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "model_id": MODEL_ID,
                "model_revision": MODEL_REVISION,
                "device": self._device,
                "precision": self._precision,
                "prompt_text": prompt_text,
            }

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        model_status = self.status(persist=False)
        if not model_status["installed"]:
            raise ModelUnavailableError(model_status["message"])
        if not model_status["runtime_ready"]:
            raise ModelUnavailableError(model_status["message"])

        os.environ.setdefault("USE_TF", "0")
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        self._torch = torch
        self._device = self._runtime_device(torch)
        requested_precision = os.environ.get("LINE_ACCEPT_AI_PRECISION", "auto").lower()
        self._precision = "fp16" if self._device == "cuda" and requested_precision != "fp32" else "fp32"
        self._processor = AutoProcessor.from_pretrained(str(self.model_dir), local_files_only=True)
        dtype = torch.float16 if self._precision == "fp16" else torch.float32
        try:
            self._model = AutoModelForZeroShotObjectDetection.from_pretrained(
                str(self.model_dir),
                local_files_only=True,
                dtype=dtype,
            ).to(self._device)
        except TypeError:
            self._model = AutoModelForZeroShotObjectDetection.from_pretrained(
                str(self.model_dir),
                local_files_only=True,
                torch_dtype=dtype,
            ).to(self._device)
        self._model.eval()

    def _runtime_device(self, torch_module=None) -> str:
        requested = os.environ.get("LINE_ACCEPT_AI_DEVICE", "auto").lower()
        if requested == "cpu":
            return "cpu"
        try:
            torch_module = torch_module or __import__("torch")
            if torch_module.cuda.is_available():
                return "cuda"
        except Exception:
            return "cpu"
        return "cpu"

    def _persist_status(self, status: dict[str, Any]) -> None:
        self.db.execute(
            """
            INSERT INTO ai_model_registry
            (id, display_name, revision, local_path, license, source_url,
             install_status, device, detail_json, last_checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                display_name = excluded.display_name,
                revision = excluded.revision,
                local_path = excluded.local_path,
                license = excluded.license,
                source_url = excluded.source_url,
                install_status = excluded.install_status,
                device = excluded.device,
                detail_json = excluded.detail_json,
                last_checked_at = excluded.last_checked_at
            """,
            (
                MODEL_ID,
                MODEL_DISPLAY_NAME,
                MODEL_REVISION,
                str(self.model_dir),
                MODEL_LICENSE,
                MODEL_SOURCE_URL,
                "已就绪" if status["runtime_ready"] else "未就绪",
                status["device"],
                json_text(status),
                now_text(),
            ),
        )


def match_prompt(label: str, prompts: list[dict[str, str]]) -> dict[str, str]:
    for prompt in prompts:
        candidate = prompt["prompt"].strip().lower().rstrip(".")
        if label == candidate or label in candidate or candidate in label:
            return prompt
    return {"id": "unknown", "target_type": label or "未知目标", "prompt": label}


def non_maximum_suppression(items: list[dict[str, Any]], iou_threshold: float) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda value: value["model_score"], reverse=True):
        if any(
            item["prompt_id"] == kept["prompt_id"] and bbox_iou(item["bbox"], kept["bbox"]) >= iou_threshold
            for kept in selected
        ):
            continue
        selected.append(item)
    return selected


def bbox_iou(first: list[float], second: list[float]) -> float:
    ax1, ay1, aw, ah = first
    bx1, by1, bw, bh = second
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0
