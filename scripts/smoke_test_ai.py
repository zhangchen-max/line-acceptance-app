from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from line_acceptance.config import load_config  # noqa: E402
from line_acceptance.services.ai_model_service import AIModelService


def main() -> int:
    parser = argparse.ArgumentParser(description="运行本地影像模型冒烟测试")
    parser.add_argument("image", nargs="?", type=Path, help="待检测图片，默认使用 sample_data/images 下第一张图片")
    args = parser.parse_args()
    config = load_config()
    image_path = args.image or next((config.root_dir / "sample_data" / "images").glob("*.jpg"))
    prompts = [
        {"id": "insulator", "prompt": "insulator string", "target_type": "绝缘子串"},
        {"id": "fitting", "prompt": "power line fitting", "target_type": "连接金具"},
        {"id": "bolt", "prompt": "metal bolt", "target_type": "螺栓"},
        {"id": "damper", "prompt": "vibration damper", "target_type": "防震锤"},
        {"id": "conductor", "prompt": "power conductor wire", "target_type": "导线"},
    ]
    service = AIModelService(None, config.model_dir)
    status = service.status(persist=False)
    if not status["runtime_ready"]:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 1
    image = Image.open(image_path).convert("RGB")
    result = service.detect(image, prompts, box_threshold=0.22, text_threshold=0.20)
    print(
        json.dumps(
            {"image": str(image_path), "status": service.status(persist=False), "result": result},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
