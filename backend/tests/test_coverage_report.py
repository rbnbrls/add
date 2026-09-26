"""Guards the published coverage contract.

The darkfactory quality lane reads a repository's coverage from a *committed*,
machine-readable report — `coverage.xml` at the repository root, the first path
it probes — and reports the rung as `enforced` with the number `unavailable`
(`capability:coverage_not_published`) while that file is absent. That was this
repository's state on 2026-09-26: CI ran `pytest --cov=app --cov-fail-under=75`
and uploaded `backend/coverage.xml` as an artifact, so coverage was enforced but
published nowhere a reader could reach it.

Four invariants keep the rung at `measured`:

1. `coverage.xml` exists at the repository root and parses to a line percentage,
   and git keeps tracking it — an ignore rule that swallows the published report
   would silently un-publish it;
2. the report is machine-independent: no timestamp, no absolute checkout path,
   and a re-run of the normaliser on it rewrites identical bytes, which is what
   makes the CI comparison meaningful instead of always-red;
3. the CI job measures the tree, publishes into the working tree and refuses to
   pass while the committed report no longer describes it — so the report cannot
   rot;
4. publishing needs no write access: the report travels through the ordinary
   merge, and CI neither pushes to the repository nor widens the workflow token.
"""

from __future__ import annotations

import configparser
import importlib.util
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "coverage_report.py"
REPORT = ROOT / "coverage.xml"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy.yml"
GITIGNORE = ROOT / ".gitignore"
COVERAGERC = ROOT / "backend" / ".coveragerc"
#: The report `pytest --cov=app --cov-report=xml` writes, run from `backend/`.
PER_RUN_REPORT = ROOT / "backend" / "coverage.xml"

VALID_REPORT = """<?xml version="1.0" ?>
<coverage version="7.15.2" timestamp="1790438298516" lines-valid="4" lines-covered="3"
\tline-rate="0.75" branches-valid="0" branches-covered="0" branch-rate="0"
\tcomplexity="0">
\t<sources>
\t\t<source>app</source>
\t</sources>
\t<packages>
\t\t<package name="." line-rate="0.75" branch-rate="0" complexity="0">
\t\t\t<classes>
\t\t\t\t<class name="a.py" filename="app/a.py" complexity="0" line-rate="0.75" branch-rate="0">
\t\t\t\t\t<methods />
\t\t\t\t\t<lines>
\t\t\t\t\t\t<line number="1" hits="1" />
\t\t\t\t\t\t<line number="2" hits="0" />
\t\t\t\t\t\t<line number="3" hits="1" />
\t\t\t\t\t\t<line number="4" hits="1" />
\t\t\t\t\t</lines>
\t\t\t\t</class>
\t\t\t</classes>
\t\t</package>
\t</packages>
</coverage>
"""


