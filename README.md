# nf-chain

Chain nf-core pipelines together with a simple import.

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

```console
git clone <this repo> && cd nf-chain
python3 -m venv .venv && .venv/bin/pip install -e .
```

Only the standard library is needed. Running the generated workflow additionally
needs [Nextflow](https://nextflow.io) (and Java) on `PATH`.

## Commands

| | |
|---|---|
| `nfchain explain <flow>` | resolve the chain, show every wire and where it came from |
| `nfchain sync <flow>` | fetch schemas → write editor stubs + JSON Schemas |
| `nfchain build <flow>` | generate a runnable Nextflow project into `build_nf/` |
| `nfchain run <flow>` | build, then `nextflow run` it |
| `nfchain watch <flow>` | re-sync stubs on every save |
| `nfchain ls [query]` | list the 150-odd nf-core pipelines |
| `nfchain show <pipeline>` | print a pipeline's params, straight from its schema |

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
Your Nextflow is *newer* than the pipeline release. 2024-era nf-core pipelines
(e.g. fetchngs 1.12.0) put a `def check_max(...)` helper in `nextflow.config` and
cap only the *minimum* Nextflow version. Nextflow 25+'s strict config parser
rejects that helper. nf-chain pins each nested run to a compatible Nextflow via
`NXF_VER` (default `24.10.5`, in the generated config); override per run:

```console
nextflow run build_nf/main.nf -profile docker --nf_version 24.10.5
```

This only helps if your `nextflow` launcher honours `NXF_VER`. The **official
installer** (`curl -s https://get.nextflow.io | bash`) and the conda package do;
**Homebrew's `nextflow` is a fixed build that ignores it** — `brew install`
gives you exactly one version. If you installed via brew, use the official
launcher for real runs (stub runs are fine on any version).

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
