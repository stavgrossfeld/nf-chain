"""nfchain — command line interface."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import codegen, dag, dsl, graph, registry, schema, stubgen
from .cache import FetchError

BUILD_DIR = "build_nf"


class Abort(RuntimeError):
    pass


def _rel(path: Path, root: Path) -> str:
    """Path relative to root when possible, else the path as given."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _load(flow_path: Path, refresh: bool) -> tuple[graph.Chain, Path]:
    if not flow_path.exists():
        raise Abort(f"no such flow file: {flow_path}")
    root = Path.cwd()
    flow = dsl.parse_file(flow_path)
    if not flow.steps:
        raise Abort(f"{flow_path}: no pipeline steps found")
    return graph.resolve(flow, root, refresh=refresh), root


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_sync(args) -> int:
    chain, root = _load(args.flow, args.refresh)
    written = stubgen.sync(chain, root, build_dir=args.outdir)
    print(f"synced {len(chain.steps)} pipeline(s) from nf-core:")
    for step in chain.steps:
        n_req = len(step.sch.required)
        print(f"  {step.ref.full_name}@{step.ref.revision}  ({n_req} required params)")
    for p in written:
        print(f"  → {_rel(p, root)}")
    return 0


def cmd_explain(args) -> int:
    chain, _ = _load(args.flow, args.refresh)
    for step in chain.steps:
        print(f"\n\033[1m{step.var}\033[0m  {step.ref.full_name}@{step.ref.revision}")
        if step.ref.description:
            print(f"      {step.ref.description}")
        if step.accession_input:
            print(f"      accessions: {', '.join(step.accession_input)}")
        for wire in sorted(step.wires, key=lambda w: w.param):
            tag = " (auto)" if wire.auto else ""
            print(
                f"      {wire.param} ← {wire.source_step}.{wire.artifact.name}"
                f"  [{wire.artifact.kind}]{tag}"
            )
        for key, value in sorted(step.params.items()):
            tag = " (auto)" if key in step.auto_params else ""
            print(f"      {key} = {value!r}{tag}")
    print()
    return 0


def cmd_dag(args) -> int:
    chain, root = _load(args.flow, args.refresh)
    out = dag.render(chain, args.format)
    if args.output:
        Path(args.output).write_text(out)
        print(f"wrote {args.format} dag → {args.output}")
    else:
        print(out, end="")
    return 0


def cmd_build(args) -> int:
    chain, root = _load(args.flow, args.refresh)
    outdir = root / args.outdir
    stubgen.sync(chain, root, build_dir=args.outdir)
    written = codegen.write(chain, outdir)
    print(f"built {len(chain.steps)}-step chain → {args.outdir}/")
    for p in written:
        print(f"  {_rel(p, root)}")
    print(f"\nrun it (live per-task output):  {args.outdir}/run.sh docker")
    print(f"or Nextflow-managed DAG:        nextflow run {args.outdir}/main.nf -profile docker")
    return 0


STARTER_FLOW = '''\
"""Pipeline chain definition.

Run this with:
    nfchain explain {flow_name}
    nfchain build   {flow_name}
    nfchain run     {flow_name} --profile docker
"""

from nf-core import sratools
from nf-core import rnaseq

# Step 1: Fetch raw reads and build samplesheet
# 'sratools' is an alias for nf-core/fetchngs; 'ids' is an alias for 'input'
sra = sratools(
    ids=["SRR6357070", "SRR6357071"],
    download_method="sratools",
)

# Step 2: RNA quantification
# 'input' is wired to sra.samplesheet (or auto-wired if omitted)
rna = rnaseq(
    input=sra.samplesheet,
    genome="R64-1-1",
    rev="3.14.0",
)
'''


def cmd_init(args) -> int:
    target = args.flow
    if target.exists() and not args.force:
        raise Abort(f"file '{target}' already exists (use --force to overwrite)")
    target.write_text(STARTER_FLOW.format(flow_name=target.name))
    print(f"created starter flow file → {target}")
    print(f"\nnext steps:")
    print(f"  nfchain sync    {target}   # download schemas & setup VSCode stubs")
    print(f"  nfchain explain {target}   # inspect resolved arguments and wiring")
    print(f"  nfchain dag     {target}   # visualize pipeline DAG (mermaid)")
    print(f"  nfchain build   {target}   # compile into build_nf/ Nextflow project")
    return 0


