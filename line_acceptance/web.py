from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .app_context import AppContext, create_context
from .config import load_config
from .seed import seed_demo


class TaskCreateRequest(BaseModel):
    project_name: str = Field(..., min_length=1)
    line_name: str = Field(..., min_length=1)
    section_name: str = Field(..., min_length=1)
    batch_no: str = Field(..., min_length=1)
    owner: str = Field(..., min_length=1)
    construction_unit: str = ""
    acceptance_scope: str = "GIM-like 模型、点云、影像资料及问题台账校核"
    operator: str = "资料管理员"


def create_app(context: AppContext | None = None) -> FastAPI:
    config = load_config()
    app_context = context or create_context(config)

    app = FastAPI(
        title="基于人工智能的线路工程验收校核软件",
        version="1.1.0",
        description="面向线路工程验收的模型、点云、影像融合校核本地 Web 服务。",
    )
    app.state.context = app_context

    app.mount("/static", StaticFiles(directory=app_context.config.root_dir / "static"), name="static")
    app.mount("/evidence", StaticFiles(directory=app_context.config.evidence_dir), name="evidence")
    app.mount("/reports", StaticFiles(directory=app_context.config.report_dir), name="reports")
    app.mount("/uploads", StaticFiles(directory=app_context.config.storage_dir), name="uploads")
    app.mount("/sample_data", StaticFiles(directory=app_context.config.root_dir / "sample_data"), name="sample_data")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(app_context.config.root_dir / "static" / "index.html")

    @app.get("/api/summary")
    def summary() -> dict[str, Any]:
        return call(lambda: app_context.tasks.summary())

    @app.get("/api/ai/model/status")
    def ai_model_status() -> dict[str, Any]:
        return call(lambda: app_context.ai_models.status())

    @app.get("/api/rules")
    def rules(module: Optional[str] = None) -> dict[str, Any]:
        return call(lambda: {"items": app_context.rule_service.list_rules(module=module)})

    @app.put("/api/rules/{rule_id}")
    def update_rule(rule_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: app_context.rule_service.update_rule(rule_id, data, operator=data.get("operator", "系统管理员")))

    @app.post("/api/rules/reset")
    def reset_rules(payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(
            lambda: {
                "items": app_context.rule_service.restore_defaults(
                    data.get("rule_id"),
                    operator=data.get("operator", "系统管理员"),
                )
            }
        )

    @app.get("/api/tasks")
    def tasks() -> dict[str, Any]:
        return call(lambda: {"items": app_context.tasks.list_tasks()})

    @app.get("/api/tasks/{task_id}")
    def task_detail(task_id: str) -> dict[str, Any]:
        return call(lambda: app_context.tasks.get_task(task_id))

    @app.get("/api/tasks/{task_id}/checks")
    def checks(task_id: str) -> dict[str, Any]:
        return call(lambda: {"items": app_context.checks.results(task_id)})

    @app.get("/api/tasks/{task_id}/vision")
    def vision(task_id: str) -> dict[str, Any]:
        return call(lambda: {"items": app_context.vision.results(task_id)})

    @app.get("/api/tasks/{task_id}/vision/acceptance")
    def vision_acceptance(task_id: str) -> dict[str, Any]:
        return call(lambda: app_context.vision.task_acceptance(task_id))

    @app.get("/api/tasks/{task_id}/acceptance-summary")
    def acceptance_summary(task_id: str) -> dict[str, Any]:
        return call(lambda: app_context.vision.task_acceptance(task_id))

    @app.get("/api/tasks/{task_id}/fusion-scene")
    def fusion_scene(task_id: str, persist: bool = Query(default=False)) -> dict[str, Any]:
        return call(lambda: app_context.fusion.build_scene(task_id, persist=persist))

    @app.get("/api/issues")
    def issues(task_id: Optional[str] = None, level: Optional[str] = None, keyword: Optional[str] = None) -> dict[str, Any]:
        return call(lambda: {"items": app_context.issues.list_issues(task_id=task_id, level=level, keyword=keyword)})

    @app.post("/api/demo/load")
    def load_demo() -> dict[str, Any]:
        def action() -> dict[str, Any]:
            if app_context.tasks.list_tasks():
                raise ValueError("系统中已有验收任务，不能加载示例数据")
            return seed_demo(app_context, reset=False)

        return call(action)

    @app.post("/api/tasks")
    def create_task(payload: TaskCreateRequest) -> dict[str, Any]:
        data = payload.model_dump()
        operator = data.pop("operator")
        return call(lambda: app_context.tasks.create_task(data, operator=operator))

    @app.post("/api/tasks/{task_id}/model/import")
    def import_model(task_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: app_context.models.import_design_model(task_id, data, operator=data.get("operator", "资料管理员")))

    @app.post("/api/tasks/{task_id}/model/upload")
    async def upload_model(
        task_id: str,
        file: UploadFile = File(...),
        model_version: str = Form("V1.0"),
        operator: str = Form("资料管理员"),
    ) -> dict[str, Any]:
        content = await file.read()
        return call(
            lambda: app_context.models.import_uploaded_design_model(
                task_id,
                file.filename or "design_model.json",
                content,
                model_version=model_version,
                operator=operator,
            )
        )

    @app.post("/api/tasks/{task_id}/pointcloud/import")
    def import_pointcloud(task_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: app_context.assets.import_pointcloud(task_id, data, operator=data.get("operator", "资料管理员")))

    @app.post("/api/tasks/{task_id}/pointcloud/upload")
    async def upload_pointcloud(
        task_id: str,
        file: UploadFile = File(...),
        coordinate_system: str = Form("CGCS2000"),
        operator: str = Form("资料管理员"),
    ) -> dict[str, Any]:
        content = await file.read()
        return call(
            lambda: app_context.assets.import_uploaded_pointcloud(
                task_id,
                file.filename or "pointcloud.csv",
                content,
                coordinate_system=coordinate_system,
                operator=operator,
            )
        )

    @app.post("/api/tasks/{task_id}/pointcloud/process")
    def process_pointcloud(task_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: app_context.pointcloud.process_task_pointcloud(task_id, data, operator=data.get("operator", "验收工程师")))

    @app.post("/api/tasks/{task_id}/images/import")
    def import_images(task_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: {"items": app_context.assets.import_images(task_id, data, operator=data.get("operator", "资料管理员"))})

    @app.post("/api/tasks/{task_id}/images/upload")
    async def upload_image(
        task_id: str,
        file: UploadFile = File(...),
        shoot_position: str = Form("现场照片"),
        source_type: str = Form("照片"),
        operator: str = Form("验收工程师"),
    ) -> dict[str, Any]:
        content = await file.read()
        return call(
            lambda: app_context.vision.analyze_uploaded_photo(
                task_id,
                file.filename or "现场照片.png",
                content,
                shoot_position=shoot_position,
                source_type=source_type,
                operator=operator,
            )
        )

    @app.post("/api/tasks/{task_id}/registration/run")
    def run_registration(task_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: app_context.registration.run_registration(task_id, data, operator=data.get("operator", "验收工程师")))

    @app.post("/api/tasks/{task_id}/checks/run")
    def run_checks(task_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: {"items": app_context.checks.run_geometry_checks(task_id, data, operator=data.get("operator", "验收工程师"))})

    @app.post("/api/tasks/{task_id}/compare/run")
    def run_compare(task_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: {"items": app_context.checks.run_model_pointcloud_compare(task_id, data, operator=data.get("operator", "验收工程师"))})

    @app.post("/api/tasks/{task_id}/vision/run")
    def run_vision(task_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: {"items": app_context.vision.analyze_task_images(task_id, data, operator=data.get("operator", "验收工程师"))})

    @app.post("/api/tasks/{task_id}/report/export")
    def export_report(task_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}

        def export() -> dict[str, Any]:
            report = app_context.reports.export_report(task_id, data, operator=data.get("operator", "验收工程师"))
            report["download_url"] = report_url(app_context.config.report_dir, report["file_path"])
            return report

        return call(export)

    @app.post("/api/issues/{issue_id}/review")
    def review_issue(issue_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: app_context.issues.review_issue(issue_id, data, operator=data.get("operator", "复核人员")))

    @app.post("/api/issues/{issue_id}/rectify")
    def rectify_issue(issue_id: str, payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
        data = payload or {}
        return call(lambda: app_context.issues.update_rectify_status(issue_id, data.get("status", "整改中"), operator=data.get("operator", "复核人员")))

    return app


def call(factory):
    try:
        return factory()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def report_url(report_dir: Path, file_path: str) -> str:
    path = Path(file_path)
    try:
        rel = path.resolve().relative_to(report_dir.resolve())
        return "/reports/" + "/".join(rel.parts)
    except ValueError:
        return ""


def serve(host: Optional[str] = None, port: Optional[int] = None) -> None:
    config = load_config()
    app = create_app(create_context(config))
    address_host = host or config.host
    address_port = port or config.port
    print(f"基于人工智能的线路工程验收校核软件已启动：http://{address_host}:{address_port}")
    print("按 Ctrl+C 停止服务。")
    import uvicorn

    uvicorn.run(app, host=address_host, port=address_port, log_level="warning")
