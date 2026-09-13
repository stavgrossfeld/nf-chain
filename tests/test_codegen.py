from __future__ import annotations

import json
from pathlib import Path

import pytest

from nfchain import codegen, dsl, graph

CHAIN_SRC = (
    "from nf-core import fetchngs\n"
    "from nf-core import rnaseq\n"
    "sra = fetchngs(ids=['SRR1', 'SRR2'])\n"
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


def test_each_nested_run_selects_the_config_parser(chain):
    main = codegen.render_main(chain)
    # export must precede the nested `nextflow run` in every process, and fall
    # back to a valid parser so it can never render `null`.
    for proc in ("NFCORE_SRA", "NFCORE_RNA"):
        script = main.split(f"process {proc} {{")[1].split("stub:")[0]
        assert "export NXF_SYNTAX_PARSER=${params.nf_syntax_parser ?: 'v1'}" in script
        assert script.index("export NXF_SYNTAX_PARSER") < script.index("nextflow run")


def test_config_defaults_to_the_legacy_parser(chain):
    cfg = codegen._config(chain)
    assert f"nf_syntax_parser = '{codegen.DEFAULT_SYNTAX_PARSER}'" in cfg
    assert codegen.DEFAULT_SYNTAX_PARSER == "v1"


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


def test_every_process_streams_nested_output(chain):
    # `debug true` echoes the nested pipeline's stdout live, so main.nf doesn't
    # look hung while a child pipeline runs.
    main = codegen.render_main(chain)
    assert main.count("debug true") == len(chain.steps)


def test_every_process_has_a_stub_block(chain):
    main = codegen.render_main(chain)
    assert main.count("stub:") == len(chain.steps)


def test_stub_creates_the_consumed_samplesheet(chain):
    main = codegen.render_main(chain)
    sra = main.split("process NFCORE_SRA {")[1].split("process ")[0]
    # the samplesheet rnaseq consumes must be created by the stub, or a
    # `-stub-run` of the chain would fail at the wire.
    assert "touch sra/samplesheet/samplesheet.csv" in sra


def test_stub_globs_become_concrete_paths(chain):
    main = codegen.render_main(chain)
    # `rna/star_salmon/*.markdup.sorted.bam` -> a real file the glob matches
    assert "touch rna/star_salmon/stub.markdup.sorted.bam" in main
    # no glob survives on any stub command line, or the touch wouldn't create it
    stub_cmds = [ln for ln in main.splitlines() if ln.strip().startswith(("touch ", "mkdir "))]
    assert stub_cmds and all("*" not in ln for ln in stub_cmds)


def test_run_sh_runs_each_pipeline_top_level(chain):
    sh = codegen.render_run_sh(chain)
    # one top-level `nextflow run` per step — this is what makes tasks visible.
    assert sh.count("nextflow run ") == len(chain.steps)
    assert "nextflow run nf-core/fetchngs \\\n        -r 1.12.0" in sh
    assert "nextflow run nf-core/rnaseq \\\n        -r 3.26.0" in sh


def test_run_sh_wires_upstream_output_as_downstream_input(chain):
    sh = codegen.render_run_sh(chain)
    # rnaseq's --input is fetchngs' published samplesheet path.
    assert '--input "$OUTDIR/sra/samplesheet/samplesheet.csv"' in sh
    # fetchngs' --input is the accessions file.
    assert '--input "$HERE/params/sra.accessions.csv"' in sh


def test_run_sh_sets_legacy_parser_and_is_ordered(chain):
    sh = codegen.render_run_sh(chain)
    assert 'export NXF_SYNTAX_PARSER="${NXF_SYNTAX_PARSER:-v1}"' in sh
    # fetchngs (producer) must be invoked before rnaseq (consumer).
    assert sh.index("nf-core/fetchngs") < sh.index("nf-core/rnaseq")


def test_run_sh_gives_each_step_a_linked_run_name(chain):
    sh = codegen.render_run_sh(chain)
    # a shared per-invocation tag, overridable, used to name every step's run
    assert 'TAG="${NFCHAIN_TAG:-run_$(date' in sh
    assert '-name "${TAG}_sra"' in sh
    assert '-name "${TAG}_rna"' in sh
    # a summary that links run names to their output locations
    assert "run=${TAG}_sra   outdir=" in sh
    assert "nextflow log" in sh


def test_run_sh_forwards_extra_nextflow_args(chain):
    sh = codegen.render_run_sh(chain)
    # profile is $1; everything after is captured and forwarded to each run.
    assert 'shift || true' in sh
    assert 'EXTRA=("$@")' in sh
    # empty-array-safe under `set -u` on bash 3.2, appended to every run
    assert sh.count('"${EXTRA[@]+"${EXTRA[@]}"}"') == len(chain.steps)


def test_run_sh_runs_from_clean_dir_to_avoid_driver_config(chain):
    # Running inside build_nf/ would auto-load the driver's nextflow.config and
    # inject its params into each standalone pipeline (an invalid-params warning).
    sh = codegen.render_run_sh(chain)
    assert 'cd "$HERE/run"' in sh
    # anchor on the indented command, not a comment that mentions nextflow
    assert sh.index('cd "$HERE/run"') < sh.index("\n    nextflow run ")


def test_write_emits_run_sh_and_accessions(chain, root):
    out = root / "build_nf"
    written = codegen.write(chain, out)
    run_sh = out / "run.sh"
    assert run_sh in written
    assert run_sh.stat().st_mode & 0o100  # executable
    acc = out / "params" / "sra.accessions.csv"
    assert acc.read_text().split() == ["SRR1", "SRR2"]


def test_stubs_runs_each_pipeline_with_stub_run(chain):
    sh = codegen.render_stubs_sh(chain)
    assert sh.count("-stub-run") == len(chain.steps)
    assert "nextflow run nf-core/fetchngs" in sh
    assert "nextflow run nf-core/rnaseq" in sh
    assert 'PROFILE="${1:-test,docker}"' in sh


def test_stubs_sets_download_skip_when_schema_has_it(chain):
    # fetchngs declares skip_fastq_download → set it so the stub stays light;
    # rnaseq does not → it must not appear on the rnaseq line.
    sh = codegen.render_stubs_sh(chain)
    fetchngs_block = sh.split("nextflow run nf-core/fetchngs")[1].split("echo")[0]
    rnaseq_block = sh.split("nextflow run nf-core/rnaseq")[1]
    assert "--skip_fastq_download true" in fetchngs_block
    assert "--skip_fastq_download" not in rnaseq_block


def test_stubs_tolerates_failure_and_is_isolated(chain):
    sh = codegen.render_stubs_sh(chain)
    assert "set -e" not in sh  # one pipeline failing must not stop the rest
    assert sh.count("|| true") == len(chain.steps)
    assert 'cd "$HERE/stubs"' in sh


def test_write_emits_executable_stubs_sh(chain, root):
    written = codegen.write(chain, root / "build_nf")
    p = root / "build_nf" / "stubs.sh"
    assert p in written and (p.stat().st_mode & 0o100)


def test_local_config_caps_resources(chain, root):
    written = codegen.write(chain, root / "build_nf")
    lc = root / "build_nf" / "local.config"
    assert lc in written
    text = lc.read_text()
    assert "resourceLimits" in text and "memory:" in text and "cpus:" in text


def test_runners_apply_the_local_cap(chain):
    # nf-core processes request more memory than a laptop has; both runners must
    # pass the cap so the pipeline still schedules locally.
    assert '-c "$HERE/local.config"' in codegen.render_run_sh(chain)
    assert "-c ${projectDir}/local.config" in codegen.render_main(chain)


def test_local_resources_are_sane():
    cpus, mem = codegen._local_resources()
    assert cpus >= 1 and mem >= 4


def test_config_records_the_chain(chain):
    cfg = codegen._config(chain)
    assert "sra=nf-core/fetchngs@1.12.0" in cfg
    assert "rna=nf-core/rnaseq@3.26.0" in cfg
    assert "nf_profile" in cfg


def test_config_maps_driver_profile_onto_nested_runs(chain):
    cfg = codegen._config(chain)
    # `-profile docker` on the driver must set the profile of the nested runs.
    assert "docker      { params.nf_profile = 'docker' }" in cfg
    assert "singularity { params.nf_profile = 'singularity' }" in cfg
