"""nfchain — command line interface."""

from __future__ import annotations

import argparse
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


def cmd_run(args) -> int:
    rc = cmd_build(args)
    if rc:
        return rc
    if shutil.which("nextflow") is None:
        raise Abort(
            "nextflow is not on PATH — install it (https://nextflow.io) or run "
            f"`{args.outdir}/run.sh` on a machine that has it"
        )
    if args.nested:
        # One driver process per pipeline; nested task output is hidden.
        cmd = ["nextflow", "run", f"{args.outdir}/main.nf", "-profile", args.profile]
        if args.resume:
            cmd.append("-resume")
    else:
        # Sequential: each pipeline runs top-level, so every task streams live.
        cmd = ["bash", f"{args.outdir}/run.sh", args.profile]
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
    root = Path.cwd()
    ref = registry.resolve(args.pipeline, root, revision=args.rev, refresh=args.refresh)
    sch = schema.load(ref, root, refresh=args.refresh)
    print(f"\n\033[1m{ref.full_name}@{ref.revision}\033[0m\n{sch.description}\n")
    for p in sch.user_params():
        if not args.all and not p.required:
            continue
        mark = "\033[31m*\033[0m" if p.required else " "
        enum = f"  {{{'|'.join(p.enum)}}}" if p.enum else ""
        print(f" {mark} {p.name:<28} {p.type}{enum}")
        if p.description:
            print(f"     {p.description[:90]}")
    if not args.all:
        print("\n(required params only; pass --all for everything)")
    return 0


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # prog defaults to the basename of argv[0], so `nf-chain --help` and
    # `nfchain --help` each show the name that was actually invoked.
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="bypass the schema cache")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_flow(p):
        p.add_argument("flow", type=Path, nargs="?", default=Path("flow.flow"))
        p.add_argument("-o", "--outdir", default=BUILD_DIR, help="generated project dir")
        return p

    with_flow(sub.add_parser("sync", help="fetch schemas, write VSCode stubs")).set_defaults(
        func=cmd_sync
    )
    with_flow(sub.add_parser("explain", help="show the resolved chain and wiring")).set_defaults(
        func=cmd_explain
    )

    d = sub.add_parser("dag", help="draw the chain as a graph (mermaid/dot)")
    d.add_argument("flow", type=Path, nargs="?", default=Path("flow.flow"))
    d.add_argument("--format", choices=["mermaid", "dot"], default="mermaid")
    d.add_argument("-o", "--output", help="write to a file instead of stdout")
    d.set_defaults(func=cmd_dag)
    with_flow(sub.add_parser("build", help="generate the Nextflow project")).set_defaults(
        func=cmd_build
    )

    run = with_flow(sub.add_parser("run", help="build, then run (live per-task output)"))
    run.add_argument("--profile", default="docker")
    run.add_argument("-resume", "--resume", action="store_true")
    run.add_argument(
        "--nested",
        action="store_true",
        help="run the nested main.nf (Nextflow-managed DAG) instead of the sequential run.sh",
    )
    run.set_defaults(func=cmd_run)

    watch = with_flow(sub.add_parser("watch", help="re-sync stubs on every save"))
    watch.add_argument("--interval", type=float, default=1.0)
    watch.set_defaults(func=cmd_watch)

    ls = sub.add_parser("ls", help="list nf-core pipelines")
    ls.add_argument("query", nargs="?")
    ls.set_defaults(func=cmd_ls)

    show = sub.add_parser("show", help="show a pipeline's params")
    show.add_argument("pipeline")
    show.add_argument("--rev")
    show.add_argument("--all", action="store_true")
    show.set_defaults(func=cmd_show)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (Abort, dsl.DslError, graph.ChainError, registry.UnknownPipeline, FetchError) as e:
        print(f"\033[31merror:\033[0m {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
