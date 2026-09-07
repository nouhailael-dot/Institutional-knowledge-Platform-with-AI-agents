"""GitHub Actions orchestration for the weekly agents maintenance run."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

REQUIRED_ENV = ("DATABASE_URL", "ANTHROPIC_API_KEY", "GHUS_AGENT_CONTACT_EMAIL")
DISCOVERY_SOURCES = ("climate_week", "unga_programme", "unga_guide")


@dataclass(frozen=True)
class StepOutcome:
    name: str
    status: str
    exit_code: int

    @property
    def failed(self) -> bool:
        return self.exit_code != 0 or self.status in {"failed", "missing_digest", "unknown"}


@dataclass(frozen=True)
class WeeklyOutcome:
    discovery: list[StepOutcome]
    downstream: list[StepOutcome]
    summary_path: Path

    @property
    def exit_code(self) -> int:
        return 1 if any(outcome.failed for outcome in [*self.discovery, *self.downstream]) else 0


Runner = Callable[[Sequence[str]], int]


def validate_required_env(env: Mapping[str, str] | None = None) -> None:
    values = env if env is not None else os.environ
    missing = [name for name in REQUIRED_ENV if not values.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {' '.join(missing)}")


def run_weekly(
    *,
    live: bool = False,
    runs_dir: Path | str = Path("agents/runs"),
    runner: Runner | None = None,
) -> WeeklyOutcome:
    command_runner = runner or _run_command
    output_dir = Path(runs_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    live_arg = ["--live"] if live else []

    discovery: list[StepOutcome] = []
    for source in DISCOVERY_SOURCES:
        digest_path = output_dir / f"{source}-digest.md"
        command = [
            sys.executable,
            "-m",
            "agents.discovery.run",
            "--source",
            source,
            "--entity",
            "event",
            *live_arg,
            "--out",
            str(output_dir / f"{source}-audit.csv"),
            "--digest-out",
            str(digest_path),
        ]
        exit_code = int(command_runner(command) or 0)
        status = digest_status(digest_path)
        if status == "missing_digest":
            exit_code = exit_code or 1
        discovery.append(StepOutcome(source, status, exit_code))

    downstream = [
        _run_downstream(
            "enrichment",
            [
                sys.executable,
                "-m",
                "agents.enrichment.run",
                "--entity",
                "actor",
                "--field-set",
                "profile",
                "--limit",
                "50",
                "--deterministic-only",
                "--revisit-missing",
                *live_arg,
            ],
            command_runner,
        ),
        _run_downstream(
            "index_refresh",
            [
                sys.executable,
                "-m",
                "agents.index.refresh",
                "--entity",
                "all",
                "--limit",
                "500",
                *live_arg,
            ],
            command_runner,
        ),
    ]

    summary_path = output_dir / "source-outcomes.md"
    outcome = WeeklyOutcome(discovery=discovery, downstream=downstream, summary_path=summary_path)
    summary_path.write_text(build_summary(outcome), encoding="utf-8", newline="\n")
    return outcome


def digest_status(path: Path) -> str:
    if not path.exists():
        return "missing_digest"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("**Status:**"):
            status = line.removeprefix("**Status:**").strip().lower()
            return status if status in {"succeeded", "attention", "failed"} else "unknown"
    return "unknown"


def build_summary(outcome: WeeklyOutcome) -> str:
    discovery_succeeded = [item.name for item in outcome.discovery if item.status == "succeeded"]
    discovery_attention = [
        item.name for item in outcome.discovery if item.status == "attention" and not item.failed
    ]
    discovery_failed = [_format_failed(item) for item in outcome.discovery if item.failed]
    downstream_succeeded = [item.name for item in outcome.downstream if not item.failed]
    downstream_failed = [_format_failed(item) for item in outcome.downstream if item.failed]
    return "\n".join(
        [
            "### Weekly discovery source outcomes",
            "",
            f"Discovery succeeded: {_format_names(discovery_succeeded)}",
            f"Discovery attention: {_format_names(discovery_attention)}",
            f"Discovery failed: {_format_names(discovery_failed)}",
            f"Downstream succeeded: {_format_names(downstream_succeeded)}",
            f"Downstream failed: {_format_names(downstream_failed)}",
            "",
        ]
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="commit writes; absent means dry-run")
    parser.add_argument("--runs-dir", default="agents/runs")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    validate_required_env()
    outcome = run_weekly(live=args.live, runs_dir=args.runs_dir)
    summary = outcome.summary_path.read_text(encoding="utf-8")
    print(summary, end="")
    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with Path(github_summary).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(summary)
    return outcome.exit_code


def _run_downstream(name: str, command: Sequence[str], runner: Runner) -> StepOutcome:
    exit_code = int(runner(command) or 0)
    status = "succeeded" if exit_code == 0 else "failed"
    return StepOutcome(name, status, exit_code)


def _run_command(command: Sequence[str]) -> int:
    return subprocess.run(command, check=False).returncode


def _format_names(names: Sequence[str]) -> str:
    return ", ".join(names) if names else "none"


def _format_failed(outcome: StepOutcome) -> str:
    return f"{outcome.name}(status={outcome.status},exit={outcome.exit_code})"


if __name__ == "__main__":
    sys.exit(main())
