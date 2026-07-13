# nf-chain

Chain nf-core pipelines together with a simple import.

> Internals and design rationale: [ARCHITECTURE.md](ARCHITECTURE.md).

```python
# examples/sra_to_rnaseq.flow
from nf-core import sratools
from nf-core import rnaseq

sra = sratools(ids=["SRR6357070", "SRR6357071"])
rna = rnaseq(input=sra.samplesheet, genome="GRCh38")
```

```console
$ nfchain build examples/sra_to_rnaseq.flow
built 2-step chain → build_nf/

$ nextflow run build_nf/main.nf -stub-run -profile docker   # dry-run the whole chain
[PROCESS 3d/a62225] NFCORE_SRA (nf-core/fetchngs@1.12.0)
[PROCESS 8d/a01b88] NFCORE_RNA (nf-core/rnaseq@3.14.0)
[SUCCESS] completed=2 failed=0 cached=0

$ nextflow run build_nf/main.nf -profile docker             # for real (needs data + Docker)
```

Nothing about `rnaseq`'s inputs is hardcoded in nf-chain. The pipeline's own
`nextflow_schema.json` is fetched at the pinned revision, turned into type stubs,
and dropped into `.nfchain/stubs` — so the moment you write the import, VSCode
knows every param the pipeline takes, which ones are required, and which values
its enums allow.

---

## Install

It's an ordinary, dependency-free Python package. Install it however you like:

```console
pip install nf-chain                      # once published to PyPI
pip install git+https://github.com/stav/nf-chain     # straight from GitHub
pip install .                             # from a clone (add -e for editable)
make wheel && pip install dist/nf_chain-*.whl        # from a built wheel
```

Any of these exposes the `nf-chain` (and `nfchain`) command and lets you
`import nfchain` as a library. For local development:

```console
git clone <this repo> && cd nf-chain
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

This installs two identical console commands, `nf-chain` and `nfchain` (into the
venv). To get a real `nf-chain` on your PATH — better than a shell alias, since
it works in every shell and in scripts — use the Makefile:

```console
make install     # symlinks ~/.local/bin/nf-chain -> .venv/bin/nf-chain
make uninstall   # removes it
```

`make` on its own lists every target (`test`, `explain`, `build`, `run`, …), so
you can also drive the tool without installing it at all:

```console
make run FLOW=examples/sra_to_rnaseq.flow PROFILE=docker
```

Only the standard library is needed. Running the generated workflow additionally
needs [Nextflow](https://nextflow.io) (and Java) on `PATH`.

## Commands

| | |
|---|---|
| `nfchain explain <flow>` | resolve the chain, show every wire and where it came from |
| `nfchain dag <flow>` | draw the chain as a graph (`--format mermaid`\|`dot`) |
| `nfchain sync <flow>` | fetch schemas → write editor stubs + JSON Schemas |
| `nfchain build <flow>` | generate a runnable Nextflow project into `build_nf/` |
| `nfchain stubs <flow>` | stub-run each pipeline to list its tasks, kept light |
| `nfchain run <flow>` | build, then `nextflow run` it |
| `nfchain watch <flow>` | re-sync stubs on every save |
| `nfchain ls [query]` | list the 150-odd nf-core pipelines |
| `nfchain show <pipeline>` | print a pipeline's params, straight from its schema |

## Seeing each pipeline's tasks (without a data run)

```console
nf-chain stubs examples/sra_to_rnaseq.flow
```

Stub-runs each pipeline on its own with its `test` profile, listing every task:

```
==> step 1/2: nf-core/fetchngs@1.12.0  (light: --skip_fastq_download true)
NFCORE_FETCHNGS:SRA:SRA_IDS_TO_RUNINFO … SRA_TO_SAMPLESHEET …
==> step 2/2: nf-core/rnaseq@3.14.0
NFCORE_RNASEQ:RNASEQ:FASTQC … TRIMGALORE … PREPARE_GENOME:SALMON_INDEX …
```

Two caveats, because they're real. `-stub-run` only fakes a module that ships a
`stub:` block — coverage varies (demo 4/4, rnaseq 19/61, fetchngs 1/10), so
un-stubbed modules run for real on the pipeline's **test** data. "Light" means
test-scale, **not zero**: nf-chain sets any schema-declared download-skip param
it finds (fetchngs' `skip_fastq_download` → 0 bytes pulled), but a pipeline whose
test inputs are FastQs and whose staging modules aren't stubbed (rnaseq) still
stages those test FastQs — tens of MB, versus the multi-GB of a real chain run.
It uses each pipeline's own test data, so it's a task-graph preview, not your
chain's data run.

For a chain-level wiring check instead, `nextflow run build_nf/main.nf -stub-run`
shows the two chain steps instantly.

## How the chaining works

`nfchain explain` on the example above:

```
sra  nf-core/fetchngs@1.12.0
      accessions: SRR6357070, SRR6357071
      nf_core_pipeline = 'rnaseq' (auto)

