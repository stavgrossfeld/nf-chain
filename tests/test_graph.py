from __future__ import annotations

from pathlib import Path

import pytest

from nfchain import dsl, graph, registry

FLOW = Path("f.flow")


def chain(src: str, root: Path) -> graph.Chain:
    return graph.resolve(dsl.parse(src, FLOW), root)


def test_sratools_alias_resolves_to_fetchngs(root):
    c = chain("from nf-core import sratools\ns = sratools(ids='SRR1')\n", root)
    assert c.steps[0].ref.full_name == "nf-core/fetchngs"
    assert c.steps[0].ref.imported_as == "sratools"


def test_latest_release_skips_dev_tag(root):
    ref = registry.resolve("fetchngs", root)
    assert ref.revision == "1.12.0"


def test_falls_back_to_default_branch_without_releases(root):
    ref = registry.resolve("atacseq", root)
    assert ref.revision == "master"


def test_explicit_rev_is_honoured(root):
    c = chain("from nf-core import rnaseq\nr = rnaseq(rev='3.25.0', input='s.csv')\n", root)
    assert c.steps[0].ref.revision == "3.25.0"


def test_unknown_pipeline_suggests(root):
    with pytest.raises(registry.UnknownPipeline, match="Did you mean: rnaseq"):
        chain("from nf-core import rnaseqq\nr = rnaseqq()\n", root)


def test_accession_input_is_lifted_out_of_params(root):
    c = chain("from nf-core import sratools\ns = sratools(ids=['SRR1','SRR2'])\n", root)
    step = c.steps[0]
    assert step.accession_input == ["SRR1", "SRR2"]
    assert "input" not in step.params


def test_scalar_accession_becomes_a_list(root):
    c = chain("from nf-core import sratools\ns = sratools(ids='SRR1')\n", root)
    assert c.steps[0].accession_input == ["SRR1"]


def test_explicit_wire(root):
    c = chain(
        "from nf-core import sratools\n"
        "from nf-core import rnaseq\n"
        "s = sratools(ids='SRR1')\n"
        "r = rnaseq(input=s.samplesheet)\n",
        root,
    )
    wire = c.steps[1].wires[0]
    assert (wire.param, wire.source_step, wire.auto) == ("input", "s", False)
    assert wire.artifact.path == "samplesheet/samplesheet.csv"


def test_missing_input_is_autowired_from_upstream_samplesheet(root):
    c = chain(
        "from nf-core import sratools\n"
        "from nf-core import rnaseq\n"
        "s = sratools(ids='SRR1')\n"
        "r = rnaseq(genome='GRCh38')\n",
        root,
    )
    wire = c.steps[1].wires[0]
    assert (wire.param, wire.source_step, wire.auto) == ("input", "s", True)
    assert wire.artifact.kind == "samplesheet/nf-core"


def test_fetchngs_is_told_its_downstream_pipeline(root):
    c = chain(
        "from nf-core import sratools\n"
        "from nf-core import rnaseq\n"
        "s = sratools(ids='SRR1')\n"
        "r = rnaseq()\n",
        root,
    )
    sra = c.steps[0]
    assert sra.params["nf_core_pipeline"] == "rnaseq"
    assert "nf_core_pipeline" in sra.auto_params


def test_fetchngs_hint_is_skipped_when_downstream_is_not_in_its_enum(root):
    # fetchngs can only pre-format its samplesheet for a handful of pipelines;
    # sarek is not one of them, so the param must be left alone rather than set
    # to a value the nested run would reject. sarek's `input` is optional, so
    # the wire is explicit here.
    c = chain(
        "from nf-core import fetchngs\n"
        "from nf-core import sarek\n"
        "s = fetchngs(ids='SRR1')\n"
        "v = sarek(input=s.samplesheet)\n",
        root,
    )
    assert "nf_core_pipeline" not in c.steps[0].params
    assert c.steps[1].wires[0].source_step == "s"


def test_required_param_with_a_default_is_not_missing(root):
    # sarek marks `step` required but gives it default 'mapping'; nf-core fills
    # it in, so `sarek()` alone must resolve rather than erroring.
    c = chain("from nf-core import sarek\nv = sarek()\n", root)
    assert c.steps[0].params == {}


def test_optional_input_is_not_autowired(root):
    # sarek's samplesheet is optional (multi-entry pipeline), so nf-chain does
    # not guess the wire — you ask for it explicitly.
    c = chain(
        "from nf-core import fetchngs\n"
        "from nf-core import sarek\n"
        "s = fetchngs(ids='SRR1')\n"
        "v = sarek()\n",
        root,
    )
    assert c.steps[1].wires == []


def test_explicit_nf_core_pipeline_is_not_overridden(root):
    c = chain(
        "from nf-core import sratools\n"
        "from nf-core import rnaseq\n"
        "s = sratools(ids='SRR1', nf_core_pipeline='atacseq')\n"
        "r = rnaseq()\n",
        root,
    )
    assert c.steps[0].params["nf_core_pipeline"] == "atacseq"
    assert "nf_core_pipeline" not in c.steps[0].auto_params


def test_unknown_param_suggests_a_real_one(root):
    with pytest.raises(graph.ChainError, match="Did you mean: genome"):
        chain("from nf-core import rnaseq\nr = rnaseq(genom='x', input='s.csv')\n", root)


def test_missing_required_param_without_upstream(root):
    with pytest.raises(graph.ChainError, match="requires input"):
        chain("from nf-core import rnaseq\nr = rnaseq(genome='GRCh38')\n", root)


def test_outdir_is_reserved(root):
    with pytest.raises(graph.ChainError, match="managed by nf-chain"):
        chain("from nf-core import rnaseq\nr = rnaseq(input='s.csv', outdir='x')\n", root)


def test_unknown_artifact_lists_available(root):
    with pytest.raises(graph.ChainError, match="does not emit 'reads'"):
        chain(
            "from nf-core import sratools\n"
            "from nf-core import rnaseq\n"
            "s = sratools(ids='SRR1')\n"
            "r = rnaseq(input=s.reads)\n",
            root,
        )


def test_boilerplate_params_are_hidden_but_still_valid(root):
    c = chain("from nf-core import rnaseq\nr = rnaseq(input='s.csv', version=True)\n", root)
    assert "version" in c.steps[0].params
    assert "version" not in {p.name for p in c.steps[0].sch.user_params()}
