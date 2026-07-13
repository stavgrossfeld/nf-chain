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

    def fake_call(cmd):
        captured["cmd"] = cmd
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
