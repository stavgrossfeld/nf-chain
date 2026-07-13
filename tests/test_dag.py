from __future__ import annotations

from pathlib import Path

import pytest

from nfchain import dag, dsl, graph

SRC = (
    "from nf-core import fetchngs\n"
    "from nf-core import rnaseq\n"
    "sra = fetchngs(ids=['SRR1', 'SRR2'])\n"
    "rna = rnaseq(input=sra.samplesheet, genome='GRCh38')\n"
)


@pytest.fixture
def chain(root):
    return graph.resolve(dsl.parse(SRC, Path("f.flow")), root)


def test_mermaid_has_a_node_per_step(chain):
    m = dag.render_mermaid(chain)
    assert m.startswith("```mermaid")
    assert 'sra["' in m and 'rna["' in m
    assert "nf-core/fetchngs@1.12.0" in m
    assert "nf-core/rnaseq@3.26.0" in m


def test_mermaid_edge_is_labelled_with_param_and_kind(chain):
    m = dag.render_mermaid(chain)
    assert "sra -->|input: samplesheet/nf-core| rna" in m


def test_mermaid_shows_params_and_accessions(chain):
    m = dag.render_mermaid(chain)
    assert "ids = SRR1, SRR2" in m
    assert "genome = GRCh38" in m


def test_auto_wire_is_marked(root):
    c = graph.resolve(
        dsl.parse(
            "from nf-core import fetchngs\n"
            "from nf-core import rnaseq\n"
            "s = fetchngs(ids='SRR1')\n"
            "r = rnaseq(genome='GRCh38')\n",
            Path("f.flow"),
        ),
        root,
    )
    m = dag.render_mermaid(c)
    assert "~auto~" in m


def test_dot_is_a_digraph_with_edges(chain):
    d = dag.render_dot(chain)
    assert d.startswith("digraph nfchain {")
    assert 'sra -> rna [label="input (samplesheet/nf-core)"];' in d
    assert d.rstrip().endswith("}")


def test_parens_in_labels_do_not_break_mermaid(chain):
    # raw parentheses would be read as mermaid node syntax
    m = dag.render_mermaid(chain)
    assert "(" not in m.split("flowchart TD")[1].rsplit("```", 1)[0]


def test_unknown_format_errors(chain):
    with pytest.raises(ValueError, match="unknown dag format"):
        dag.render(chain, "svg")
