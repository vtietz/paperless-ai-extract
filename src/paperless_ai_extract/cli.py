"""Command line: check | analyse | process | serve | health."""
from __future__ import annotations

import argparse
import json
import os
import logging
import shutil
import sqlite3
import sys
import time

from .config import ConfigError, load_config
from .domain.errors import ExtractError


def _setup_logging(verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def cmd_check(args, config) -> int:
    from .bootstrap import build_extractor
    ok = True

    def report(name, fn):
        nonlocal ok
        try:
            print(f"[ok]   {name}: {fn() or 'ok'}")
        except Exception as exc:  # noqa: BLE001 - diagnostics command
            ok = False
            print(f"[fail] {name}: {exc}")

    extractor = build_extractor(config)
    report("paperless", extractor.store.ping)
    report("llm", extractor.llm.check)
    ctx_holder = {}

    def context():
        ctx_holder["ctx"] = extractor.context(create_tags=True if args.create_tags else None)
        ctx = ctx_holder["ctx"]
        return f"{len(ctx.taxonomy.correspondents)} correspondents, fingerprint {ctx.fingerprint}"
    report("taxonomy/prompt/schema", context)

    def tags():
        ctx = ctx_holder["ctx"]
        names = config.queue.tags.model_dump()
        missing = [n for role, n in names.items() if n and role not in ctx.tag_ids]
        if missing:
            raise ConfigError(f"missing tags {missing}; rerun with --create-tags")
        return ", ".join(f"{r}={i}" for r, i in ctx.tag_ids.items())
    if "ctx" in ctx_holder:
        report("queue tags", tags)
    for tool in ("pdftoppm", "pdfinfo", "tesseract"):
        if shutil.which(tool) is None:
            ok = False
            print(f"[fail] tool {tool} not installed")
    return 0 if ok else 1


def cmd_analyse(args, config) -> int:
    """Dry run: extract and plan, never write to Paperless."""
    from .bootstrap import build_extractor
    extractor = build_extractor(config)
    ctx = extractor.context(create_tags=False)
    status = 0
    for doc_id in args.documents:
        try:
            outcome = extractor.analyse(doc_id, ctx, force=args.force, mode=args.mode)
        except ExtractError as exc:
            print(json.dumps({"document": doc_id, "error": f"{exc.__class__.__name__}: {exc}"}))
            status = 1
            continue
        print(json.dumps({"document": doc_id, "cached": outcome.cached,
                          "metrics": outcome.metrics,
                          "extraction": outcome.extraction.to_dict(),
                          "plan": outcome.plan.to_dict()}, ensure_ascii=False, indent=2))
    return status


def cmd_process(args, config) -> int:
    """Process given documents now (same use case as the queue)."""
    from .bootstrap import build_extractor
    extractor = build_extractor(config)
    ctx = extractor.context()
    status = 0
    for doc_id in args.documents:
        try:
            outcome = extractor.process(doc_id, ctx, force=args.force, mode=args.mode)
            print(json.dumps({"document": doc_id,
                              "filled": [c.field for c in outcome.written],
                              "proposed": [c.field for c in outcome.plan.proposals],
                              "review": outcome.plan.review}))
        except ExtractError as exc:
            print(json.dumps({"document": doc_id, "error": f"{exc.__class__.__name__}: {exc}"}))
            status = 1
    return status


def cmd_serve(args, config) -> int:
    from .bootstrap import build_worker
    worker = build_worker(config)
    logging.getLogger("paperless_ai_extract").info(
        "serving: poll %ss, %s via %s, input %s", config.queue.poll_interval,
        config.llm.model, config.llm.provider, config.input.mode)
    worker.run(once=args.once)
    return 0


def cmd_health(args, config) -> int:
    try:
        beat = float(config.state.heartbeat_file.read_text())
    except (OSError, ValueError):
        return 1
    limit = config.queue.poll_interval * 3 + config.llm.timeout * config.queue.batch_size
    return 0 if time.time() - beat < limit else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paperless-ai-extract")
    parser.add_argument("-c", "--config", default=os.environ.get("PAE_CONFIG", "/config/config.yaml"),
                        help="YAML config (optional when configured via environment)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="verify Paperless, LLM, taxonomy, tags and tools")
    check.add_argument("--create-tags", action="store_true")
    for name, help_text in (("analyse", "dry run: print extraction and plan, write nothing"),
                            ("process", "analyse and write now (as the queue would)")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("documents", nargs="+", type=int)
        p.add_argument("--force", action="store_true", help="ignore cached extraction")
        p.add_argument("--mode", choices=["first_run", "rerun"])
    serve = sub.add_parser("serve", help="run the tag-driven queue")
    serve.add_argument("--once", action="store_true")
    sub.add_parser("health", help="exit 0 if the worker heartbeat is fresh")
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    commands = {"check": cmd_check, "analyse": cmd_analyse, "process": cmd_process,
                "serve": cmd_serve, "health": cmd_health}
    try:
        return commands[args.command](args, config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error) as exc:
        print(f"state error ({config.state.path}): {exc}", file=sys.stderr)
        return 2
