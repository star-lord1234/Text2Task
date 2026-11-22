#!/usr/bin/env python3
"""Annotate Text2Task candidate JSONL with a configurable LLM provider."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.annotation.llm_annotator import (  # noqa: E402
    AnnotationRunner,
    OllamaProvider,
    OpenAIResponsesProvider,
    PromptBuilder,
    RunnerConfig,
    ThreadContextIndex,
    format_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/candidates/dev.jsonl"))
    parser.add_argument("--provider", choices=("ollama", "openai"), default="ollama")
    parser.add_argument("--model", help="Provider model name; defaults to llama3.1:latest for Ollama")
    parser.add_argument("--base-url", help="Override provider base URL")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Environment variable containing the API key")
    parser.add_argument("--allow-external", action="store_true", help="Explicitly authorize sending redacted email content to an external provider")
    parser.add_argument(
        "--redact-sensitive",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Offset-preserving email/phone/long-ID masking; defaults on externally and off locally",
    )
    parser.add_argument("--context-jsonl", type=Path, action="append", default=[], help="JSONL source for neighboring thread turns; repeatable")
    parser.add_argument("--context-turns", type=int, default=2)
    parser.add_argument("--prompt", type=Path, default=Path("configs/annotation_prompt.md"))
    parser.add_argument("--silver-dir", type=Path, default=Path("data/annotations/silver"))
    parser.add_argument("--failed-dir", type=Path, default=Path("data/annotations/failed"))
    parser.add_argument("--report", type=Path, default=Path("data/reports/llm_annotation_report.json"))
    parser.add_argument("--dry-run", action="store_true", help="Generate prompts locally without provider calls")
    parser.add_argument("--pilot", action="store_true", help="Run at most 20 records")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-bulk", action="store_true", help="Explicitly remove the 20-record pre-review safety gate")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--base-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=60.0)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--max-output-tokens", type=int, default=1536)
    parser.add_argument("--context-window", type=int, default=8192)
    parser.add_argument(
        "--ollama-format",
        choices=("json", "schema"),
        default="json",
        help="Ollama output constraint; JSON is faster, while schema uses full grammar enforcement",
    )
    parser.add_argument("--input-cost-per-million", type=float)
    parser.add_argument("--output-cost-per-million", type=float)
    return parser.parse_args()


def infer_context_path(input_path: Path) -> list[Path]:
    split = input_path.stem
    candidate = Path("data/cleaned") / f"{split}.jsonl"
    return [candidate] if candidate.is_file() else [input_path]


def main() -> None:
    args = parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Input JSONL not found: {args.input}")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.max_attempts < 1:
        raise SystemExit("--max-attempts must be positive")
    limit = 20 if args.pilot or (args.dry_run and args.limit is None) else args.limit
    if args.pilot and args.limit is not None:
        limit = min(20, args.limit)
    if not args.dry_run and not args.allow_bulk and (limit is None or limit > 20):
        raise SystemExit("Pilot review gate: use --pilot/--limit <= 20, or explicitly pass --allow-bulk after pilot review")

    model = args.model or ("llama3.1:latest" if args.provider == "ollama" else None)
    if not args.dry_run and not model:
        raise SystemExit("--model is required for the OpenAI provider")
    external = args.provider == "openai"
    if external and not args.dry_run and not args.allow_external:
        raise SystemExit("External privacy gate: pass --allow-external only after provider permissions and data handling are approved")
    redact_sensitive = args.redact_sensitive if args.redact_sensitive is not None else external

    split_name = args.input.stem
    args.silver_dir.mkdir(parents=True, exist_ok=True)
    args.failed_dir.mkdir(parents=True, exist_ok=True)
    success_path = args.silver_dir / f"{split_name}.jsonl"
    failure_path = args.failed_dir / f"{split_name}.jsonl"
    review_path = args.failed_dir / f"{split_name}.review.jsonl"
    checkpoint_path = args.silver_dir / f"{split_name}.checkpoint.json"
    prompt_dump_path = args.silver_dir / f"{split_name}.dry_run_prompts.jsonl"

    context_paths = args.context_jsonl or infer_context_path(args.input)
    missing_context = [path for path in context_paths if not path.is_file()]
    if missing_context:
        raise SystemExit(f"Context JSONL not found: {missing_context}")
    context_index = ThreadContextIndex.from_jsonl(context_paths)
    prompt_builder = PromptBuilder(args.prompt)

    provider = None
    if not args.dry_run and args.provider == "ollama":
        provider = OllamaProvider(
            model,
            base_url=args.base_url or "http://127.0.0.1:11434",
            timeout=args.timeout,
            format_mode=args.ollama_format,
            max_output_tokens=args.max_output_tokens,
            context_window=args.context_window,
        )
    elif not args.dry_run and args.provider == "openai":
        api_key = os.getenv(args.api_key_env, "")
        if not api_key:
            raise SystemExit(f"API key environment variable is unset: {args.api_key_env}")
        provider = OpenAIResponsesProvider(
            model,
            api_key=api_key,
            base_url=args.base_url or "https://api.openai.com/v1",
            timeout=args.timeout,
            input_cost_per_million=args.input_cost_per_million,
            output_cost_per_million=args.output_cost_per_million,
        )

    runner = AnnotationRunner(
        provider,
        prompt_builder,
        context_index,
        RunnerConfig(
            input_path=args.input,
            success_path=success_path,
            failure_path=failure_path,
            review_path=review_path,
            checkpoint_path=checkpoint_path,
            report_path=args.report,
            prompt_dump_path=prompt_dump_path,
            limit=limit,
            dry_run=args.dry_run,
            max_attempts=args.max_attempts,
            base_delay_seconds=args.base_delay,
            max_delay_seconds=args.max_delay,
            retry_failed=args.retry_failed,
            context_turns=args.context_turns,
            redact_sensitive=redact_sensitive,
        ),
    )
    stats = runner.run()
    print(format_summary(stats))
    if args.dry_run:
        print(f"  Prompt dump: {prompt_dump_path.resolve()}")
    else:
        print(f"  Silver output: {success_path.resolve()}")
        print(f"  Failure output: {failure_path.resolve()}")
        print(f"  Review queue: {review_path.resolve()}")
    print(f"  Report: {args.report.resolve()}")


if __name__ == "__main__":
    main()
