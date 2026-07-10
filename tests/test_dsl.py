from __future__ import annotations

from pathlib import Path

import pytest

from nfchain import dsl

FLOW = Path("f.flow")


def parse(src: str) -> dsl.Flow:
    return dsl.parse(src, FLOW)


def test_hyphenated_import_is_normalized():
    assert dsl.normalize("from nf-core import rnaseq") == "from nf_core import rnaseq"


def test_underscored_import_also_works():
    flow = parse("from nf_core import rnaseq\nx = rnaseq(genome='GRCh38')\n")
    assert flow.steps[0].imported_as == "rnaseq"


def test_parses_imports_steps_and_refs():
    flow = parse(
        "from nf-core import sratools\n"
        "from nf-core import rnaseq\n"
        "sra = sratools(ids=['SRR1', 'SRR2'])\n"
        "rna = rnaseq(input=sra.samplesheet, genome='GRCh38')\n"
    )
    assert flow.imports == {"sratools": "sratools", "rnaseq": "rnaseq"}
    sra, rna = flow.steps
    assert sra.var == "sra" and sra.kwargs["ids"] == ["SRR1", "SRR2"]
    assert rna.kwargs["input"] == dsl.Ref("sra", "samplesheet")
    assert rna.kwargs["genome"] == "GRCh38"


def test_import_alias():
    flow = parse("from nf-core import rnaseq as quant\nq = quant()\n")
    assert flow.steps[0].imported_as == "rnaseq"


def test_rev_is_lifted_off_kwargs():
    flow = parse("from nf-core import rnaseq\nr = rnaseq(rev='3.14.0')\n")
    assert flow.steps[0].revision == "3.14.0"
    assert "rev" not in flow.steps[0].kwargs


def test_docstring_is_allowed():
    flow = parse('"""doc"""\nfrom nf-core import rnaseq\nr = rnaseq()\n')
    assert len(flow.steps) == 1


@pytest.mark.parametrize(
    "src, needle",
    [
        ("from os import path\n", "only `from nf-core import ...`"),
        ("from nf-core import rnaseq\nr = rnaseq('x')\n", "must be keywords"),
        ("from nf-core import rnaseq\nr = rnaseq(input=other.x)\n", "unknown step 'other'"),
        ("from nf-core import rnaseq\nr = rnaseq()\nr = rnaseq()\n", "defined twice"),
        ("from nf-core import rnaseq\nr = rnaseq(**{})\n", "**kwargs"),
        ("from nf-core import rnaseq\nprint(1)\n", "may only contain"),
        ("from nf-core import rnaseq\nr = rnaseq(input=rnaseq)\n", "is a step, not a value"),
    ],
)
def test_errors(src, needle):
    with pytest.raises(dsl.DslError) as e:
        parse(src)
    assert needle in str(e.value)


def test_error_carries_line_number():
    with pytest.raises(dsl.DslError) as e:
        parse("from nf-core import rnaseq\n\nprint(1)\n")
    assert e.value.lineno == 3
    assert str(e.value).startswith("f.flow:3:")


def test_step_must_be_imported():
    with pytest.raises(dsl.DslError, match="never imported"):
        parse("from nf-core import rnaseq\nx = sarek()\n")
