"""CLI entry point for the internal duplicate red-team laboratory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .runner import RedTeamRunner, run_regression


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.duplicate_redteam",
        description=(
            "Internal QA laboratory: generate perceptual variants of known media "
            "and measure false-negative rate of the deduplication pipeline. "
            "NOT for production or public use."
        ),
    )
    p.add_argument(
        "--input", "-i",
        type=Path,
        help="Path to original media (image or video) that already exists on the platform.",
    )
    p.add_argument(
        "--iterations", "-n",
        type=int,
        default=50,
        help="Number of variants to generate (default: 50).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers (currently sequential; reserved for future).",
    )
    p.add_argument(
        "--results-dir",
        type=Path,
        default=Path("tools/duplicate_redteam/results"),
        help="Directory for reports and false-negative fixtures.",
    )
    p.add_argument(
        "--max-transforms",
        type=int,
        default=3,
        help="Max transforms chained per variant.",
    )
    p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Less verbose output.",
    )
    p.add_argument(
        "--regression",
        action="store_true",
        help="Re-run saved false-negative fixtures and report regressions.",
    )
    p.add_argument(
        "--replay-case",
        type=int,
        default=None,
        help="Replay a specific case ID (requires recorded params).",
    )
    p.add_argument(
        "--pipeline-check",
        action="store_true",
        help="Run full MediaDuplicatePipeline once on --input (extract + score, dry-run).",
    )
    p.add_argument(
        "--with-supabase",
        action="store_true",
        help="Enable Supabase candidate lookup (requires SUPABASE_URL + SERVICE_ROLE_KEY). Still dry-run unless --persist.",
    )
    p.add_argument(
        "--persist",
        action="store_true",
        help="Allow writing to vd_media / fingerprints (requires --with-supabase). Creates media row if no --media-id.",
    )
    p.add_argument("--media-id", type=str, default=None, help="vd_media.id for persist (optional; auto-created if omitted)")
    return p



def _run_pipeline_check(args) -> int:
    from .detectors.pipeline import MediaDuplicatePipeline
    store = None
    if args.with_supabase:
        try:
            from .detectors.supabase_store import SupabaseFingerprintStore
            store = SupabaseFingerprintStore(dry_run=not args.persist)
            print("[pipeline] Supabase store connected, dry_run=", store.dry_run)
            print("[pipeline] health:", store.health())
        except Exception as exc:
            print(f"[pipeline] Supabase unavailable: {exc}", file=sys.stderr)
            print("[pipeline] continuing without store")
    pipe = MediaDuplicatePipeline(store=store, dry_run=not args.persist)
    result = pipe.process(
        args.input,
        media_id=args.media_id,
        persist=args.persist,
    )
    import json
    out = result.to_dict()
    # trim large binary fields for display
    fp = out.get("fingerprints") or {}
    if fp.get("tmk_fingerprint"):
        fp["tmk_fingerprint"] = f"<{len(fp['tmk_fingerprint'])} bytes>"
    if fp.get("audio_fingerprint"):
        fp["audio_fingerprint"] = f"<{len(fp['audio_fingerprint'])} bytes>"
    if fp.get("sscd_embedding"):
        fp["sscd_embedding"] = f"<vector dim={len(fp['sscd_embedding'])}>"
    if fp.get("pdq_hashes"):
        fp["pdq_hashes"] = fp["pdq_hashes"][:3] + (["..."] if len(fp["pdq_hashes"]) > 3 else [])
    print(json.dumps(out, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.regression:
        run_regression(args.results_dir)
        return 0

    if args.input is None:
        parser.error("--input is required unless --regression is used")

    if not args.input.exists():
        print(f"Error: input not found: {args.input}", file=sys.stderr)
        return 1

    if args.pipeline_check:
        return _run_pipeline_check(args)

    runner = RedTeamRunner(
        input_path=args.input,
        iterations=args.iterations,
        seed=args.seed,
        workers=args.workers,
        results_dir=args.results_dir,
        verbose=not args.quiet,
        max_transforms=args.max_transforms,
    )
    try:
        runner.run()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
