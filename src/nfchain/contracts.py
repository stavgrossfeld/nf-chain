"""Output contracts — the part nf-core schemas can't tell us.

`nextflow_schema.json` describes a pipeline's *inputs* exhaustively, so nf-chain
reads those live. It says nothing about what a pipeline *emits*, so chaining
needs a small curated table of published outputs keyed by artifact kind.

Adding a pipeline here is the only hand-written step; everything else about it
is discovered from its schema at the pinned revision.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Import-name aliases
# ---------------------------------------------------------------------------
# `sratools` is an nf-core *module*, not a pipeline. The pipeline that wraps it
# to pull reads from SRA/ENA/GEO/DDBJ is `fetchngs`. Users reach for the tool
# name they know, so map it.
ALIASES: dict[str, str] = {
    "sratools": "fetchngs",
    "sra_tools": "fetchngs",
    "sra": "fetchngs",
    "fastq_dl": "fetchngs",
}

# Friendlier keyword names a flow file may use, mapped onto real params.
# Several friendly names may share a target, so this is not invertible.
PARAM_ALIASES: dict[str, dict[str, str]] = {
    "fetchngs": {"ids": "input", "accessions": "input"},
}

# The one friendly name to advertise in editor completions, per real param.
DISPLAY_ALIASES: dict[str, dict[str, str]] = {
    "fetchngs": {"input": "ids"},
}

# Artifact kinds. Wiring is a match on kind, not on filename.
SAMPLESHEET = "samplesheet/nf-core"
COUNTS = "matrix/counts"
REPORT = "report/multiqc"
BAM = "alignment/bam"
VCF = "variants/vcf"


@dataclass(frozen=True)
class Artifact:
    """Something a pipeline publishes under its `--outdir`."""

    name: str  # attribute name: `sra.samplesheet`
    kind: str  # matched against a consumer's input kind
    path: str  # path relative to the pipeline's outdir


EMITS: dict[str, tuple[Artifact, ...]] = {
    "fetchngs": (
        Artifact("samplesheet", SAMPLESHEET, "samplesheet/samplesheet.csv"),
        Artifact("metadata", "table/tsv", "metadata/*.tsv"),
    ),
    "rnaseq": (
        Artifact("counts", COUNTS, "star_salmon/salmon.merged.gene_counts.tsv"),
        Artifact("bam", BAM, "star_salmon/*.markdup.sorted.bam"),
        Artifact("multiqc", REPORT, "multiqc/star_salmon/multiqc_report.html"),
    ),
    "sarek": (
        Artifact("vcf", VCF, "variant_calling/**/*.vcf.gz"),
        Artifact("bam", BAM, "preprocessing/recalibrated/**/*.bam"),
        Artifact("multiqc", REPORT, "multiqc/multiqc_report.html"),
    ),
    "atacseq": (
        Artifact("bam", BAM, "bwa/merged_library/*.bam"),
        Artifact("multiqc", REPORT, "multiqc/*/multiqc_report.html"),
    ),
}

# Pipelines whose `input` is a list of accessions written to a file, not a
# samplesheet the user already has on disk.
ACCESSION_INPUT: frozenset[str] = frozenset({"fetchngs"})


def emits(pipeline: str) -> tuple[Artifact, ...]:
    return EMITS.get(pipeline, ())


def find_emit(pipeline: str, kind: str) -> Artifact | None:
    for art in emits(pipeline):
        if art.kind == kind:
            return art
    return None


def resolve_param_alias(pipeline: str, key: str) -> str:
    """Friendly keyword -> real param name (`ids` -> `input`)."""
    return PARAM_ALIASES.get(pipeline, {}).get(key, key)


def display_alias(pipeline: str) -> dict[str, str]:
    """Real param name -> the name to show in completions (`input` -> `ids`)."""
    return DISPLAY_ALIASES.get(pipeline, {})
