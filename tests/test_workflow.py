from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from line_acceptance.app_context import create_context
from line_acceptance.config import load_config
from line_acceptance.seed import seed_demo
from line_acceptance.services.fusion_service import MAX_SCENE_POINTS, sample_pointcloud
from line_acceptance.services.pointcloud_service import PointCloudData
from line_acceptance.web import create_app


class WorkflowTest(unittest.TestCase):
    def test_web_app_starts_without_demo_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            (config.root_dir / "static").mkdir(parents=True, exist_ok=True)
            (config.root_dir / "sample_data").mkdir(parents=True, exist_ok=True)
            context = create_context(config)
            create_app(context)
            self.assertEqual(context.tasks.list_tasks(), [])

    def test_demo_workflow_generates_formal_module_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            context = create_context(config)
            task = seed_demo(context, reset=True)

            self.assertEqual(task["status"], "待复核")
            self.assertGreaterEqual(len(task["models"]), 1)
            self.assertGreaterEqual(len(task["pointclouds"]), 1)
            self.assertGreaterEqual(len(task["pointcloud_slices"]), 4)
            self.assertGreaterEqual(len(task["pointcloud_objects"]), 5)
            self.assertEqual(len(task["measurements"]), 5)
            self.assertEqual(len(task["geometry_results"]), 5)
            self.assertGreaterEqual(len(task["heatmap_markers"]), 5)
            self.assertGreaterEqual(len(task["vision_results"]), 1)
            self.assertGreaterEqual(len(task["issues"]), 1)
            self.assertGreaterEqual(len(task["reports"]), 1)

            check = task["geometry_results"][0]
            self.assertIn("measurement_id", check["evidence_json"])
            self.assertNotEqual(check["evidence_json"]["measurement_method"], "规则默认值")

            vision = task["vision_results"][0]
            self.assertTrue(vision["snapshot_path"].startswith("/evidence/"))
            snapshot_path = config.evidence_dir / vision["snapshot_path"].removeprefix("/evidence/")
            self.assertTrue(snapshot_path.exists())

            scene = context.fusion.build_scene(task["id"])
            self.assertGreaterEqual(scene["statistics"]["slice_count"], 4)
            self.assertGreaterEqual(scene["statistics"]["heatmap_count"], 5)
            self.assertIn("model", scene["layers"])
            self.assertIn("pointcloud", scene["layers"])
            self.assertEqual(scene["schema_version"], "2.0")
            self.assertGreaterEqual(len(scene["profile"]["terrain"]), 2)
            self.assertEqual(len(scene["profile"]["dimensions"]), 5)
            self.assertGreaterEqual(len(scene["scene3d"]["components"]), 5)
            self.assertGreaterEqual(len(scene["scene3d"]["pointcloud"]["positions"]), 100)
            self.assertTrue(scene["coordinate_info"]["contains_inferred_geometry"])
            self.assertIn(task["issues"][0]["id"], scene["selection_index"])

            report_path = Path(task["reports"][0]["file_path"])
            self.assertTrue(report_path.exists())
            self.assertGreater(report_path.stat().st_size, 1000)

    def test_fusion_scene_keeps_unpositioned_image_out_of_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = create_context(load_config(Path(tmp)))
            task = context.tasks.create_task(
                {
                    "project_name": "空白线路验收",
                    "line_name": "测试线路",
                    "section_name": "第一标段",
                    "batch_no": "B001",
                    "owner": "测试人员",
                }
            )
            context.assets.import_images(
                task["id"],
                {
                    "images": [
                        {
                            "file_name": "未定位照片.jpg",
                            "file_path": "sample_data/images/现场照片.jpg",
                            "shoot_position": "现场未知位置",
                        }
                    ]
                },
            )
            scene = context.fusion.build_scene(task["id"])
            self.assertEqual(scene["layers"]["images"], [])
            self.assertEqual(len(scene["profile"]["unlocated_images"]), 1)
            self.assertIsNone(scene["profile"]["unlocated_images"][0]["x"])
            warning_codes = {item["code"] for item in scene["warnings"]}
            self.assertTrue({"missing_model", "missing_pointcloud", "missing_checks", "unlocated_images"}.issubset(warning_codes))

    def test_pointcloud_scene_sampling_is_bounded_and_deterministic(self) -> None:
        count = MAX_SCENE_POINTS + 3200
        indexes = np.arange(count, dtype=float)
        data = PointCloudData(
            x=indexes % 800,
            y=(indexes * 7) % 120,
            z=(indexes * 0.13) % 55,
            cls=np.array(["ground", "tower", "conductor", "vegetation"] * (count // 4) + ["ground"] * (count % 4), dtype=object),
            intensity=np.full(count, 0.75, dtype=float),
        )
        first = sample_pointcloud(data, MAX_SCENE_POINTS)
        second = sample_pointcloud(data, MAX_SCENE_POINTS)
        self.assertEqual(first.count, MAX_SCENE_POINTS)
        np.testing.assert_array_equal(first.x, second.x)
        self.assertEqual(set(first.cls.tolist()), {"ground", "tower", "conductor", "vegetation"})

    def test_manual_review_blocks_duplicate_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            context = create_context(config)
            task = seed_demo(context, reset=True)
            pending = next(item for item in context.issues.list_issues(task_id=task["id"]) if item["review_status"] == "待复核")
            context.issues.review_issue(pending["id"], {"action": "确认", "opinion": "确认纳入整改"})
            with self.assertRaises(ValueError):
                context.issues.review_issue(pending["id"], {"action": "确认"})

    def test_upload_photo_runs_acceptance_diagnosis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            context = create_context(config)
            task = seed_demo(context, reset=True)
            image = Image.new("RGB", (320, 180), (222, 232, 238))
            draw = ImageDraw.Draw(image)
            for x in range(12, 310, 18):
                draw.line((x, 18, x, 162), fill=(90, 105, 116), width=2)
            draw.line((20, 90, 300, 90), fill=(52, 60, 66), width=6)
            buffer = BytesIO()
            image.save(buffer, format="PNG")

            result = context.vision.analyze_uploaded_photo(
                task["id"],
                "现场验收照片.png",
                buffer.getvalue(),
                shoot_position="T002 杆塔大号侧",
                operator="验收工程师",
            )

            self.assertEqual(result["image"]["file_name"], "现场验收照片.png")
            self.assertEqual(result["acceptance"]["conclusion"], "资料不足")
            self.assertEqual(result["inference_run"]["status"], "模型未就绪")
            self.assertFalse(result["model_status"]["runtime_ready"])
            self.assertTrue((config.root_dir / result["image"]["file_path"]).exists())
            refreshed = context.tasks.get_task(task["id"])
            self.assertGreaterEqual(len(refreshed["images"]), 3)

    def test_detector_output_is_combined_with_rules_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp))
            context = create_context(config)
            task = seed_demo(context, reset=True)
            fake_model = FakeAIModel()
            context.ai_models = fake_model
            context.vision.ai_models = fake_model

            image = Image.new("RGB", (640, 360), (218, 229, 236))
            draw = ImageDraw.Draw(image)
            draw.rectangle((190, 100, 470, 280), fill=(96, 101, 102), outline=(35, 39, 42), width=8)
            draw.rectangle((255, 145, 390, 240), fill=(155, 69, 35))
            for x in range(200, 470, 28):
                draw.line((x, 105, x, 275), fill=(220, 225, 226), width=3)
            buffer = BytesIO()
            image.save(buffer, format="PNG")

            result = context.vision.analyze_uploaded_photo(
                task["id"],
                "T002_连接金具现场照片.png",
                buffer.getvalue(),
                shoot_position="T002 横担连接部位",
            )

            self.assertEqual(result["inference_run"]["model_id"], "test-grounding-detector")
            self.assertEqual(result["inference_run"]["status"], "成功")
            self.assertGreaterEqual(len(result["detections"]), 1)
            self.assertGreaterEqual(len(result["results"]), 1)
            self.assertIn(result["acceptance"]["conclusion"], {"需人工复核", "AI初判不符合"})
            first = result["results"][0]
            self.assertTrue(first["rule_id"].startswith("vision."))
            self.assertGreater(first["model_score"], 0)
            self.assertGreater(first["rule_score"], 0)
            self.assertTrue(first["snapshot_path"].startswith("/evidence/"))

    def test_rule_update_is_applied_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = create_context(load_config(Path(tmp)))
            before = context.rule_service.get_rule("vision.rust")
            updated = context.rule_service.update_rule(
                "vision.rust",
                {"parameters": {"min_rust_ratio": 0.08}, "severity": "严重"},
            )
            self.assertEqual(updated["parameters_json"]["min_rust_ratio"], 0.08)
            self.assertEqual(updated["severity"], "严重")
            self.assertEqual(updated["version"], before["version"] + 1)


class FakeAIModel:
    def status(self, persist: bool = True):
        return {
            "model_id": "test-grounding-detector",
            "display_name": "Test Grounding Detector",
            "revision": "test-1",
            "license": "test-only",
            "source_url": "",
            "local_path": "",
            "expected_bytes": 0,
            "installed": True,
            "runtime_ready": True,
            "loaded": True,
            "device": "cpu",
            "precision": "fp32",
            "missing_files": [],
            "invalid_files": [],
            "dependencies": {},
            "message": "测试检测器已就绪",
        }

    def detect(self, image, prompts, box_threshold=0.3, text_threshold=0.25):
        return {
            "detections": [
                {
                    "prompt_id": "fitting",
                    "target_type": "连接金具",
                    "model_label": "power line fitting",
                    "model_score": 0.92,
                    "bbox": [0.28, 0.24, 0.46, 0.54],
                }
            ],
            "duration_ms": 32,
            "model_id": "test-grounding-detector",
            "model_revision": "test-1",
            "device": "cpu",
            "precision": "fp32",
            "prompt_text": "power line fitting.",
        }


if __name__ == "__main__":
    unittest.main()