rna  nf-core/rnaseq@3.14.0
      input ← sra.samplesheet  [samplesheet/nf-core] (auto)
      genome = 'GRCh38'
```

Two things happened on their own.

**The samplesheet edge was inferred.** `rnaseq` declares `input` as a required
`file-path` with mimetype `text/csv`; `fetchngs` publishes a samplesheet. Kinds
match, so nf-chain wires them. You can write `rna = rnaseq()` and get the same
graph — passing `input=sra.samplesheet` just makes the edge explicit.

**fetchngs was told its downstream consumer.** fetchngs has an
`--nf_core_pipeline` param that formats its samplesheet for a named pipeline.
That's the pipeline's own chaining hook, so nf-chain sets it rather than hoping
a generic samplesheet lines up. Set it yourself and nf-chain won't touch it.

Everything is version-pinned to the newest release tag (`dev` is skipped), or to
whatever you pass as `rev=`.

## Why `sratools` resolves to `fetchngs`

`sratools` is an nf-core *module*, not a pipeline — you can't run it standalone.
The pipeline that wraps it to pull reads from SRA/ENA/GEO/DDBJ is
[`nf-core/fetchngs`](https://nf-co.re/fetchngs). Since that's the name most
people reach for, `src/nfchain/contracts.py` aliases it, along with `sra` and
`fastq_dl`. `nfchain explain` always prints the pipeline that actually runs.

## Editor integration

`nfchain sync` (or `watch`) writes three things:

- `.nfchain/stubs/nf_core/__init__.pyi` — one typed function per import, with
  enums as `Literal[...]`, outputs as attributes (`sra.samplesheet`), and the
  pipeline's own description and required-param list as the docstring.
- `.nfchain/schemas/<pipeline>.params.schema.json` — validates the generated
  `build_nf/params/*.json` in the editor.
- `.vscode/settings.json` — points Pylance at the stubs, maps the JSON Schemas,
  and associates `*.flow` with Python. Existing settings are preserved.

Every param carries `= ...` in the stub even when it's required, because a
required input may be satisfied by auto-wiring. Missing inputs are caught by
`nfchain build`, which is the thing that actually knows the graph.

Keep completions fresh while you work:

```console
$ nfchain watch examples/sra_to_rnaseq.flow
✓ 14:02:11  nf-core/fetchngs → nf-core/rnaseq
```

Schemas are cached under `.nfchain/cache` for six hours; `--refresh` forces a
re-fetch. If you're offline, a stale cache entry is served rather than failing.

## The flow file

A flow file is Python, with one concession: `nf-core` keeps its hyphen, because
that's what the pipelines are actually called. nf-chain rewrites that one token
to `nf_core` and parses the rest with `ast`. `from nf_core import ...` works too,
if you'd rather not see the squiggle. Flow files are **parsed, never executed**.

Steps may only pass keyword arguments. Values are literals or an upstream
output (`sra.samplesheet`). `rev="3.14.0"` pins that step.

## Two ways to run a chain

`nfchain build` writes both:

- **`run.sh` (default, recommended)** — runs each pipeline as an ordinary
  top-level `nextflow run`, in order, wiring each step's published output into
  the next step's input. You see **every task of every pipeline live**, exactly
  like running nf-core by hand. `nfchain run` uses this.
- **`main.nf` (nested DAG)** — one Nextflow driver process per pipeline, each
  shelling out to a child `nextflow run`. Nextflow manages the graph, but the
  child's tasks are hidden: you see one `NFCORE_SRA  0 of 1` line for the whole
  duration of that pipeline, which looks like a hang during a long download. Use
  `nfchain run --nested` (or run `main.nf` directly) if you want it.

```console
$ build_nf/run.sh docker
==> step 1/2: nf-core/fetchngs@1.12.0
[PROCESS 54/7bbde0] NFCORE_FETCHNGS:SRA:SRA_IDS_TO_RUNINFO (SRR6357070)
[PROCESS 36/a87f25] NFCORE_FETCHNGS:SRA:SRA_FASTQ_FTP (SRX3453465_SRR6357070)
...
==> step 2/2: nf-core/rnaseq@3.14.0
[PROCESS .. / ......] NFCORE_RNASEQ:RNASEQ:...
```

### Forwarding Nextflow flags (Seqera Platform / Tower, reports, etc.)

Anything after `--` is passed straight to each `nextflow run`:

```console
export TOWER_ACCESS_TOKEN=...    # from Seqera Platform → Access tokens
nf-chain run examples/sra_to_rnaseq.flow --profile docker -- -with-tower
```

Because `run.sh` launches each pipeline as its own top-level run, `-with-tower`
gives you **one Seqera Platform run per pipeline** — properly monitored, with all
tasks visible — instead of the nested driver that would hide them. The same works
directly: `build_nf/run.sh docker -with-tower -with-report`.

If you're stuck watching `main.nf` show `NFCORE_SRA  0 of 1` and nothing else,
it is **not hung** — the nested pipeline is running; its task output is in
`build_nf/work/<hash>/.command.out`. The generated processes set `debug true` to
echo that log, but some Nextflow console renderers only flush it on completion,
so `run.sh` (or `nfchain run`) is the reliable way to watch tasks live.

**Don't run `nextflow run main.nf` when you want to watch progress** — that's the
nested driver, and it shows one line per pipeline by construction. Use
`./run.sh <profile>` or `nfchain run`.

## What gets generated

`build_nf/main.nf` has one process per step, each shelling out to
`nextflow run nf-core/<name> -r <rev>`:

```groovy
process NFCORE_RNA {
    tag "nf-core/rnaseq@3.14.0"

    input:
    path params_file
    path in_input

    output:
    path "rna", emit: outdir
    path "rna/star_salmon/salmon.merged.gene_counts.tsv", emit: counts, optional: true

    script:
    """
    nextflow run nf-core/rnaseq \
        -r 3.14.0 \
        -profile ${params.nf_profile} \
        -params-file ${params_file} \
        --input ${in_input} \
        --outdir rna
    """
}
```

Literal params go into `build_nf/params/<step>.json`; chained inputs are passed
on the command line, because only Nextflow knows their staged paths at runtime.
An artifact consumed downstream is a required output; the rest are `optional`.

Every process also gets a `stub:` block that `touch`es its declared outputs, so
`nextflow run build_nf/main.nf -stub-run` executes the entire DAG in seconds
without running a single real pipeline. That's the fast way to check a chain is
wired correctly — if a downstream input isn't actually produced upstream, the
stub run fails at that wire. `-profile docker` on the driver selects the profile
handed to the nested runs (`-profile singularity`, `conda`, `podman`, `test`
work too); the tiny driver processes always run locally.

## Does the chaining actually work?

Yes — and you can watch the data cross the wire. After a stub run of the example:

```console
$ ls build_nf/results/
sra/samplesheet/samplesheet.csv          # produced by fetchngs
rna/star_salmon/salmon.merged.gene_counts.tsv   # produced by rnaseq

# Nextflow staged fetchngs' samplesheet as rnaseq's input:
$ ls -l build_nf/work/<rna-task>/
samplesheet.csv -> .../work/<sra-task>/sra/samplesheet/samplesheet.csv
```

It is not hardcoded to one pair. `fetchngs → sarek` (variant calling) chains the
same way — `sarek(input=sra.samplesheet)` — and stub-runs to `completed=2`.

**What "anything" means, precisely.** All 152 nf-core pipelines can be imported,
resolved, pinned, and turned into stubs — that half is fully general, because
it's read from each pipeline's schema. Chaining has one requirement: the
*producer* needs an entry in the `EMITS` table (`src/nfchain/contracts.py`),
which currently covers `fetchngs`, `rnaseq`, `sarek` and `atacseq`. A pipeline
with no `EMITS` entry is fine as the **last** step (nothing reads its output),
but to feed a downstream step you add its published paths there — a few lines.
Auto-wiring fires only for a consumer's *required* samplesheet; optional inputs
(like sarek's) are wired explicitly. Everything else about the pipeline is still
discovered live.

## Troubleshooting a real run

**`Unexpected input: '('` / `def check_max(obj, type)` — config parsing failed.**
2024-era nf-core pipelines (e.g. fetchngs 1.12.0) put a `def check_max(...)`
helper in `nextflow.config`, and cap only the *minimum* Nextflow version. A
current Nextflow (25+) defaults to a strict config parser that rejects that
helper. The fix is the **legacy parser, not an older Nextflow** — nf-chain
exports `NXF_SYNTAX_PARSER=v1` before each nested run (the `nf_syntax_parser`
param, default `v1`). It's read at config-parse time, so it works with any
`nextflow` on `PATH`, Homebrew's fixed build included. Once every pipeline in
the chain has dropped `check_max`, switch to the strict parser:

```console
nextflow run build_nf/main.nf -profile docker --nf_syntax_parser v2
```

Verified: with `v1`, fetchngs 1.12.0 runs its real tasks under Nextflow 26.04.

**`Cannot connect to the Docker daemon`.** Start Docker Desktop / OrbStack. This
is unrelated to nf-chain — the nested pipeline reached the point of launching a
container, which means config parsing and wiring already succeeded.

**`Unknown configuration profile: 'docker'`.** The generated `nextflow.config`
defines the profiles, and Nextflow reads it from the script's directory — so run
the generated `main.nf`, not a hand-written one, and rebuild after upgrading
nf-chain (`nfchain build`) so the config includes the profile block.

**Can I use `-profile test`?** Yes, but know what it does: nf-core's `test`
profile makes each pipeline run on *its own* bundled mini-dataset, which means
each nested run ignores the wiring and runs standalone — fetchngs downloads its
test accessions, rnaseq uses its test samplesheet, and they don't feed each
other. It's a good smoke test that each pipeline runs in your environment, not a
test of the chain. For a connected run use `-profile docker` with real inputs;
to exercise the wiring cheaply use `-stub-run`.

## Limitations, honestly

- **Nested `nextflow run`.** Nextflow's DSL2 `include` pulls in modules and
  subworkflows from the local project, not whole remote pipelines. Composing
  *released* pipelines therefore means a nested run per step. Each nested run
  gets its own work directory, so `-resume` works within a step but the driver
  can't resume into the middle of one. The driver processes are tiny; the nested
  runs request resources from the executor themselves.
- **Nextflow must be on `PATH` inside the task environment.** The driver runs
  with `executor = 'local'` for that reason. Pointing it at a scheduler means
  making `nextflow` available on the compute nodes.
- **Output contracts are curated.** `nextflow_schema.json` describes a
  pipeline's inputs exhaustively — which is why nf-chain reads them live — but
  says nothing about what it publishes. The `EMITS` table in
  `src/nfchain/contracts.py` maps published paths to artifact kinds, and it
  currently covers `fetchngs`, `rnaseq`, `sarek` and `atacseq`. Adding a
  pipeline there is the only hand-written step; everything else is discovered.
- **Auto-wiring only matches samplesheets.** A BAM- or VCF-consuming pipeline
  has to be wired explicitly. The kind system supports it; the inference doesn't
  guess yet.

## Development

```console
.venv/bin/python -m pytest        # 61 tests, no network
./scripts/vendor_nextflow.sh      # shallow-clone Nextflow into vendor/ for reference
```

The generated project was launched end-to-end in `-stub-run` mode against a real
Nextflow (26.04) to confirm the DSL compiles, the workflow DAG builds, and the
upstream samplesheet is genuinely staged as the downstream pipeline's input.

Tests stub the registry and every schema, so the suite is offline and fast. The
fixtures in `tests/conftest.py` mirror the real shape of `pipelines.json` and
`nextflow_schema.json` (including nf-core's move from `definitions` to `$defs`).
