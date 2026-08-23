"""Command line interface — the same pipeline the Gradio app drives.

    python -m archivist app                      launch the UI
    python -m archivist run "deep sea salvage"   one full run
    python -m archivist check                    connection self-test
    python -m archivist plan "north sea oil" -n 6
    python -m archivist jobs / job-run <id>
    python -m archivist deploy --port 7860
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import connectivity, deploy as deploy_mod, storage
from .config import Settings
from .pipeline import PipelineOptions, autopilot as run_autopilot, run as run_pipeline
from .queries import cluster_summary, generate_queries
from .scheduler import Scheduler, plan_preview, plan_topics
from .trends import derive_ladder


def _settings(args: argparse.Namespace) -> Settings:
    overrides = {}
    for name in ("collection", "offline", "keep_references", "max_queries", "seed", "garment"):
        value = getattr(args, name, None)
        if value is not None:
            overrides[name] = value
    if getattr(args, "runs_dir", None):
        overrides["runs_dir"] = Path(args.runs_dir)
    return Settings.from_env(**overrides)


def cmd_run(args: argparse.Namespace) -> int:
    settings = _settings(args)
    options = PipelineOptions(
        audience=args.audience,
        garment=args.garment or settings.garment,
        aggressiveness=args.aggressiveness,
        variants=list(args.variants),
        generate=not args.no_generate,
        generate_keys=list(args.generate or []),
        include_text=not args.no_text,
        build_mockup=not args.no_mockup,
        use_llm=not args.no_llm,
    )
    result = run_pipeline(args.topic, settings, options, log=lambda line: print(line, flush=True))
    print("\n" + "=" * 72)
    print(f"style      : {result.direction.style_name if result.direction else '—'}")
    print(f"micro-niche: {result.ladder.micro_niche if result.ladder else '—'}")
    print(f"references : {len(result.references)} of {result.candidates}")
    for concept in result.concepts:
        mark = "★" if concept.key == result.recommended else " "
        print(f" {mark} {concept.key} {concept.lane:<22} {concept.overall:>5}  {concept.name}")
    print(f"run        : {result.run_dir}")
    for warning in result.warnings:
        print(f"warning    : {warning}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Find topics — no design work, just the research."""
    from .discovery import DiscoveryEngine
    from .llm import LLM

    settings = _settings(args)
    llm = LLM(settings.openai_api_key, model=settings.openai_model,
              base_url=settings.openai_base_url, enabled=settings.can_use_llm and not args.no_llm)
    engine = DiscoveryEngine(settings, llm=llm, log=lambda line: print(line, flush=True))
    report = engine.discover(count=args.count)
    path = engine.write_report(report)

    print("\n" + "=" * 96)
    header = f"{'score':>5}  {'topic':<38} {'growth':>8} {'social':>7} {'eng/post':>9} {'comp':>6}  sources"
    print(header)
    print("-" * 96)
    for opportunity in report.opportunities:
        print(f"{opportunity.overall:5.2f}  {opportunity.topic[:38]:<38} "
              f"{opportunity.growth_3m:+7.0f}% {opportunity.social_heat:7.0f} "
              f"{opportunity.avg_engagement:9.0f} {opportunity.competition:6.0f}  "
              f"{','.join(opportunity.sources)}")
        if opportunity.angle:
            print(f"       angle: {opportunity.angle}")
    if args.rejected:
        print("\nrejected:")
        for opportunity in report.rejected[:20]:
            print(f"  {opportunity.topic[:44]:<44} {opportunity.rejected_reason}")
    print(f"\nfamilies: {report.families}")
    print(f"report: {path}")
    return 0 if report.opportunities else 1


def cmd_autopilot(args: argparse.Namespace) -> int:
    """Discover topics and design them — the whole bot in one command."""
    settings = _settings(args)
    options = PipelineOptions(
        garment=args.garment or settings.garment,
        aggressiveness=args.aggressiveness,
        generate=not args.no_generate,
        build_mockup=not args.no_mockup,
        use_llm=not args.no_llm,
    )
    result = run_autopilot(
        settings, options, designs=args.designs, log=lambda line: print(line, flush=True)
    )
    print("\n" + "=" * 72)
    if result.report is not None:
        for opportunity in result.report.opportunities:
            print(f"  candidate {opportunity.overall:5.2f}  {opportunity.summary()}")
    for run_result in result.runs:
        print(f"  designed: {run_result.topic} -> {run_result.run_dir} "
              f"(recommended {run_result.recommended})")
    for warning in result.warnings:
        print(f"  warning: {warning}")
    return 0 if result.runs else 1