def cmd_run(args) -> int:
    rc = cmd_build(args)
    if rc:
        return rc
    if shutil.which("nextflow") is None:
        raise Abort(
            "nextflow is not on PATH — install it (https://nextflow.io) or run "
            f"`{args.outdir}/run.sh` on a machine that has it"
        )
    # Args after `--` are forwarded to the nextflow run(s):
    # e.g. `nf-chain run flow --profile docker -- -with-tower`.
    extra = args.nf_extra
    if any(a in ("-profile", "--profile") for a in extra):
        raise Abort(
            "set the profile with nf-chain's `--profile ...` before `--`, "
            "not as a forwarded flag"
        )
    env = dict(os.environ)
    if getattr(args, "results_dir", None):
        res = str(args.results_dir)
        env["NFCHAIN_RESULTS"] = res
        if res.startswith("s3://") or "AWS_PROFILE" in env:
            if "AWS_ACCESS_KEY_ID" not in env and shutil.which("aws"):
                try:
                    out = subprocess.check_output(
                        ["aws", "configure", "export-credentials", "--format", "env"],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    )
                    for line in out.splitlines():
                        if line.startswith("export "):
                            k, v = line[7:].split("=", 1)
                            env[k] = v.strip('"\'')
                except Exception:
                    pass
            if "AWS_DEFAULT_REGION" not in env and "AWS_REGION" not in env and shutil.which("aws"):
                try:
                    reg = subprocess.check_output(
                        ["aws", "configure", "get", "region"],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    ).strip()
                    if reg:
                        env["AWS_DEFAULT_REGION"] = reg
                except Exception:
                    pass

    if args.nested:
        # One driver process per pipeline; nested task output is hidden.
        cmd = ["nextflow", "run", f"{args.outdir}/main.nf", "-profile", args.profile]
        if getattr(args, "results_dir", None):
            cmd += ["--outdir", str(args.results_dir)]
        if args.resume:
            cmd.append("-resume")
        cmd += extra
    else:
        # Sequential: each pipeline runs top-level, so every task streams live.
        if shutil.which("bash") is None:
            raise Abort(
                "bash was not found on PATH. On Windows or environments without bash, "
                "run with `nfchain run --nested` to launch the Nextflow-managed DAG directly, "
                f"or run `{args.outdir}/run.sh` in WSL or Git Bash."
            )
        cmd = ["bash", f"{args.outdir}/run.sh", args.profile, *extra]
    print(f"\n$ {' '.join(cmd)}\n")
    return subprocess.call(cmd, env=env)


def cmd_stubs(args) -> int:
    """Stub-run each pipeline on its own to list its individual tasks, kept light."""
    rc = cmd_build(args)
    if rc:
        return rc
    if shutil.which("nextflow") is None:
        raise Abort(f"nextflow is not on PATH — run `{args.outdir}/stubs.sh` where it is")
    if shutil.which("bash") is None:
        raise Abort(
            "bash was not found on PATH — run in WSL / Git Bash, or execute Nextflow directly."
        )
    cmd = ["bash", f"{args.outdir}/stubs.sh", args.profile]
    print(f"\n$ {' '.join(cmd)}\n")
    return subprocess.call(cmd)


