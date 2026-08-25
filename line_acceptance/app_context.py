from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .database import Database
from .rules import RuleBook
from .services import (
    AIModelService,
    AssetService,
    CheckService,
    FusionService,
    IssueService,
    ModelService,
    PointCloudService,
    RegistrationService,
    ReportService,
    RuleService,
    TaskService,
    VisionService,
)


@dataclass
class AppContext:
    config: AppConfig
    db: Database
    rules: RuleBook
    tasks: TaskService
    models: ModelService
    assets: AssetService
    pointcloud: PointCloudService
    registration: RegistrationService
    checks: CheckService
    fusion: FusionService
    vision: VisionService
    issues: IssueService
    reports: ReportService
    rule_service: RuleService
    ai_models: AIModelService


def create_context(config: AppConfig) -> AppContext:
    db = Database(config)
    db.init_schema()
    rules = RuleBook(config.rule_file)
    rule_service = RuleService(db, rules)
    ai_models = AIModelService(db, config.model_dir)
    return AppContext(
        config=config,
        db=db,
        rules=rules,
        tasks=TaskService(db),
        models=ModelService(db, config.root_dir),
        assets=AssetService(db, config.root_dir),
        pointcloud=PointCloudService(db, rules, config.root_dir),
        registration=RegistrationService(db, rules),
        checks=CheckService(db, rules),
        fusion=FusionService(db, config.root_dir),
        vision=VisionService(
            db,
            rules,
            rule_service,
            ai_models,
            config.root_dir,
            config.evidence_dir,
            config.storage_dir,
        ),
        issues=IssueService(db),
        reports=ReportService(db, config.report_dir),
        rule_service=rule_service,
        ai_models=ai_models,
    )
