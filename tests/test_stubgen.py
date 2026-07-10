from __future__ import annotations

import json
from pathlib import Path

import pytest

from nfchain import dsl, graph, stubgen

SRC = (
    "from nf-core import sratools\n"
    "from nf-core import rnaseq\n"
    "sra = sratools(ids=['SRR1'])\n"
    "rna = rnaseq(input=sra.samplesheet)\n"
)


@pytest.fixture
def chain(root):
    return graph.resolve(dsl.parse(SRC, Path("f.flow")), root)


def test_stub_declares_a_function_per_import(chain):
    stub = stubgen.render_stub(chain)
    assert "def sratools(" in stub
    assert "def rnaseq(" in stub


def test_stub_uses_the_imported_name_not_the_pipeline_name(chain):
    stub = stubgen.render_stub(chain)
    assert "def fetchngs(" not in stub
    assert "nf-core/fetchngs@1.12.0" in stub  # ...but the docstring is honest


def test_enums_become_literals(chain):
    stub = stubgen.render_stub(chain)
    assert 'aligner: Literal["star_salmon", "star_rsem", "hisat2"]' in stub


def test_boolean_enum_uses_python_spelling_not_json(chain):
    # The schema says `false`; Python says `False`. `ast.parse` accepts both
    # (as a bare name), a type checker does not.
    stub = stubgen.render_stub(chain)
    assert "force_sratools_download: Literal[False]" in stub
    assert "Literal[false]" not in stub


def test_accession_input_is_typed_as_ids_not_a_path(chain):
    stub = stubgen.render_stub(chain)
    assert "ids: str | list[str]" in stub
    assert "input:" not in stub.split("def rnaseq(")[0].split("def sratools(")[1]


def test_path_params_accept_upstream_artifacts(chain):
    stub = stubgen.render_stub(chain)
    assert "input: str | _Artifact" in stub


def test_outputs_are_typed_attributes(chain):
    stub = stubgen.render_stub(chain)
    assert "class _SratoolsOut(_Output):" in stub
    assert "    samplesheet: _Artifact" in stub


def test_every_param_is_optional_so_autowiring_typechecks(chain):
    stub = stubgen.render_stub(chain)
    for line in stub.splitlines():
        if line.startswith("    ") and ": " in line and not line.startswith('    """'):
            if line.strip().endswith(","):
                assert line.rstrip(",").endswith("...")


def test_managed_params_are_not_offered(chain):
    stub = stubgen.render_stub(chain)
    assert "outdir:" not in stub.replace("outdir: _Artifact", "")


def test_boilerplate_params_are_not_offered(chain):
    stub = stubgen.render_stub(chain)
    assert "version: bool" not in stub


def test_params_schema_validates_the_params_file(chain):
    sch = stubgen.render_params_schema(chain.steps[1].sch)
    assert sch["additionalProperties"] is False
    assert sch["properties"]["genome"]["type"] == "string"
    assert sch["properties"]["aligner"]["enum"] == ["star_salmon", "star_rsem", "hisat2"]
    assert sch["properties"]["input"]["pattern"] == r"^\S+\.csv$"
    assert "outdir" in sch["properties"]


def test_sync_writes_stubs_schemas_and_vscode_settings(chain, root):
    written = stubgen.sync(chain, root)
    names = {p.relative_to(root).as_posix() for p in written}
    assert ".nfchain/stubs/nf_core/__init__.pyi" in names
    assert ".nfchain/schemas/fetchngs.params.schema.json" in names
    assert ".nfchain/schemas/rnaseq.params.schema.json" in names

    settings = json.loads((root / ".vscode" / "settings.json").read_text())
    assert settings["python.analysis.stubPath"] == ".nfchain/stubs"
    assert settings["files.associations"]["*.flow"] == "python"
    matches = [m for s in settings["json.schemas"] for m in s["fileMatch"]]
    assert "/build_nf/params/rna.json" in matches


def test_sync_preserves_unrelated_vscode_settings(chain, root):
    vs = root / ".vscode"
    vs.mkdir()
    (vs / "settings.json").write_text(json.dumps({"editor.tabSize": 2}))

    stubgen.sync(chain, root)
    settings = json.loads((vs / "settings.json").read_text())
    assert settings["editor.tabSize"] == 2
    assert "python.analysis.stubPath" in settings


def test_generated_stub_is_valid_python(chain):
    import ast

    ast.parse(stubgen.render_stub(chain))
