from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from line_acceptance.model_manifest import (  # noqa: E402
    MODEL_DISPLAY_NAME,
    MODEL_DOWNLOAD_BASE,
    MODEL_FILES,
    MODEL_ID,
    MODEL_LICENSE,
    MODEL_REVISION,
    MODEL_SOURCE_URL,
    MODEL_TOTAL_BYTES,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_file(path: Path, expected: dict[str, int | str]) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == int(expected["size"])
        and sha256_file(path) == str(expected["sha256"])
    )


def human_size(value: int) -> str:
    return f"{value / 1024 / 1024:.1f} MB"


def download_file(name: str, target: Path, expected: dict[str, int | str], force: bool) -> None:
    if target.exists() and not force and valid_file(target, expected):
        print(f"[跳过] {name} 已通过校验")
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    if force and partial.exists():
        partial.unlink()

    url = f"{MODEL_DOWNLOAD_BASE}/{name}"
    expected_size = int(expected["size"])
    downloaded = partial.stat().st_size if partial.exists() else 0
    if downloaded > expected_size:
        partial.unlink()
        downloaded = 0
    headers = {"User-Agent": "LineAcceptance/1.0"}
    if downloaded:
        headers["Range"] = f"bytes={downloaded}-"
        print(f"[续传] {name}，已完成 {human_size(downloaded)}")
    request = urllib.request.Request(url, headers=headers)
    last_report = time.monotonic()
    print(f"[下载] {name} ({human_size(expected_size)})")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            append = downloaded > 0 and getattr(response, "status", 200) == 206
            if downloaded and not append:
                downloaded = 0
            with partial.open("ab" if append else "wb") as output:
                while True:
                    block = response.read(4 * 1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    downloaded += len(block)
                    if time.monotonic() - last_report >= 2:
                        percent = downloaded * 100 / expected_size if expected_size else 0
                        print(f"        {human_size(downloaded)} / {human_size(expected_size)} ({percent:.1f}%)")
                        last_report = time.monotonic()
        os.replace(partial, target)
    except Exception:
        print(f"[中断] 已保留 {human_size(partial.stat().st_size) if partial.exists() else '0 MB'}，再次执行将续传")
        raise

    if not valid_file(target, expected):
        target.unlink(missing_ok=True)
        raise RuntimeError(f"{name} 下载完成但大小或 SHA-256 校验失败")
    print(f"[完成] {name}")


def write_install_manifest(model_dir: Path) -> None:
    payload = {
        "model_id": MODEL_ID,
        "display_name": MODEL_DISPLAY_NAME,
        "revision": MODEL_REVISION,
        "license": MODEL_LICENSE,
        "source_url": MODEL_SOURCE_URL,
        "files": MODEL_FILES,
        "total_bytes": MODEL_TOTAL_BYTES,
    }
    (model_dir / "install_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="从 ModelScope 安装线路验收影像诊断模型")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=PROJECT_ROOT / "storage" / "models" / "grounding-dino-tiny",
        help="模型保存目录",
    )
    parser.add_argument("--force", action="store_true", help="重新下载并覆盖已有文件")
    parser.add_argument("--check-only", action="store_true", help="只校验本地文件，不执行下载")
    args = parser.parse_args()
    model_dir = args.model_dir.resolve()

    print(f"模型：{MODEL_DISPLAY_NAME} ({MODEL_ID})")
    print(f"来源：{MODEL_SOURCE_URL}")
    print(f"许可：{MODEL_LICENSE}")
    print(f"目录：{model_dir}")
    print(f"总计：{human_size(MODEL_TOTAL_BYTES)}")

    if args.check_only:
        invalid = [name for name, expected in MODEL_FILES.items() if not valid_file(model_dir / name, expected)]
        if invalid:
            print("校验失败，缺失或损坏：" + "、".join(invalid))
            return 1
        print("模型文件完整，校验通过。")
        return 0

    for name, expected in MODEL_FILES.items():
        download_file(name, model_dir / name, expected, args.force)
    write_install_manifest(model_dir)
    print("模型安装完成。可启动软件并在影像验收页查看模型状态。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
