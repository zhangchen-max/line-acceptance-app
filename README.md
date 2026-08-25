# 基于人工智能的线路工程验收校核软件

## 项目简介（约300字概述）

基于人工智能的线路工程验收校核软件 V1.0 是一款面向输电线路竣工验收的本地化 Web 应用，辅助验收人员完成多源数据融合、智能校核与缺陷诊断。

系统导入 GIM-like 设计模型与 CSV 点云，解析杆塔、导线、地面线及语义点云，并基于设计参数完成模型—点云偏差校核，输出偏差、阈值、等级与整改建议。点云模块可对海量数据进行分片、分类、量测与异常识别。

影像验收在本地调用 Grounding DINO Tiny 定位绝缘子、金具、螺栓、防震锤、导线、杆塔等构件，结合规则库对锈蚀、破损、缺失等缺陷作 AI 初判，生成标注证据图与"符合/需复核/不符合"结论，全程读取本地模型、不依赖远程接口。

系统提供融合总览（纵断面与三维巡视）、问题台账与 DOCX/Markdown 报告导出，形成"导入—处理—校核—诊断—归档"闭环。运行需 Python 3.9+ 与浏览器，内置示例数据。最终验收结论须由专业人员结合现场证据与正式标准复核确认；原生 GIM、LAS/LAZ 及视频处理为后续扩展。本仓库为软著对应的原创源代码（不含第三方前端库、运行数据库、示例图片与模型权重）。

本项目是面向线路工程竣工验收和软件著作权材料提交的正式本地 Web 项目。系统提供 GIM-like 设计模型导入、CSV 点云智能处理、模型点云偏差校核、现场照片 AI 初验、融合可视化、问题台账和报告导出能力。

影像诊断使用从 ModelScope 下载到本地的 Grounding DINO Tiny 权重定位线路构件，并结合可配置规则库生成缺陷候选和证据图。系统不依赖远程推理接口，但不宣称具备未经现场数据验证的工业级识别精度。原生 GIM、LAS/LAZ 仍保留扩展接口。

## 运行环境

- Python 3.9+
- Windows、macOS 或 Linux
- 推荐使用虚拟环境

安装依赖：

```bash
pip install -r requirements.txt
```

安装 AI 运行依赖并下载本地模型：

```bash
pip install -r requirements-ai.txt --index-url https://pypi.org/simple
python scripts/install_ai_model.py
python scripts/smoke_test_ai.py
```

模型文件约 658 MB，默认保存在 `storage/models/grounding-dino-tiny/`。下载脚本支持断点续传和 SHA256 校验；模型完成安装后，业务推理只读取本地文件。

默认自动选择运行设备。CPU 可直接运行；如计算机已正确安装 NVIDIA 驱动，可按实际 CUDA 版本安装对应的 PyTorch CUDA wheel，再通过 `LINE_ACCEPT_AI_DEVICE=cuda` 指定 GPU。不要在不匹配的 CUDA 环境中强行安装示例 wheel。

启动服务：

```bash
python run.py
```

浏览器访问：

```text
http://127.0.0.1:8080
```

## 主要功能

- 多维数据融合可视化：默认以工程纵断面展示线路里程、高程、杆塔、地面线、设计/实测导线、语义点云和验收尺寸，并可切换 Three.js 三维巡视视图。
- 点云智能处理与缺陷识别：解析 `x,y,z,class,intensity` CSV 点云，生成点云分片、分类对象、量测结果和异常对象。
- 模型与点云对比分析：使用点云量测值与设计模型参数进行偏差校核，输出偏差、阈值、等级、建议和热力图坐标。
- 影像资料缺陷诊断：先进行清晰度、亮度和对比度质量门禁，再调用本地 Grounding DINO 定位绝缘子、金具、螺栓、防震锤、导线和杆塔构件，最后结合锈蚀、破损、位置和缺失规则生成缺陷候选。
- 现场照片上传验收：用户可在“影像验收”页上传 PNG/JPG/JPEG/WebP 现场照片，系统自动保存原图、记录拍摄位置、运行模型和规则库、生成标注证据图，并输出“AI 初判符合、需人工复核、AI 初判不符合或资料不足”。
- 问题台账与报告归档：将需复核或超限结果写入台账，支持复核确认、整改状态更新和 DOCX/Markdown 报告导出。

