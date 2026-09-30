import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "bin" / "coord-review"
FIXTURE = ROOT / "tests" / "fixtures" / "well-shaped.md"
ANSWERS = """1. Deletion alternative: Replace the existing per-row loop with the batch call.
2. Orphans: Remove the per-row upsert helper once its only caller is replaced.
3. Net LOC delta target: +10 to +30
4. Retirement: The old loop and helper retire; growth covers the batch regression test.
"""


def review(tmp_path, analysis=ANSWERS, band="+10 to +30", heading="##"):
    task = FIXTURE.read_text()
    task = task.split("\n## Subtraction analysis\n")[0]
    task = task.replace("scope_budget:\n  net_loc_delta_target: +10 to +30\n", "")
    if band is not None:
        task = task.replace("tags:\n", f"scope_budget:\n  net_loc_delta_target: {band}\ntags:\n")
    if analysis is not None:
        task += f"\n{heading} Subtraction analysis\n\n{analysis}\n"
    path = tmp_path / "task.md"
    path.write_text(task)
    return subprocess.run([sys.executable, str(REVIEW), str(path)], capture_output=True, text=True)


@pytest.mark.parametrize("heading", ["##", "###"])
@pytest.mark.parametrize("marker", ["numbered", "bulleted"])
def test_accepts_recorded_subtraction(tmp_path, heading, marker):
    analysis = ANSWERS
    if marker == "bulleted":
        analysis = "\n".join("- " + line[3:] for line in analysis.splitlines())
    result = review(tmp_path, analysis, heading=heading)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("analysis", [
    None,
    "",
    "_To be filled by shaping._",
    "\n".join(ANSWERS.splitlines()[:3]),
    ANSWERS.replace("The old loop and helper retire; growth covers the batch regression test.", "**TBD**"),
    ANSWERS.replace("4. Retirement: The old loop and helper retire; growth covers the batch regression test.", "4. What gets retired?"),
])
def test_rejects_missing_or_placeholder_answers(tmp_path, analysis):
    result = review(tmp_path, analysis)
    assert result.returncode == 1
    assert "Subtraction analysis must record four" in result.stdout
    assert "Add a `### Subtraction analysis` sub-heading" in result.stdout


@pytest.mark.parametrize("band", [None, "TBD", "+50", "+50 to lots", ""])
def test_rejects_missing_or_malformed_budget(tmp_path, band):
    result = review(tmp_path, band=band)
    assert result.returncode == 1
    assert "net_loc_delta_target must be a numeric band" in result.stdout


@pytest.mark.parametrize("band", ["0 to 0", "-800 to -1200", "'+10 to +30'"])
def test_accepts_supported_budget_bands(tmp_path, band):
    result = review(tmp_path, ANSWERS.replace("+10 to +30", band.strip("'")), band)
    assert result.returncode == 0, result.stdout


def test_accepts_justified_growth_without_forced_retirement(tmp_path):
    analysis = """1. Deletion alternative: None; the requested standalone export has no existing implementation.
2. Orphans: None; existing callers and commands remain in use.
3. Net LOC delta target: +10 to +30
4. Retirement: None; extending the existing report would change its required wire format, so a separate export is necessary.
"""
    result = review(tmp_path, analysis)
    assert result.returncode == 0, result.stdout


def test_keeps_existing_shaping_checks(tmp_path):
    path = tmp_path / "under-shaped.md"
    path.write_text((ROOT / "tests" / "fixtures" / "under-shaped.md").read_text())
    result = subprocess.run([sys.executable, str(REVIEW), str(path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "Plan section" in result.stdout
    assert "Subtraction analysis" in result.stdout


def test_well_shaped_fixture_passes():
    result = subprocess.run([sys.executable, str(REVIEW), str(FIXTURE)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_accepts_subtraction_sub_heading_written_by_set_plan(coord_repo):
    plan = "Replace the per-row loop with the batch call.\n\n### Subtraction analysis\n\n" + ANSWERS
    result = coord_repo.coord("update", "sample-shaping", f"--set-plan={plan}", "--scope-budget-loc=+10 to +30")
    assert result.returncode == 0, result.stderr

    reviewed = subprocess.run(
        [sys.executable, str(REVIEW), str(coord_repo.tasks["shaping"])], capture_output=True, text=True,
    )

    assert "Subtraction analysis" not in reviewed.stdout
    assert "Plan section" not in reviewed.stdout