def cmd_watch(args) -> int:
    """Re-sync stubs whenever the flow file changes: 'on the fly' in VSCode."""
    last: float | None = None
    print(f"watching {args.flow} (ctrl-c to stop)")
    try:
        while True:
            if args.flow.exists():
                mtime = args.flow.stat().st_mtime
                if mtime != last:
                    last = mtime
                    try:
                        chain, root = _load(args.flow, refresh=False)
                        stubgen.sync(chain, root, build_dir=args.outdir)
                        names = " → ".join(s.ref.full_name for s in chain.steps)
                        print(f"\033[32m✓\033[0m {time.strftime('%H:%M:%S')}  {names}")
                    except (Abort, dsl.DslError, graph.ChainError, FetchError) as e:
                        print(f"\033[31m✗\033[0m {time.strftime('%H:%M:%S')}  {e}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def cmd_ls(args) -> int:
    reg = registry.load_registry(Path.cwd(), refresh=args.refresh)
    rows = sorted(reg.values(), key=lambda w: w["name"])
    if args.query:
        from .contracts import ALIASES

        q = args.query.lower()
        # An import name a user might type (`sra`) resolves through an alias to
        # the pipeline that actually runs (`fetchngs`), so match those too.
        alias_hits = {tgt for name, tgt in ALIASES.items() if q in name}
        rows = [
            w
            for w in rows
            if q in w["name"] or q in (w.get("description") or "").lower() or w["name"] in alias_hits
        ]
    for wf in rows:
        desc = (wf.get("description") or "").split("\n")[0][:70]
        alias = " ".join(sorted(n for n, t in ALIASES.items() if t == wf["name"])) if args.query else ""
        tag = f"  \033[2m(alias: {alias})\033[0m" if alias else ""
        print(f"  {wf['name']:<24} {desc}{tag}")
    print(f"\n{len(rows)} pipeline(s)")
    return 0


def cmd_show(args) -> int:
    from . import contracts

    root = Path.cwd()
    ref = registry.resolve(args.pipeline, root, revision=args.rev, refresh=args.refresh)
    sch = schema.load(ref, root, refresh=args.refresh)
    print(f"\n\033[1m{ref.full_name}@{ref.revision}\033[0m\n{sch.description}")

    # INPUTS / params — read live from the pipeline's nextflow_schema.json.
    print("\n\033[1mINPUTS\033[0m (from nextflow_schema.json)")
    for p in sch.user_params():
        if not args.all and not p.required:
            continue
        mark = "\033[31m*\033[0m" if p.required else " "
        enum = f"  {{{'|'.join(p.enum)}}}" if p.enum else ""
        kind = f" \033[2m[{p.fmt}]\033[0m" if p.is_path else ""
        print(f" {mark} {p.name:<26} {p.type}{enum}{kind}")
        if p.description:
            print(f"     {p.description[:90]}")
    if not args.all:
        print("   \033[2m(required only; --all for every param)\033[0m")

    # OUTPUTS — not in any schema; from nf-chain's curated EMITS table.
    arts = contracts.emits(ref.name)
    print("\n\033[1mOUTPUTS\033[0m (curated — schemas don't describe outputs)")
    if arts:
        for a in arts:
            print(f"   {a.name:<26} \033[2m[{a.kind}]\033[0m  outdir/{a.path}")
    else:
        print("   \033[2mnone curated yet — add to EMITS in contracts.py to chain from it\033[0m")
    print()
    return 0


# ---------------------------------------------------------------------------


FLOW_HELP_EPILOG = """\
HOW TO WRITE A .FLOW FILE:
---------------------------
Flow files use clean Python syntax (parsed with ast, never executed).

1. Imports:
   Import any pipeline from nf-core. Both 'nf-core' and 'nf_core' are accepted:
       from nf-core import fetchngs
       from nf-core import rnaseq
   (Friendly aliases are supported: e.g. 'from nf-core import sratools' resolves to 'fetchngs')

2. Step Assignments:
   Assign pipeline calls to variables. Arguments must be keyword literals:
       sra = fetchngs(ids=["SRR6357070", "SRR6357071"], download_method="sratools")

3. Output Wiring:
   Wire an upstream output to a downstream input using attribute references:
       rna = rnaseq(input=sra.samplesheet, genome="R64-1-1")

4. Auto-Wiring:
   If a consumer requires a samplesheet and 'input' is omitted, nf-chain
   automatically finds the nearest upstream step emitting a compatible samplesheet:
       sra = fetchngs(ids="SRR9984183")
       qc  = demo()   # input ← sra.samplesheet (automatically wired!)

5. Version Pinning:
   By default, nf-chain pins to each pipeline's latest release tag.
   To lock to a specific git tag or branch, pass 'rev':
       rna = rnaseq(genome="GRCh38", rev="3.14.0")

COMPLETE EXAMPLE (pipeline.flow):
----------------------------------
    from nf-core import sratools
    from nf-core import rnaseq

    sra = sratools(ids=["SRR6357070", "SRR6357071"])
    rna = rnaseq(input=sra.samplesheet, genome="R64-1-1", rev="3.14.0")

TYPICAL WORKFLOW:
------------------
    nfchain init pipeline.flow              # scaffold a starter .flow file
    nfchain sync pipeline.flow              # fetch schemas & configure VSCode stubs
    nfchain explain pipeline.flow           # inspect resolved arguments and wires
    nfchain dag pipeline.flow               # preview the DAG graph (mermaid/dot)
    nfchain build pipeline.flow             # compile into build_nf/ Nextflow project
    nfchain run pipeline.flow --profile docker   # run with live streaming task output
"""


def build_parser() -> argparse.ArgumentParser:
    # prog defaults to the basename of argv[0], so `nf-chain --help` and
    # `nfchain --help` each show the name that was actually invoked.
    ap = argparse.ArgumentParser(
        description="nf-chain — Chain nf-core pipelines together with Python syntax.",
        epilog=FLOW_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--refresh", action="store_true", help="bypass the schema cache")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_flow(p, help_text="path to .flow file (default: flow.flow)"):
        p.add_argument("flow", type=Path, nargs="?", default=Path("flow.flow"), help=help_text)
        p.add_argument("-o", "--outdir", default=BUILD_DIR, help="generated project dir (default: build_nf)")
        return p

    p_init = sub.add_parser(
        "init",
        help="scaffold a new starter .flow file",
        description="Create a starter .flow file with example pipeline imports, parameters, and wiring.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_init.add_argument("flow", type=Path, nargs="?", default=Path("flow.flow"), help="path to flow file to create")
    p_init.add_argument("-f", "--force", action="store_true", help="overwrite existing file")
    p_init.set_defaults(func=cmd_init)

    with_flow(
        sub.add_parser(
            "sync",
            help="fetch schemas, write VSCode stubs",
            description="Fetch remote pipeline schemas and generate type stubs in .nfchain/stubs for VS Code.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    ).set_defaults(func=cmd_sync)

    with_flow(
        sub.add_parser(
            "explain",
            help="show the resolved chain and wiring",
            description="Parse and resolve the flow file, showing all bound parameters, defaults, and artifact wires.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    ).set_defaults(func=cmd_explain)

    p_dag = sub.add_parser(
        "dag",
        help="draw the chain as a graph (mermaid/dot)",
        description="Render the chain graph showing steps and artifact connections.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_dag.add_argument("flow", type=Path, nargs="?", default=Path("flow.flow"), help="path to .flow file")
    p_dag.add_argument(
        "--format", choices=["mermaid", "dot"], default="mermaid", help="graph format (default: mermaid)"
    )
    p_dag.add_argument("-o", "--output", help="write graph to a file instead of stdout")
    p_dag.set_defaults(func=cmd_dag)

    with_flow(
        sub.add_parser(
            "build",
            help="generate the Nextflow project",
            description="Compile the .flow file into a runnable Nextflow project (build_nf/run.sh, main.nf, etc.).",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    ).set_defaults(func=cmd_build)

    p_run = with_flow(
        sub.add_parser(
            "run",
            help="build, then run (live per-task output)",
            description="Build and execute the chain. Flags after '--' are forwarded directly to Nextflow.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    )
    p_run.add_argument("--profile", default="docker", help="Nextflow profile to use (default: docker)")
    p_run.add_argument(
        "--results-dir",
        "--results",
        dest="results_dir",
        default=None,
        help="results directory or S3 bucket path (default: build_nf/results)",
    )
    p_run.add_argument("-resume", "--resume", action="store_true", help="resume execution from cache")
    p_run.add_argument(
        "--nested",
        action="store_true",
        help="run the nested main.nf (Nextflow-managed DAG) instead of sequential run.sh",
    )
    p_run.set_defaults(func=cmd_run)

    p_stubs = with_flow(
        sub.add_parser(
            "stubs",
            help="stub-run each pipeline to list its tasks (light)",
            description="Run each pipeline in -stub-run mode with test profiles to preview the task list.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    )
    p_stubs.add_argument("--profile", default="test,docker", help="profile for stub run (default: test,docker)")
    p_stubs.set_defaults(func=cmd_stubs)

    p_watch = with_flow(
        sub.add_parser(
            "watch",
            help="re-sync stubs on every save",
            description="Watch a .flow file and re-sync editor stubs whenever it is modified.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    )
    p_watch.add_argument("--interval", type=float, default=1.0, help="polling interval in seconds")
    p_watch.set_defaults(func=cmd_watch)

    p_ls = sub.add_parser(
        "ls",
        help="list nf-core pipelines",
        description="List all available nf-core pipelines with optional search query.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ls.add_argument("query", nargs="?", help="optional filter query")
    p_ls.set_defaults(func=cmd_ls)

    p_show = sub.add_parser(
        "show",
        help="show a pipeline's params",
        description="Display inputs (from live nextflow_schema.json) and published outputs for a pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_show.add_argument("pipeline", help="pipeline name or alias (e.g. rnaseq, sratools)")
    p_show.add_argument("--rev", help="specific revision / tag (default: latest)")
    p_show.add_argument("--all", action="store_true", help="show all parameters including optional and boilerplate")
    p_show.set_defaults(func=cmd_show)

    return ap


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Split off a `--` passthrough before argparse, so forwarded flags like
    # `-with-tower` aren't mistaken for nf-chain options. Everything to the left
    # is parsed normally; everything to the right goes to the nextflow run(s).
    passthrough: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, passthrough = argv[:i], argv[i + 1 :]

    args = build_parser().parse_args(argv)
    args.nf_extra = passthrough
    try:
        return args.func(args)
    except (Abort, dsl.DslError, graph.ChainError, registry.UnknownPipeline, FetchError) as e:
        print(f"\033[31merror:\033[0m {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
