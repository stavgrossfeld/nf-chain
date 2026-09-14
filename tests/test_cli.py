from __future__ import annotations

import subprocess

import pytest

from nfchain import cli


def _run_cmd(monkeypatch, argv):
    """Parse argv through main() and capture the argv that cmd_run would exec."""
    captured = {}

    def fake_build(args):
        return 0

    def fake_which(_):
        return "/usr/bin/nextflow"

    def fake_call(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return 0

    monkeypatch.setattr(cli, "cmd_build", fake_build)
    monkeypatch.setattr(cli.shutil, "which", fake_which)
    monkeypatch.setattr(cli.subprocess, "call", fake_call)
    assert cli.main(argv) == 0
    return captured["cmd"]


def test_passthrough_after_dashdash_reaches_run_sh(monkeypatch):
    cmd = _run_cmd(monkeypatch, ["run", "f.flow", "--profile", "docker", "--", "-with-tower"])
    assert cmd[0] == "bash"
    assert cmd[1].endswith("run.sh")
    assert cmd[2] == "docker"  # profile parsed, not swallowed
    assert cmd[3:] == ["-with-tower"]


def test_multiple_forwarded_flags(monkeypatch):
    cmd = _run_cmd(
        monkeypatch, ["run", "f.flow", "--profile", "test,docker", "--", "-with-tower", "-with-report"]
    )
    assert cmd[2] == "test,docker"
    assert cmd[3:] == ["-with-tower", "-with-report"]


def test_no_passthrough_is_clean(monkeypatch):
    cmd = _run_cmd(monkeypatch, ["run", "f.flow", "--profile", "docker"])
    assert cmd == ["bash", cmd[1], "docker"]


def test_passthrough_forwarded_to_nested_main_nf(monkeypatch):
    cmd = _run_cmd(monkeypatch, ["run", "f.flow", "--nested", "--", "-with-tower"])
    assert cmd[:3] == ["nextflow", "run", cmd[2]]
    assert cmd[2].endswith("main.nf")
    assert "-with-tower" in cmd


def test_profile_before_dashdash_is_not_treated_as_passthrough(monkeypatch):
    # regression: argparse REMAINDER used to swallow --profile into the passthrough
    cmd = _run_cmd(monkeypatch, ["run", "f.flow", "--profile", "singularity", "--", "-resume"])
    assert cmd[2] == "singularity"
    assert cmd[3:] == ["-resume"]


def test_init_creates_valid_flow(tmp_path):
    target = tmp_path / "custom.flow"
    assert cli.main(["init", str(target)]) == 0
    assert target.exists()
    content = target.read_text()
    assert "from nf-core import sratools" in content
    assert "from nf-core import rnaseq" in content

    # Should fail if file exists and no --force
    assert cli.main(["init", str(target)]) == 1

    # Overwrites with --force
    assert cli.main(["init", str(target), "--force"]) == 0


def test_help_displays_flow_guide(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr().out
    assert "HOW TO WRITE A .FLOW FILE:" in captured
    assert "from nf-core import" in captured
    assert "Auto-Wiring:" in captured


def test_run_missing_bash_raises_abort(monkeypatch, tmp_path):
    flow = tmp_path / "test.flow"
    flow.write_text("from nf-core import demo\nqc = demo()\n")

    monkeypatch.setattr(cli, "cmd_build", lambda args: 0)
    monkeypatch.setattr(cli.shutil, "which", lambda cmd: "/usr/bin/nextflow" if cmd == "nextflow" else None)

    # Missing bash without --nested aborts
    assert cli.main(["run", str(flow)]) == 1


def test_results_dir_forwarded(monkeypatch):
    captured = {}

    def fake_build(args):
        return 0

    def fake_which(_):
        return "/usr/bin/nextflow"

    def fake_call(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return 0

    monkeypatch.setattr(cli, "cmd_build", fake_build)
    monkeypatch.setattr(cli.shutil, "which", fake_which)
    monkeypatch.setattr(cli.subprocess, "call", fake_call)

    # In default sequential mode, NFCHAIN_RESULTS is set in env
    assert cli.main(["run", "f.flow", "--results", "s3://my-bucket/runs"]) == 0
    assert captured["env"]["NFCHAIN_RESULTS"] == "s3://my-bucket/runs"

    # In nested mode, --outdir is added to nextflow command
    assert cli.main(["run", "f.flow", "--nested", "--results", "s3://my-bucket/runs"]) == 0
    assert "--outdir" in captured["cmd"]
    assert "s3://my-bucket/runs" in captured["cmd"]


def test_run_stub_run_defaults_to_temp_and_nested(monkeypatch):
    captured = {}

    def fake_build(args):
        captured["outdir"] = str(args.outdir)
        captured["temp"] = getattr(args, "temp", False)
        return 0

    def fake_which(_):
        return "/usr/bin/nextflow"

    def fake_call(cmd, **kwargs):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(cli, "cmd_build", fake_build)
    monkeypatch.setattr(cli.shutil, "which", fake_which)
    monkeypatch.setattr(cli.subprocess, "call", fake_call)

    assert cli.main(["run", "f.flow", "--stub-run"]) == 0
    assert "nfchain_" in captured["outdir"]
    assert captured["temp"] is True
    assert captured["cmd"][0] == "nextflow"
    assert captured["cmd"][1] == "run"
    assert "-stub-run" in captured["cmd"]


def test_run_temp_flag_uses_ephemeral_dir(monkeypatch):
    captured = {}

    def fake_build(args):
        captured["outdir"] = str(args.outdir)
        captured["temp"] = getattr(args, "temp", False)
        return 0

    def fake_which(_):
        return "/usr/bin/nextflow"

    def fake_call(cmd, **kwargs):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(cli, "cmd_build", fake_build)
    monkeypatch.setattr(cli.shutil, "which", fake_which)
    monkeypatch.setattr(cli.subprocess, "call", fake_call)

    assert cli.main(["run", "f.flow", "--temp"]) == 0
    assert "nfchain_" in captured["outdir"]
    assert captured["temp"] is True


def test_run_work_dir_and_report_flags(monkeypatch):
    captured = {}

    def fake_build(args):
        return 0

    def fake_which(_):
        return "/usr/bin/nextflow"

    def fake_call(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return 0

    monkeypatch.setattr(cli, "cmd_build", fake_build)
    monkeypatch.setattr(cli.shutil, "which", fake_which)
    monkeypatch.setattr(cli.subprocess, "call", fake_call)

    # Sequential mode
    assert cli.main(["run", "f.flow", "-w", "/scratch/work", "--report"]) == 0
    assert captured["env"]["NFCHAIN_WORKDIR"] == "/scratch/work"
    assert "-with-report" in captured["cmd"]
    assert "-with-timeline" in captured["cmd"]

    # Nested mode
    assert cli.main(["run", "f.flow", "--nested", "-w", "/scratch/work", "--report"]) == 0
    assert "-work-dir" in captured["cmd"]
    assert "/scratch/work" in captured["cmd"]
    assert "-with-report" in captured["cmd"]


def test_preview_subcommand_invokes_preview_sh(monkeypatch):
    captured = {}

    def fake_build(args):
        return 0

    def fake_which(_):
        return "/usr/bin/nextflow"

    def fake_call(cmd, **kwargs):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(cli, "cmd_build", fake_build)
    monkeypatch.setattr(cli.shutil, "which", fake_which)
    monkeypatch.setattr(cli.subprocess, "call", fake_call)

    assert cli.main(["preview", "f.flow"]) == 0
    assert captured["cmd"][0] == "bash"
    assert captured["cmd"][1].endswith("preview.sh")
    assert captured["cmd"][2] == "test,docker"


