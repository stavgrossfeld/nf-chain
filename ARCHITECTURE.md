# nf-chain — architecture

How the whole repo fits together, and why it's built the way it is. For usage,
see [README.md](README.md); this document is about the internals.

---

## The idea in one paragraph

You write a short `.flow` file — Python with `from nf-core import <pipeline>`
lines and a few assignments — and nf-chain turns it into a runnable Nextflow
project that chains released [nf-core](https://nf-co.re) pipelines end to end,
feeding each pipeline's published output into the next one's input. Nothing
about a pipeline's parameters is hardcoded: nf-chain reads each pipeline's own
`nextflow_schema.json` live, at a pinned revision, and uses it to validate the
flow, generate the workflow, and produce editor type-stubs. The only
hand-maintained knowledge is a small table of what each pipeline *publishes*,
because schemas describe inputs but never outputs.

---

## The pipeline of the tool itself

Every command walks some prefix of this data-flow. Each stage is one module with
one job, and each produces a plain dataclass the next stage consumes.

```
 flow file (.flow)
     │  dsl.parse_file            text → Flow (imports + Steps + Refs)
     ▼
   Flow
     │  graph.resolve            for each step:
     │    ├─ registry.resolve      name → PipelineRef  (alias + pin revision)   ── nf-co.re/pipelines.json
     │    ├─ schema.load           PipelineRef → PipelineSchema (params)        ── raw.githubusercontent…/nextflow_schema.json
     │    └─ contracts             outputs (EMITS) + name/param aliases
     ▼
   Chain  (ResolvedSteps + Wires: the validated, wired graph)
     │
     ├─ codegen.write     → build_nf/ : main.nf, run.sh, nextflow.config, params/*
     ├─ stubgen.sync      → .nfchain/stubs + .nfchain/schemas + .vscode/settings.json
     └─ dag.render        → mermaid / dot
```

`cache.py` sits under `registry` and `schema` — every network read is memoised
on disk. `cli.py` is the thin argparse layer that wires commands to these stages.

---

## Modules

Roughly in dependency order (leaves first).

### `cache.py` — on-disk TTL cache
The one place that touches the network. `fetch_text` / `fetch_json` GET a URL and
memoise it under `<root>/.nfchain/cache` for 6 hours. If the network is down and
a stale entry exists, it serves the stale entry rather than failing — so "read
schemas on the fly" doesn't mean "break on a plane". Raises `FetchError` on a
real miss. No third-party HTTP library; it's `urllib`.

### `contracts.py` — the hand-maintained knowledge
Everything nf-chain *can't* learn from a schema:
- **`ALIASES`** — import-name → real pipeline. `sratools` isn't an nf-core
  pipeline (it's a module); the pipeline that wraps it is `fetchngs`. So
  `from nf-core import sratools` resolves to `nf-core/fetchngs`.
- **`EMITS`** — per pipeline, the artifacts it publishes under `--outdir`, each
  tagged with a **kind** (`samplesheet/nf-core`, `matrix/counts`, `variants/vcf`,
  …). This is the only table you extend to teach nf-chain a new *producer*.
  Schemas exhaustively describe inputs, which is why those are read live, but say
  nothing about outputs — hence this table.
- **`PARAM_ALIASES` / `DISPLAY_ALIASES`** — friendly keyword ↔ real param
  (`ids` ↔ `input` for fetchngs), and which friendly name to advertise in
  completions.
- **`ACCESSION_INPUT`** — pipelines whose `input` is a list of accessions written
  to a file, not a samplesheet already on disk.

### `registry.py` — name → pinned pipeline
`resolve(name)` applies the alias, looks the pipeline up in the live registry
(`nf-co.re/pipelines.json`), and pins a revision: the newest release tag (`dev`
skipped), or the default branch if there are no releases, or whatever `rev=` the
flow specified. Returns a `PipelineRef` (name, `full_name`, `revision`,
`schema_url`). An unknown name raises `UnknownPipeline` with `difflib`
did-you-mean suggestions.

### `schema.py` — pipeline → parameters
`load(ref)` fetches that pipeline's `nextflow_schema.json` at the pinned revision
and flattens its grouped `$defs`/`definitions` into a flat map of `Param`
(type, description, enum, `format`, mimetype, pattern, required, group). Helpers:
`required`, `user_params()` (hides template boilerplate groups), and
`primary_input()` — the required samplesheet a chained upstream step should feed.
Handles nf-core's move from `definitions` to `$defs`.

### `dsl.py` — the `.flow` language
A flow file *is* Python, with one concession: `nf-core` keeps its hyphen because
that's the real pipeline name. `normalize()` rewrites the single token
`nf-core` → `nf_core`, then `ast.parse` handles the rest — so the file is real
Python and the generated stubs light up in an editor. Flow files are **parsed,
never executed**. The parser accepts only `from nf-core import …` and single
assignments of pipeline calls; arguments must be keyword literals or an upstream
output (`sra.samplesheet`, captured as a `Ref`). `rev="…"` is lifted off the
kwargs. Everything else is a `DslError` with a `file:line` prefix. Produces a
`Flow` (imports, `Step`s, `Ref`s).

### `graph.py` — resolve + validate + wire  ← the core
`resolve(flow)` turns a parsed `Flow` into a `Chain` of `ResolvedStep`s. Per step:
1. **Bind kwargs** to real params (via param aliases); reject unknown params
   (with suggestions) and nf-chain-managed ones (`outdir`).
2. **Lift accession lists** out of params for `ACCESSION_INPUT` pipelines.
3. **Wire.** An explicit `input=sra.samplesheet` becomes a `Wire` after checking
   the producer actually emits that artifact. If a required samplesheet input is
   left unset, `_autowire` fills it from the nearest upstream step that emits a
   `samplesheet/nf-core`. When a producer is fetchngs, `_link_fetchngs` sets its
   `--nf_core_pipeline` to the consumer — the pipeline's own chaining hook —
   but only if the consumer is in fetchngs's enum for that param.
4. **Check completeness.** Every required param must be supplied, wired, managed,
   or carry a schema default (sarek's `step=mapping` is required-with-default, so
   it doesn't count as missing).

The output `Chain` is the single source of truth every generator reads.

### `codegen.py` — Chain → runnable Nextflow
`write()` emits a `build_nf/` project with two ways to run the same chain:
- **`main.nf`** — one process per step, each shelling out to
  `nextflow run nf-core/<name> -r <rev>`. Nextflow's DSL2 `include` only pulls
  *local* modules/subworkflows, not whole remote pipelines, so composing
  *released* pipelines means a nested run per step. Literal params go in a
  per-step JSON params-file; wired inputs are passed on the CLI because only
  Nextflow knows their staged paths at runtime. Each process also gets a
  `stub:` block (materialises its outputs) so `-stub-run` exercises the whole
  DAG in seconds, and `debug true` to surface the nested log.
- **`run.sh`** — runs each pipeline as an ordinary top-level `nextflow run` in
  sequence, wiring each step's published path into the next `--input`. This is
  the one that shows **every task of every pipeline live**; `main.nf` hides them
  behind one process spinner. Runs from a clean `build_nf/run/` dir so Nextflow
  doesn't auto-load the driver config.

Both export `NXF_SYNTAX_PARSER=v1` before each nested run (see design notes).

### `stubgen.py` — Chain → editor intelligence
`sync()` writes three things so a flow file is smart the moment you type it:
- `.nfchain/stubs/nf_core/__init__.pyi` — one typed function per imported
  pipeline: enums as `Literal[...]`, outputs as attributes (`sra.samplesheet`),
  the pipeline's description and required list as the docstring. Every param is
  `= ...` (even required ones) because a required input may be satisfied by
  auto-wiring; missing inputs are caught by `build`, not the type checker.
- `.nfchain/schemas/<pipeline>.params.schema.json` — validates the generated
  params files in-editor.
- `.vscode/settings.json` — points Pylance at the stubs, maps the JSON schemas,
  associates `*.flow` with Python. Existing settings are preserved.

### `dag.py` — Chain → picture
`render_mermaid` / `render_dot`: nodes are steps (pipeline@rev + set params),
edges are wires labelled with the artifact kind and marked when inferred.

### `cli.py` — the commands
Thin argparse layer. `_load` runs parse→resolve once; each `cmd_*` calls one
generator. Commands: `explain`, `dag`, `sync`, `build`, `run` (uses `run.sh`;
`--nested` uses `main.nf`), `watch` (re-sync on save), `ls`, `show`. Two console
entry points, `nf-chain` and `nfchain`, both → `main`.

---

## Generated output

```
build_nf/
  main.nf            nested-run driver (Nextflow-managed DAG)
  run.sh             sequential runner (live per-task output)   ← nfchain run
  nextflow.config    params + profiles (map -profile onto nested runs)
  params/
    <step>.json      literal params for each pipeline
    <step>.accessions.csv   materialised id list (accession-input steps)

.nfchain/            editor + cache (gitignored)
  stubs/nf_core/__init__.pyi
  schemas/<pipeline>.params.schema.json
  cache/             fetched schemas + registry (6h TTL)
```

---

## Design decisions worth knowing

- **Schemas are read live, outputs are curated.** A pipeline's inputs come from
  its own schema at the pinned revision (always current, all 152 pipelines).
  Outputs can't — schemas don't describe them — so `EMITS` is the one table you
  extend. A pipeline with no `EMITS` entry still works as the *last* step.

- **`sratools` → `fetchngs`.** People reach for the tool name; the alias lands
  them on the pipeline that actually exists. `explain`/`dag` always show the real
  pipeline.

- **Auto-wiring is conservative.** It only fills a *required* samplesheet input.
  Optional inputs (sarek is multi-entry, so its `input` is optional) are wired
  explicitly. The kind system could match BAM/VCF too; the inference doesn't
  guess yet.

- **Nested `nextflow run`, not `include`.** DSL2 `include` can't pull whole
  remote pipelines, so each released pipeline runs as its own process. Trade-off:
  Nextflow manages the graph, but the nested tasks are hidden — which is exactly
  why `run.sh` exists.

- **`NXF_SYNTAX_PARSER=v1`, not a Nextflow downgrade.** 2024-era nf-core configs
  have a `def check_max(...)` helper that Nextflow 25+'s strict config parser
  rejects, and those releases cap only the *minimum* NF version. The fix is the
  legacy parser (`v1`), read at config-parse time, so it works with any
  `nextflow` on PATH — including Homebrew's fixed build, which ignores `NXF_VER`.
  The generated script uses `${params.nf_syntax_parser ?: 'v1'}` so a missing
  value can never render `null` (which Nextflow rejects outright).

- **Stubs use `= ...` everywhere and are checked with mypy.** Required-ness lives
  in the docstring and is enforced by `build`, so auto-wiring type-checks.
  Enum values are rendered as Python (`False`, not JSON `false`) — a bug the
  generated-stub mypy check catches that `ast.parse` silently accepts.

- **No third-party runtime dependencies.** Standard library only, so
  `pip install nf-chain` is instant and the tool is easy to vendor.

---

## Testing

`tests/` is fully offline: `conftest.py` monkeypatches the two `fetch_json`
seams to serve fixture copies of `pipelines.json` and four `nextflow_schema.json`
files, shaped like the real ones (including `$defs`, enums, required-with-default,
boolean enums). One suite per stage — `test_dsl`, `test_graph`, `test_codegen`,
`test_stubgen`, `test_dag`. The generated Nextflow was additionally launched
against a real Nextflow 26.04 (`-stub-run` for wiring, real `-profile docker`
for a genuine fetchngs run) to confirm it parses, wires, and executes.

```console
make test        # 76 tests, no network
```

---

## Limitations

- Composing released pipelines uses nested `nextflow run`, so `-resume` works
  within a step but the driver can't resume into the middle of one.
- `nextflow` must be on PATH inside the task environment; the driver runs local.
- Output contracts are curated (`fetchngs`, `rnaseq`, `sarek`, `atacseq` today).
- Auto-wiring only matches samplesheets.
- Real runs are real workloads — the example pulls actual FASTQ and a human
  reference; use `-stub-run` to exercise the chain cheaply.

---

## Extending it

- **New producer pipeline:** add its published paths to `EMITS` in
  `contracts.py`. Everything else (params, validation, stubs, pinning) is
  discovered from its schema.
- **New friendly import name:** add to `ALIASES`.
- **New output format:** add a `render_*` to `dag.py` or a writer to `codegen.py`;
  both read the same `Chain`.
