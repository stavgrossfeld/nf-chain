# nf-chain

Chain [nf-core](https://nf-co.re) pipelines together with simple, idiomatic Python.

```python
# pipeline.flow
from nf-core import fetchngs, rnaseq

sra = fetchngs(ids=["SRR6357070", "SRR6357071"])
rna = rnaseq(input=sra.samplesheet, genome="GRCh38")
```

`nf-chain` parses the flow, auto-wires samplesheets between pipelines, queries live schemas for type-checking and parameter validation, and compiles a production-ready Nextflow execution project.

---

## Installation

Install as a global tool using **[uv](https://github.com/astral-sh/uv)** (recommended):

```bash
uv tool install git+https://github.com/stavgrossfeld/nf-chain
```

Or run instantly without installation:
```bash
uvx --from git+https://github.com/stavgrossfeld/nf-chain nf-chain --help
```

*(With traditional pip: `pip install git+https://github.com/stavgrossfeld/nf-chain`)*

**Prerequisites:** Python 3.10+, [Nextflow](https://nextflow.io) (and Java), and a container engine (Docker / OrbStack / Singularity). `nf-chain` itself has **zero third-party Python runtime dependencies**.

---

## Quickstart

### 1. Scaffold a flow
```bash
nf-chain init my_pipeline.flow
```

### 2. Inspect the chain and wiring
```bash
nf-chain explain my_pipeline.flow
```
```text
sra  nf-core/fetchngs@1.12.0
      accessions: SRR6357070, SRR6357071
      nf_core_pipeline = 'rnaseq' (auto)

rna  nf-core/rnaseq@3.14.0
      input ← sra.samplesheet  [samplesheet/nf-core] (auto)
      genome = 'GRCh38'
```

### 3. Fast DAG preview (zero downloads, zero errors)
Evaluate the full multi-pipeline task graph in seconds without running containers:
```bash
nf-chain preview my_pipeline.flow
```

### 4. Run the chain
```bash
# Live task output across both pipelines:
nf-chain run my_pipeline.flow --profile docker

# Dry-run with mock outputs in seconds:
nf-chain run my_pipeline.flow --stub-run
```

---

## Features

- 🔗 **Smart Auto-Wiring**: Automatically infers samplesheet connections between upstream producers (like `fetchngs`) and downstream consumers (`rnaseq`, `sarek`, `demo`), and sets formatting flags like `--nf_core_pipeline` automatically.
- 💡 **IDE Type Stubs (`.pyi`)**: `nf-chain sync` fetches each pipeline's `nextflow_schema.json` to generate typed stubs with autocompletion, enums as `Literal[...]`, and docstrings in VSCode and PyCharm.
- ⚡ **Zero-Execution DAG Previews**: Uses Nextflow's native `-preview` mode to evaluate channels and display the full task DAG of every pipeline in ~3 seconds.
- ☁️ **Seqera Platform (Tower) Ready**: 
  - Real-time live monitoring: `nf-chain run flow.flow --tower`
  - Cloud orchestration via `tw` CLI: `nf-chain tower flow.flow --compute-env aws-batch --results s3://bucket/results`
- 📦 **Zero Runtime Dependencies**: The entire compiler, parser, and CLI run on the Python standard library alone.

---

## CLI Reference

| Command | Description |
|---|---|
| `nf-chain init [flow]` | Scaffold a starter `.flow` file |
| `nf-chain explain <flow>` | Resolve the chain, verify parameters, and print wiring |
| `nf-chain preview <flow>` | Print the full Nextflow task DAG for every pipeline in seconds |
| `nf-chain run <flow>` | Compile and run with live streaming task output (`--profile docker`) |
| `nf-chain tower <flow>` | Launch the chain into Seqera Platform cloud compute environments |
| `nf-chain dag <flow>` | Render DAG diagram (`--format mermaid` or `--format dot`) |
| `nf-chain sync <flow>` | Generate editor type stubs (`.pyi`) and JSON Schemas |
| `nf-chain watch <flow>` | Automatically re-sync stubs on file save |
| `nf-chain ls [query]` | Search and list available nf-core pipelines |
| `nf-chain show <pipeline>` | Print a pipeline's schema inputs and published outputs |

---

## Execution Modes

- **Sequential Task Streaming (`default`)**: Runs each pipeline step sequentially via `run.sh`. Every individual task (`FASTQC`, `STAR`, `MULTIQC`) streams live to your console and reports individually to Seqera Platform.
- **Unified DAG Driver (`--nested`)**: Runs `build_nf/main.nf` directly, where Nextflow manages the execution graph.

---

## Development

```bash
git clone https://github.com/stavgrossfeld/nf-chain && cd nf-chain
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Run test suite (104 tests, no network required):
pytest
mypy src tests
```

For compiler architecture, data structures, and contract design, see [ARCHITECTURE.md](ARCHITECTURE.md).