@lru_cache(maxsize=1)
def _report_module() -> Any:
    spec = importlib.util.spec_from_file_location("_coverage_report", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    # A dynamically loaded module must be registered before execution, or
    # `dataclasses` cannot resolve the module of the classes it decorates.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_yaml(path: Path) -> Any:
    data = yaml.safe_load(path.read_text())
    if isinstance(data, dict) and True in data:
        # PyYAML reads the `on:` key as the boolean True.
        data = {("on" if key is True else key): value for key, value in data.items()}
    return data


@lru_cache(maxsize=1)
def _workflow() -> dict[str, Any]:
    return _load_yaml(WORKFLOW)


@lru_cache(maxsize=1)
def _steps() -> list[dict[str, Any]]:
    return _workflow()["jobs"]["build-and-test"]["steps"]


def _step_named(fragment: str) -> dict[str, Any]:
    """The single CI step whose ``name`` contains ``fragment``.

    Steps are addressed by name, not by a needle in their ``run`` text: the
    staleness step legitimately *prints* the republish commands, so a
    content-based lookup would match it as well and stop distinguishing the step
    that measures from the step that compares.
    """
    matches = [step for step in _steps() if fragment.lower() in str(step.get("name", "")).lower()]
    assert len(matches) == 1, f"expected exactly one CI step named like {fragment!r}, got {len(matches)}"
    return matches[0]


def _step_names() -> list[str]:
    return [str(step.get("name", "")) for step in _steps()]


# ---------------------------------------------------------------------------
# Invariant 1 — the published report exists, parses, and stays tracked
# ---------------------------------------------------------------------------


def test_report_is_committed_at_the_path_the_lane_reads_first() -> None:
    assert REPORT.is_file(), (
        "coverage.xml must be committed at the repository root: it is the first path the "
        "quality lane probes, and without it the coverage rung stays 'enforced' with reason "
        "capability:coverage_not_published"
    )


def test_committed_report_parses_to_a_percentage() -> None:
    summary = _report_module().parse_report(REPORT)

    assert 0.0 < summary.line_rate <= 1.0
    assert summary.lines_valid > 0
    assert summary.lines_covered <= summary.lines_valid
    assert 0.0 < summary.line_percent <= 100.0


def test_published_line_coverage_is_at_or_above_the_ci_floor() -> None:
    """The floor CI enforces must be satisfiable by the published number."""
    run = str(_step_named("Run backend tests with coverage")["run"])
    floor = int(run.split("--cov-fail-under=")[1].split()[0])
    summary = _report_module().parse_report(REPORT)

    assert floor <= summary.line_percent, (
        f"--cov-fail-under={floor} sits above the published line coverage "
        f"{summary.line_percent}% — CI would fail and publish nothing"
    )


def test_the_published_report_is_not_ignored_by_git() -> None:
    """An ignore rule that swallows `coverage.xml` would un-publish it silently."""
    rules = [line.strip() for line in GITIGNORE.read_text().splitlines()]
    patterns = [rule for rule in rules if rule and not rule.startswith("#")]

    assert "coverage.xml" not in patterns, (
        "a bare `coverage.xml` rule ignores the published report at the repository root too"
    )
    assert "backend/coverage.xml" in patterns, "the per-run report stays ignored"


# ---------------------------------------------------------------------------
# Invariant 2 — the report is machine-independent, and the reader never invents
# ---------------------------------------------------------------------------


def test_committed_report_carries_no_volatile_timestamp() -> None:
    assert "timestamp=" not in REPORT.read_text(), (
        "a timestamp makes every run differ from the committed report, so the staleness check "
        "would be red on every push without anything having changed"
    )


def test_committed_report_carries_no_absolute_checkout_path() -> None:
    text = REPORT.read_text()

    assert f"<source>{ROOT.name}" not in text
    assert "/home/" not in text and "/Users/" not in text, (
        "the report must describe the measurement, not where it ran: `relative_files` in "
        "backend/.coveragerc keeps <sources> repository-relative"
    )


def test_relative_files_is_enabled_for_coverage() -> None:
    config = configparser.ConfigParser()
    config.read(COVERAGERC)

    assert config.getboolean("run", "relative_files") is True, (
        "without relative_files coverage writes the absolute checkout path into <sources>, so a "
        "report committed from one machine can never match a run on another"
    )


def test_committed_report_is_already_normalised(tmp_path: Path) -> None:
    """Normalising a copy of the committed report must not change its bytes."""
    path = tmp_path / "coverage.xml"
    shutil.copyfile(REPORT, path)
    before = path.read_bytes()

    _report_module().normalise_report(path)

    assert path.read_bytes() == before
    assert before.endswith(b"\n")


def test_parse_rejects_a_report_without_a_rate(tmp_path: Path) -> None:
    path = tmp_path / "coverage.xml"
    path.write_text("<?xml version='1.0'?><coverage version='7' />")

    with pytest.raises(ValueError, match="line-rate"):
        _report_module().parse_report(path)


def test_parse_rejects_a_non_cobertura_document(tmp_path: Path) -> None:
    path = tmp_path / "coverage.xml"
    path.write_text("<?xml version='1.0'?><html><body/></html>")

    with pytest.raises(ValueError, match="coverage"):
        _report_module().parse_report(path)


def test_parse_rejects_unparsable_input(tmp_path: Path) -> None:
    path = tmp_path / "coverage.xml"
    path.write_text("not xml at all")

    with pytest.raises(ValueError, match="not readable"):
        _report_module().parse_report(path)


def test_missing_report_is_an_error_not_zero(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _report_module().parse_report(tmp_path / "absent.xml")


def test_normalise_drops_only_the_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "coverage.xml"
    path.write_text(VALID_REPORT)

    summary = _report_module().normalise_report(path)

    assert summary.line_percent == 75.0
    assert summary.lines_covered == 3
    assert summary.lines_valid == 4
    text = path.read_text()
    assert "timestamp" not in text
    assert 'line-rate="0.75"' in text
    assert 'filename="app/a.py"' in text


def test_normalise_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "coverage.xml"
    path.write_text(VALID_REPORT)

    _report_module().normalise_report(path)
    once = path.read_bytes()
    _report_module().normalise_report(path)

    assert path.read_bytes() == once


def test_normalise_publishes_to_the_requested_path(tmp_path: Path) -> None:
    """CI publishes `backend/coverage.xml` to the repository root."""
    source = tmp_path / "backend" / "coverage.xml"
    source.parent.mkdir()
    source.write_text(VALID_REPORT)
    target = tmp_path / "coverage.xml"

    summary = _report_module().normalise_report(source, target)

    assert target.is_file()
    assert summary.line_percent == 75.0
    assert source.read_text() == VALID_REPORT, "the per-run report is left for the artifact step"


def test_main_reports_the_percentage_on_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    path = tmp_path / "coverage.xml"
    shutil.copyfile(REPORT, path)

    assert _report_module().main([str(path), "--check", "--summary"]) == 0
    assert "coverage: " in capsys.readouterr().out


def test_main_fails_loudly_on_an_unreadable_report(tmp_path: Path) -> None:
    path = tmp_path / "coverage.xml"
    path.write_text("<html/>")

    assert _report_module().main([str(path), "--check"]) == 1


def test_publish_defaults_are_the_paths_the_repository_uses() -> None:
    module = _report_module()

    assert module.DEFAULT_INPUT == "backend/coverage.xml"
    assert module.DEFAULT_OUTPUT == "coverage.xml"
    assert not Path(module.DEFAULT_OUTPUT).is_absolute(), (
        "the published path is repository-relative, so a local run and CI write the same file"
    )


# ---------------------------------------------------------------------------
# Invariant 3 — CI measures the tree, publishes, and refuses a stale report
# ---------------------------------------------------------------------------


def test_ci_runs_the_suite_under_coverage_with_a_floor() -> None:
    step = _step_named("Run backend tests with coverage")

    assert "--cov=app" in step["run"]
    assert "--cov-report=xml" in step["run"], "the report must be written, not only printed"
    assert "--cov-report=term-missing" in step["run"], "the number must stay visible in the log"
    assert "--cov-fail-under=75" in step["run"], "a run with no floor enforces nothing"


def test_ci_measures_the_file_the_publisher_reads() -> None:
    """`pytest --cov-report=xml` with no path writes `coverage.xml` in its cwd."""
    step = _step_named("Run backend tests with coverage")
    module = _report_module()

    assert step.get("working-directory") == "backend"
    assert "--cov-report=xml:" not in str(step["run"]), (
        "an explicit report path here would not be the file the publisher reads"
    )
    assert module.DEFAULT_INPUT == str(PER_RUN_REPORT.relative_to(ROOT))


def test_ci_publishes_the_report_and_summarises_it() -> None:
    run = str(_step_named("Publish the coverage report")["run"])

    assert "coverage_report.py" in run
    assert "$GITHUB_STEP_SUMMARY" in run, "the line total belongs in the job summary"
    assert "PIPESTATUS" in run, "a failed publish must not be hidden by the pipeline"


def test_ci_fails_when_the_committed_report_is_stale() -> None:
    """The committed report is evidence only while it describes this tree."""
    run = str(_step_named("committed report must match")["run"])

    assert "git diff --exit-code -- coverage.xml" in run
    assert "exit 1" in run, "a stale report must fail the job, not warn"
    assert "pytest --cov" in run, "the failure must say how to republish it"


def test_ci_compares_the_report_after_it_measures_it() -> None:
    order = _step_names()

    measured = order.index(_step_named("Run backend tests with coverage")["name"])
    published = order.index(_step_named("Publish the coverage report")["name"])
    compared = order.index(_step_named("committed report must match")["name"])

    assert measured < published < compared


def test_ci_uploads_the_published_report_as_an_artifact() -> None:
    uploads = [
        step for step in _steps() if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]

    assert len(uploads) == 1
    assert uploads[0]["with"]["path"] == "coverage.xml"
    assert uploads[0]["with"]["if-no-files-found"] == "error", "a missing report is a failure"


def test_publishing_needs_no_write_access_in_ci() -> None:
    """The report reaches `main` through the merge, not through a push from CI.

    Committing it from the workflow would need `contents: write` on the workflow
    token — a privilege change a human has to release — and would make CI a
    second writer of a file the merge already carries.
    """
    assert _workflow()["permissions"] == {"contents": "read"}

    text = WORKFLOW.read_text()
    assert "contents: write" not in text
    for step in _steps():
        run = step.get("run")
        if isinstance(run, str):
            assert "git push" not in run, "CI must not push to the repository"


# ---------------------------------------------------------------------------
# Invariant 4 — the report is verified before it lands, not after
# ---------------------------------------------------------------------------


def test_ci_runs_on_pull_requests() -> None:
    """An unreviewed report can only be proven stale after it is already on main."""
    triggers = _workflow()["on"]

    assert "pull_request" in triggers, (
        "without a pull-request trigger the branch carries no checks at all, so the committed "
        "report cannot be verified before the merge"
    )


def test_pull_request_runs_do_not_deploy() -> None:
    jobs = _workflow()["jobs"]

    for name in ("deploy-test", "deploy-production"):
        assert "refs/heads/main" in str(jobs[name]["if"]), (
            f"{name} must stay main-only: a pull request builds and tests, nothing more"
        )
