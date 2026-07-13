import os
import shlex
import subprocess
import textwrap
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "bin" / "coord-verify-artifacts"


def write_task(root, task_id, profile, scope):
    (root / "tasks").mkdir(exist_ok=True)
    (root / "tasks" / f"{task_id}.md").write_text(
        textwrap.dedent(f"""\
        ---
        id: {task_id}
        task: Verify artifact fixture
        status: pending
        assigned: codex
        complexity: simple
        kind: code-fix
        reasoning_effort: medium
        verify_profile: {profile}
        scope:
          - {scope}
        round: 1
        ---
        ## Scope notes

        - [ ] **S1: Verify artifacts**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Verify the scoped artifact.

        ## Plan
        Verify the scoped artifact.

        ## Acceptance test
        Artifact verifier passes.
        """),
        encoding="utf-8",
    )


def fake_vnu(root, rc):
    fakebin = root / "fakebin"
    fakebin.mkdir()
    args_file = root / "vnu-args.txt"
    (fakebin / "vnu").write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(args_file))}\n"
        f"exit {rc}\n",
        encoding="utf-8",
    )
    (fakebin / "vnu").chmod(0o755)
    return fakebin


def run_verify(root, task_id, fakebin):
    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:{env['PATH']}"
    return subprocess.run(
        ["python3", str(VERIFY), task_id],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )


def test_html5_profile_uses_vnu_for_valid_html(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><html><title>ok</title></html>\n", encoding="utf-8")
    write_task(tmp_path, "html-valid", "html5", "index.html")
    fakebin = fake_vnu(tmp_path, 0)

    result = run_verify(tmp_path, "html-valid", fakebin)

    assert result.returncode == 0, result.stderr
    assert "artifact verification passed: html5" in result.stdout
    assert "index.html" in (tmp_path / "vnu-args.txt").read_text(encoding="utf-8")


def test_html5_profile_fails_when_vnu_fails(tmp_path):
    (tmp_path / "bad.html").write_text("<!doctype html><html><p>bad</html>\n", encoding="utf-8")
    write_task(tmp_path, "html-invalid", "html5", "bad.html")
    fakebin = fake_vnu(tmp_path, 1)

    result = run_verify(tmp_path, "html-invalid", fakebin)

    assert result.returncode == 3
    assert "vnu failed" in result.stdout


def write_pptx(path, text, slides=1):
    with zipfile.ZipFile(path, "w") as zf:
        for idx in range(1, slides + 1):
            zf.writestr(
                f"ppt/slides/slide{idx}.xml",
                f"<p:sld><p:cSld><a:t>{text}</a:t></p:cSld></p:sld>",
            )


def test_pptx_profile_flags_large_text_loss_against_baseline(tmp_path):
    pptx = tmp_path / "deck.pptx"
    write_pptx(pptx, "important text " * 40, slides=2)
    write_task(tmp_path, "pptx-loss", "pptx-html", "deck.pptx")
    fakebin = fake_vnu(tmp_path, 0)

    capture = subprocess.run(
        ["python3", str(VERIFY), "pptx-loss", "--capture-baseline"],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert capture.returncode == 0, capture.stderr

    write_pptx(pptx, "tiny", slides=2)
    result = run_verify(tmp_path, "pptx-loss", fakebin)

    assert result.returncode == 3
    assert "extracted text dropped" in result.stdout