## 融合总览操作

形成完整融合场景前，先在“数据资料”导入 GIM-like JSON 和 CSV 点云，在“点云处理”完成解析与量测，再在“模型与点云对比”执行配准及偏差校核。现场照片可在“影像验收”上传并生成诊断证据。

进入“融合总览”后，系统默认打开工程纵断面。可在顶部切换“三维巡视”，使用俯视、侧视、适应场景和复位视角；点击问题标记、杆塔或导线可联动右侧对象详情，图层页签可控制设计模型、实测点云、影像证据和问题标记。缺少模型、未处理点云或尚未校核时，工作区会显示对应的数据质量提示，不绘制误导性的空白场景。

三维杆塔和道路等对象根据当前 JSON/CSV 数据进行参数化表达，界面会标明推算几何。只有拍摄位置能关联到杆塔或构件编号的照片才进入空间场景；无法定位的照片保留在“待定位证据”中。Three.js r184 及 OrbitControls 已打包在 `static/vendor/`，运行时不依赖互联网，许可文件为 `static/vendor/THREE-LICENSE.txt`。

## 示例数据

首次运行时系统保持空白，不会自动生成验收任务。用户应先创建验收任务，再上传现场照片或工程资料。空白任务中心提供“加载示例数据”按钮，可按需生成以下演示资料：

- `sample_data/design_model.json`：GIM-like 设计模型。
- `sample_data/pointcloud.csv`：CSV 点云样例。
- `sample_data/images/`：现场影像样例。
- `sample_data/upload_tests/现场照片_绝缘子金具锈蚀测试.png`：用于手动上传和真实本地模型推理测试的现场照片。
- `storage/evidence/`：影像诊断标注证据图。
- `storage/reports/`：验收校核报告。

“加载示例数据”生成的内置诊断记录会明确登记为 `demo-explicit-detector`，用于离线展示业务闭环；该按钮只在系统没有业务任务时显示。用户从“影像验收”页上传的照片不会使用演示检测器，而是执行质量门禁、Grounding DINO 本地推理和规则校核。

## 接口摘要

- `POST /api/tasks/{id}/pointcloud/process`：执行点云解析、分片、对象识别和量测。
- `GET /api/tasks/{id}/fusion-scene`：返回融合场景图层数据。
- `POST /api/tasks/{id}/compare/run`：执行模型点云偏差校核。
- `POST /api/tasks/{id}/images/upload`：上传现场照片，自动执行影像诊断并返回照片级验收结论。
- `GET /api/tasks/{id}/vision/acceptance`：返回当前任务影像资料的验收结论汇总。
- `POST /api/tasks/{id}/vision/run`：执行影像缺陷诊断并生成证据图。
- `GET /api/ai/model/status`：返回本地模型文件、依赖、设备和加载状态。
- `GET /api/rules`、`PUT /api/rules/{rule_id}`：查询或维护版本化验收规则。
- `POST /api/tasks/{id}/report/export`：导出校核报告。

## 测试

```bash
python -m compileall -q line_acceptance
python -m pytest tests -q
```

也可以使用标准库测试：

```bash
python -m unittest discover -s tests
```

## 软著材料口径

系统输出属于 AI 辅助初判。正式使用前应把建设单位确认的标准条文和阈值录入规则库；涉及缺陷的最终验收结论由验收人员结合现场资料复核确认。

后续生成源程序代码材料时，建议优先抽取以下原创源码：

- `line_acceptance/services/pointcloud_service.py`
- `line_acceptance/services/check_service.py`
- `line_acceptance/services/vision_service.py`
- `line_acceptance/services/ai_model_service.py`
- `line_acceptance/services/rule_service.py`
- `line_acceptance/services/fusion_service.py`
- `line_acceptance/web.py`
- `static/app.js`
- `static/index.html`
- `static/styles.css`

第三方依赖仅作为运行环境，不作为原创源程序代码材料提交。
