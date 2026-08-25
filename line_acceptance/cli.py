from __future__ import annotations

import argparse
import json
import sys

from .app_context import create_context
from .config import load_config
from .seed import seed_demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="line-accept", description="线路工程验收校核软件命令行工具")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="初始化数据库")
    sub.add_parser("demo", help="重置数据库并生成示例任务、点云处理结果、校核结果和报告")
    sub.add_parser("summary", help="输出任务、量测、缺陷和报告统计")
    serve = sub.add_parser("serve", help="启动本地 Web 服务")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    report = sub.add_parser("export-report", help="导出指定任务报告")
    report.add_argument("task_id")
    report.add_argument("--format", choices=["docx", "md"], default="docx")
    args = parser.parse_args(argv)

    config = load_config()
    context = create_context(config)
    if args.command == "init-db":
        context.db.init_schema()
        print(f"数据库已初始化：{config.database_path}")
    elif args.command == "demo":
        task = seed_demo(context, reset=True)
        print(json.dumps({"task_id": task["id"], "task_no": task["task_no"]}, ensure_ascii=False, indent=2))
    elif args.command == "summary":
        print(json.dumps(context.tasks.summary(), ensure_ascii=False, indent=2))
    elif args.command == "export-report":
        item = context.reports.export_report(args.task_id, {"format": args.format})
        print(json.dumps(item, ensure_ascii=False, indent=2))
    elif args.command == "serve":
        from .web import serve as web_serve

        web_serve(host=args.host or config.host, port=args.port or config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
