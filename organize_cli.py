"""Command line entry point for the decoupled fetch/organize features.

Usage
-----
    python organize_cli.py organize ./发票 --output ./发票库             # 预览（默认 dry-run）
    python organize_cli.py organize ./发票 --output ./发票库 --apply     # 真正归档
    python organize_cli.py fetch --email you@qq.com --auth-code env:QQ_AUTH_CODE \
        --output ./发票库 [--since 2026-01-01] [--before 2026-10-31]

``organize`` never reads mailbox settings and ``fetch`` never parses invoices;
they only share ``inbox/`` + ``manifest.jsonl``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sys
from typing import Sequence


def _resolve_secret(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("env:"):
        return str(os.environ.get(text[4:].strip(), ""))
    return text


def _default_output_dir(input_dir: str) -> str:
    """Organize inside the invoice folder itself unless another output is given."""
    return os.path.abspath(input_dir)


def _configure_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(message)s")
    for name in ("pdfminer", "PIL", "fitz", "rapidocr_onnxruntime"):
        logging.getLogger(name).setLevel(logging.ERROR)


def _print_organize_human(result) -> None:
    request = result.request
    mode = "预览（未移动文件）" if result.dry_run else "已执行归档"
    print("=" * 70)
    print(f"发票整理 · {mode}")
    print(f"输入目录: {request.input_dir}")
    print(f"输出目录: {request.output_dir}")
    print(
        "扫描: 文件 %d · 批内重复 %d · 忽略非发票 %d · manifest %d"
        % (
            result.scanned_files,
            result.duplicate_files,
            result.unsupported_files,
            result.manifest_entries,
        )
    )
    print(
        "结果: 归档 %d · 重复跳过 %d · 待人工复核 %d · 保全 %d · 失败 %d"
        % (
            result.archived_count,
            result.duplicate_count,
            result.manual_count,
            result.retained_count,
            result.unresolved_count,
        )
    )
    if result.raw_moved_count or result.duplicates_moved_count:
        print(
            "归位: 原件 → raw/ %d 个 · 重复件 → duplicates/ %d 个"
            % (result.raw_moved_count, result.duplicates_moved_count)
        )
    if result.preview_rows:
        print("-" * 70)
        print(f"{'原文件':<28}{'→ 分类/新文件名':<40}")
        for row in result.preview_rows:
            source = str(row.get("source") or row.get("name") or "")[:26]
            target = str(row.get("path") or "")
            target_label = "%s/%s" % (
                row.get("category") or "?",
                os.path.basename(target),
            ) if target else (row.get("reason") or "")
            print(f"{source:<28}→ {target_label}")
    if result.warnings:
        print("-" * 70)
        for warning in result.warnings[:10]:
            print(f"提示: {warning}")
    if result.report_path:
        print(f"结果明细: {result.report_path}")
    print("=" * 70)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="organize_cli.py",
        description="发票提取与整理（两个互不依赖的功能）",
    )
    sub = parser.add_subparsers(dest="command")

    organize = sub.add_parser(
        "organize", help="整理本地文件夹（默认仅预览；默认输出到原文件夹）"
    )
    organize.add_argument("input", help="要整理的发票文件夹")
    organize.add_argument(
        "--output", default="", help="归档输出目录（默认与原文件夹相同，即原地整理）"
    )
    organize.add_argument(
        "--apply",
        action="store_true",
        help="真正执行整理（默认仅预览；同目录整理时原件移入 raw/、重复件移入 duplicates/）",
    )
    organize.add_argument("--rules", default="", help="可选的自定义分类规则文本文件")
    organize.add_argument(
        "--json", action="store_true", help="以 JSON 输出结果（适合脚本消费）"
    )
    organize.add_argument("--verbose", action="store_true", help="输出识别过程日志")

    fetch = sub.add_parser("fetch", help="只从邮箱提取附件到 inbox（不解析）")
    fetch.add_argument("--email", required=True, help="邮箱地址")
    fetch.add_argument(
        "--auth-code",
        required=True,
        help="IMAP 授权码；支持 env:VAR 从环境变量读取",
    )
    fetch.add_argument("--output", required=True, help="输出目录（inbox 将建在其中）")
    fetch.add_argument("--since", default="", help="起始日期 YYYY-MM-DD（默认近 30 天）")
    fetch.add_argument("--before", default="", help="结束日期 YYYY-MM-DD（含当天）")
    fetch.add_argument("--mailbox", default="INBOX", help="邮箱文件夹（默认 INBOX）")
    fetch.add_argument("--imap-host", default="", help="IMAP 服务器（默认按邮箱域名识别）")
    fetch.add_argument("--imap-port", type=int, default=0, help="IMAP 端口")
    fetch.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    return parser


def _run_organize(args: argparse.Namespace) -> int:
    from app_api import InvoiceAppAPI
    from local_organize import OrganizeRequest, LocalOrganizer, validate_request

    output_dir = args.output or _default_output_dir(args.input)
    rules_text = ""
    if args.rules:
        try:
            with open(args.rules, "r", encoding="utf-8-sig") as handle:
                rules_text = handle.read()
        except OSError as exc:
            print(f"无法读取规则文件: {exc}", file=sys.stderr)
            return 2
    request = OrganizeRequest(
        input_dir=args.input,
        output_dir=output_dir,
        rules_text=rules_text,
        dry_run=not bool(args.apply),
    )
    validation_error = validate_request(request)
    if validation_error:
        print(validation_error, file=sys.stderr)
        return 2

    api = InvoiceAppAPI()
    api._stop_requested = False
    organizer = LocalOrganizer(api, request)
    try:
        if args.json:
            with contextlib.redirect_stdout(sys.stderr):
                result = organizer.run()
        else:
            result = organizer.run()
    except Exception as exc:  # keep the CLI contract stable for scripts
        payload = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"整理失败: {exc}", file=sys.stderr)
        return 1

    if args.json:
        payload = {"ok": True, **result.to_dict()}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_organize_human(result)
    return 0


def _run_fetch(args: argparse.Namespace) -> int:
    from fetch_only import FetchOnlyRequest, FetchOnlyRunner

    auth_code = _resolve_secret(args.auth_code)
    request = FetchOnlyRequest(
        email_address=str(args.email or "").strip(),
        auth_code=auth_code,
        output_dir=args.output,
        date_from=str(args.since or ""),
        date_to=str(args.before or ""),
        mailbox=str(args.mailbox or "INBOX"),
        imap_host=str(args.imap_host or ""),
        imap_port=int(args.imap_port or 0),
    )
    result = FetchOnlyRunner().run(request)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "message": result.message,
                    "error_reason": result.error_reason,
                    "emails": result.email_count,
                    "attachments": result.attachment_count,
                    "saved": result.saved_count,
                    "duplicates": result.duplicate_count,
                    "todos": result.link_count,
                    "inbox_dir": result.inbox_dir,
                    "manifest_path": result.manifest_path,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        if not result.ok:
            print(f"提取失败: {result.message}", file=sys.stderr)
        else:
            print("=" * 70)
            print("邮箱提取完成（未解析、未归档）")
            print(
                "邮件 %d · 附件 %d · 新增 %d · 重复 %d · 需人工处理链接 %d"
                % (
                    result.email_count,
                    result.attachment_count,
                    result.saved_count,
                    result.duplicate_count,
                    result.link_count,
                )
            )
            print(f"交接目录: {result.inbox_dir}")
            print(f"元数据清单: {result.manifest_path}")
            print("=" * 70)
    return 0 if result.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(bool(getattr(args, "verbose", False)))
    if args.command == "organize":
        return _run_organize(args)
    if args.command == "fetch":
        return _run_fetch(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