def cmd_app(args: argparse.Namespace) -> int:
    from .app import main as app_main

    argv = ["--host", args.host, "--port", str(args.port)]
    if args.share:
        argv.append("--share")
    if args.open:
        argv.append("--open")
    if args.auth:
        argv += ["--auth", args.auth]
    if args.scheduler:
        argv.append("--scheduler")
    return app_main(argv)


def cmd_check(args: argparse.Namespace) -> int:
    settings = _settings(args)
    results = connectivity.run_checks(settings, include_generation=not args.no_generation)
    width = max(len(result.name) for result in results)
    for result in results:
        print(f"{result.badge:<8} {result.name:<{width}}  {result.ms:>5} ms  {result.detail}")
    print("\n" + connectivity.summarise(results))
    return 0 if all(r.ok for r in results if r.required) else 1


def cmd_queries(args: argparse.Namespace) -> int:
    settings = _settings(args)
    ladder = derive_ladder(args.topic, aggressiveness=args.aggressiveness, seed=settings.seed)
    queries = generate_queries(args.topic, ladder, count=settings.max_queries, seed=settings.seed)
    print(f"micro-niche: {ladder.micro_niche}\n")
    for query in queries:
        print(f"  [{query.cluster.value}] {query.text}")
    print(f"\nclusters: {cluster_summary(queries)}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    settings = _settings(args)
    topics = plan_topics(args.theme, args.count, seed=settings.seed)
    rows = plan_preview(topics, cadence=args.cadence, interval_minutes=args.interval, at_time=args.at)
    for index, when, topic in rows:
        print(f"{index:>2}  {when}  {topic}")
    if args.create:
        scheduler = Scheduler(settings)
        job = scheduler.create_job(
            args.name or f"{args.theme} plan", topics, cadence=args.cadence,
            interval_minutes=args.interval, at_time=args.at,
            options={"collection": settings.collection, "generate": not args.no_generate},
        )
        print(f"\ncreated job {job.id} — {job.describe()} (start the app or `archivist serve-scheduler` to run it)")
    return 0


def cmd_jobs(args: argparse.Namespace) -> int:
    scheduler = Scheduler(_settings(args))
    rows = scheduler.job_rows()
    if not rows:
        print("no jobs configured")
        return 0
    for row in rows:
        print("  ".join(str(cell) for cell in row))
    return 0


def cmd_job_run(args: argparse.Namespace) -> int:
    scheduler = Scheduler(_settings(args), on_event=lambda message: print(message, flush=True))
    entry = scheduler.run_job(args.job_id)
    print(entry)
    return 0 if entry.get("status") == "ok" else 1


def cmd_serve_scheduler(args: argparse.Namespace) -> int:
    """Run only the scheduler — for a headless box that does not need the UI."""
    import time

    scheduler = Scheduler(_settings(args), on_event=lambda message: print(message, flush=True))
    scheduler.start()
    print("scheduler running — ctrl-c to stop")
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        scheduler.stop()
        print("stopped")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    settings = _settings(args)
    rows = storage.list_runs(settings.runs_dir, limit=args.limit)
    if not rows:
        print(f"no runs under {Path(settings.runs_dir).resolve()}")
        return 0
    for row in rows:
        print(f"{row['created']}  {row['collection']:<12} {row['status']:<7} "
              f"{row['refs']:>3} refs  {row['best_score']:>5}  {row['topic']}")
        print(f"   {row['run_dir']}")
    print("\n" + str(storage.stats(settings.runs_dir)))
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    written = deploy_mod.materialise(
        args.target, port=args.port, image=args.image, user=args.user,
        workdir=args.workdir, windows_workdir=args.windows_workdir,
    )
    for path in written:
        print(f"wrote {path}")
    for key, value in deploy_mod.summary(args.port, args.target).items():
        print(f"{key:<8} {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archivist", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collection", help="collection name (shares a style lock)")
    parser.add_argument("--runs-dir", help="where runs are written")
    parser.add_argument("--offline", action="store_true", default=None, help="synthetic references, no network")
    parser.add_argument("--seed", type=int, help="deterministic seed")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the full pipeline for one topic")
    run.add_argument("topic")
    run.add_argument("--audience", default="")
    run.add_argument("--garment", default=None, choices=["dark", "faded-black", "black", "light", "white", "sand"])
    run.add_argument("--aggressiveness", type=int, default=5, choices=range(0, 11), metavar="0-10")
    run.add_argument("--variants", nargs="+", default=["A", "B", "C"])
    run.add_argument("--generate", nargs="*", help="which variants to render (default: recommended)")
    run.add_argument("--no-generate", action="store_true", help="prompts and print settings only")
    run.add_argument("--no-text", action="store_true", help="no lettering in the artwork")
    run.add_argument("--no-mockup", action="store_true")
    run.add_argument("--no-llm", action="store_true")
    run.add_argument("--keep-references", type=int, default=None)
    run.add_argument("--max-queries", type=int, default=None)
    run.set_defaults(func=cmd_run)

    discover = sub.add_parser("discover", help="find trending topics worth designing (no design work)")
    discover.add_argument("-n", "--count", type=int, default=6)
    discover.add_argument("--rejected", action="store_true", help="also list what was filtered out and why")
    discover.add_argument("--no-llm", action="store_true")
    discover.set_defaults(func=cmd_discover)

    auto = sub.add_parser("autopilot", help="discover topics AND design them, with no input")
    auto.add_argument("-n", "--designs", type=int, default=None, help="how many topics to design")
    auto.add_argument("--garment", default=None)
    auto.add_argument("--aggressiveness", type=int, default=5)
    auto.add_argument("--no-generate", action="store_true")
    auto.add_argument("--no-mockup", action="store_true")
    auto.add_argument("--no-llm", action="store_true")
    auto.set_defaults(func=cmd_autopilot)

    app = sub.add_parser("app", help="launch the Gradio control room")
    app.add_argument("--host", default="127.0.0.1")
    app.add_argument("--port", type=int, default=7860)
    app.add_argument("--share", action="store_true")
    app.add_argument("--open", action="store_true")
    app.add_argument("--auth", default="")
    app.add_argument("--scheduler", action="store_true", help="start the scheduler with the app")
    app.set_defaults(func=cmd_app)

    check = sub.add_parser("check", help="connection self-test")
    check.add_argument("--no-generation", action="store_true", help="skip the BFL probe")
    check.set_defaults(func=cmd_check)

    queries = sub.add_parser("queries", help="show the search queries for a topic")
    queries.add_argument("topic")
    queries.add_argument("--aggressiveness", type=int, default=5)
    queries.add_argument("--max-queries", type=int, default=None)
    queries.set_defaults(func=cmd_queries)

    plan = sub.add_parser("plan", help="auto-plan a collection from one theme")
    plan.add_argument("theme")
    plan.add_argument("-n", "--count", type=int, default=6)
    plan.add_argument("--cadence", default="daily", choices=["interval", "daily", "weekly", "once"])
    plan.add_argument("--interval", type=int, default=720, help="minutes, for --cadence interval")
    plan.add_argument("--at", default="09:00", help="HH:MM local, for daily/weekly")
    plan.add_argument("--create", action="store_true", help="persist it as a scheduled job")
    plan.add_argument("--name", default="")
    plan.add_argument("--no-generate", action="store_true")
    plan.set_defaults(func=cmd_plan)

    jobs = sub.add_parser("jobs", help="list scheduled jobs")
    jobs.set_defaults(func=cmd_jobs)

    job_run = sub.add_parser("job-run", help="run one scheduled job now")
    job_run.add_argument("job_id")
    job_run.set_defaults(func=cmd_job_run)

    serve = sub.add_parser("serve-scheduler", help="run the scheduler headless")
    serve.set_defaults(func=cmd_serve_scheduler)

    runs = sub.add_parser("runs", help="list past runs")
    runs.add_argument("--limit", type=int, default=20)
    runs.set_defaults(func=cmd_runs)

    deploy = sub.add_parser("deploy", help="write deployment artefacts")
    deploy.add_argument("--target", default="deploy")
    deploy.add_argument("--port", type=int, default=7860)
    deploy.add_argument("--image", default="archivist:latest")
    deploy.add_argument("--user", default="ubuntu")
    deploy.add_argument("--workdir", default="/opt/archivist")
    deploy.add_argument("--windows-workdir", default=r"C:\archivist")
    deploy.set_defaults(func=cmd_deploy)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
