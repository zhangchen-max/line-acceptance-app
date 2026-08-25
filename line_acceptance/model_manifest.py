from __future__ import annotations

MODEL_ID = "IDEA-Research/grounding-dino-tiny"
MODEL_REVISION = "master"
MODEL_DISPLAY_NAME = "Grounding DINO Tiny"
MODEL_LICENSE = "Apache-2.0"
MODEL_SOURCE_URL = f"https://modelscope.cn/models/{MODEL_ID}"
MODEL_DOWNLOAD_BASE = f"{MODEL_SOURCE_URL}/resolve/{MODEL_REVISION}"

# Only the Transformers/Safetensors runtime files are downloaded. The repository
# also contains a duplicate pytorch_model.bin that is intentionally excluded.
MODEL_FILES: dict[str, dict[str, int | str]] = {
    "added_tokens.json": {
        "size": 82,
        "sha256": "909e96cb32d92ce728a01bc99850cbba26196d74115c17ebeb019275412588f2",
    },
    "config.json": {
        "size": 1644,
        "sha256": "eec82c5ab66e16df12a9a212e68ac011779927c2536cf9078658e35d85f0c67a",
    },
    "configuration.json": {
        "size": 84,
        "sha256": "d3b04763a1487762bde9a2ce85f47cfdc161a8a793f33b53aa996df6514646ec",
    },
    "model.safetensors": {
        "size": 689359096,
        "sha256": "1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3",
    },
    "preprocessor_config.json": {
        "size": 457,
        "sha256": "8454179ba95e2ad22947835aad7b45862a601fc0055ab88bf1ee70892d3aea60",
    },
    "special_tokens_map.json": {
        "size": 125,
        "sha256": "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3",
    },
    "tokenizer.json": {
        "size": 711396,
        "sha256": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
    },
    "tokenizer_config.json": {
        "size": 1237,
        "sha256": "d40ab645b68211910b9170d22433d43186a6ec8ee6fd10ba170524b25bf4fb56",
    },
    "vocab.txt": {
        "size": 231508,
        "sha256": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
    },
}

MODEL_TOTAL_BYTES = sum(int(item["size"]) for item in MODEL_FILES.values())
