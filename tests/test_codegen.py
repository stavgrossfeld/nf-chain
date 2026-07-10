from __future__ import annotations

import json
from pathlib import Path

import pytest

from nfchain import codegen, dsl, graph

CHAIN_SRC = (
    "from nf-core import sratools\n"
    "from nf-core import rnaseq\n"
    "sra = sratools(ids=['SRR1', 'SRR2'])\n"
    "rna = rnaseq(input=sra.samplesheet, genome='GRCh38')\n"
)


@pytest.fixture
def chain(root):
    return graph.resolve(dsl.parse(CHAIN_SRC, Path("f.flow")), root)


def test_one_process_per_step(chain):
    main = codegen.render_main(chain)
    assert "process NFCORE_SRA {" in main
    assert "process NFCORE_RNA {" in main


def test_processes_are_pinned_to_a_revision(chain):
    main = codegen.render_main(chain)
    # `\\` in the generated file; Groovy collapses it to the shell's `\`.
    assert "nextflow run nf-core/fetchngs \\\\\n        -r 1.12.0" in main
    assert "nextflow run nf-core/rnaseq \\\\\n        -r 3.26.0" in main


def test_accessions_become_a_collectfile_channel(chain):
    main = codegen.render_main(chain)
    assert "ch_sra_ids = Channel.of( 'SRR1', 'SRR2' )" in main
    assert "collectFile( name: 'sra.accessions.csv', newLine: true )" in main
    assert "--input ${accessions}" in main


def test_wire_becomes_a_process_input_and_cli_flag(chain):
    main = codegen.render_main(chain)
    assert "    path in_input" in main
    assert "--input ${in_input}" in main
    assert 'rna = NFCORE_RNA( file("${projectDir}/params/rna.json"), sra.samplesheet )' in main


def test_nextflow_options_precede_pipeline_params(chain):
    main = codegen.render_main(chain)
    script = main.split("process NFCORE_RNA {")[1]
    assert script.index("-work-dir ./work") < script.index("--input ${in_input}")


def test_consumed_artifact_is_mandatory_others_optional(chain):
    main = codegen.render_main(chain)
    # rnaseq consumes sra.samplesheet, so it must exist...
    assert 'path "sra/samplesheet/samplesheet.csv", emit: samplesheet\n' in main
    # ...while fetchngs' metadata and all of rnaseq's outputs are optional.
    assert 'emit: metadata, optional: true' in main
    assert 'emit: counts, optional: true' in main


def test_line_continuations_survive_groovy_escaping(chain):
    main = codegen.render_main(chain)
    # Groovy renders `\\` inside a triple-quoted string as a single backslash,
    # which is what the shell needs to continue the line.
    assert "\\\\\n" in main
    assert "\\\\\\" not in main


def test_write_emits_project_files(chain, root):
    out = root / "build_nf"
    written = codegen.write(chain, out)

    assert (out / "main.nf") in written
    assert (out / "nextflow.config").exists()

    sra_params = json.loads((out / "params" / "sra.json").read_text())
    # outdir is nf-chain's, and the downstream hint was inferred.
    assert sra_params["outdir"] == "sra"
    assert sra_params["nf_core_pipeline"] == "rnaseq"

    rna_params = json.loads((out / "params" / "rna.json").read_text())
    assert rna_params["genome"] == "GRCh38"
    # wired inputs are passed on the CLI at runtime, never baked into params
    assert "input" not in rna_params


def test_config_records_the_chain(chain):
    cfg = codegen._config(chain)
    assert "sra=nf-core/fetchngs@1.12.0" in cfg
    assert "rna=nf-core/rnaseq@3.26.0" in cfg
    assert "nf_profile" in cfg
