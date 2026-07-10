from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nfchain import registry, schema  # noqa: E402

REGISTRY = {
    "remote_workflows": [
        {
            "name": "fetchngs",
            "full_name": "nf-core/fetchngs",
            "description": "Fetch metadata and raw FastQ files from public databases",
            "default_branch": "master",
            "releases": [{"tag_name": "dev"}, {"tag_name": "1.12.0"}],
        },
        {
            "name": "rnaseq",
            "full_name": "nf-core/rnaseq",
            "description": "RNA sequencing analysis pipeline",
            "default_branch": "master",
            "releases": [{"tag_name": "3.26.0"}, {"tag_name": "3.25.0"}],
        },
        {
            "name": "atacseq",
            "full_name": "nf-core/atacseq",
            "description": "ATAC-seq peak-calling",
            "default_branch": "master",
            "releases": [],
        },
        {
            "name": "sarek",
            "full_name": "nf-core/sarek",
            "description": "Germline and somatic variant calling",
            "default_branch": "master",
            "releases": [{"tag_name": "3.4.0"}],
        },
    ]
}

FETCHNGS_SCHEMA = {
    "title": "nf-core/fetchngs pipeline parameters",
    "description": "Fetch FastQ files from public databases",
    "$defs": {
        "input_output_options": {
            "required": ["input", "outdir"],
            "properties": {
                "input": {
                    "type": "string",
                    "format": "file-path",
                    "mimetype": "text/csv",
                    "description": "File of SRA/ENA/GEO/DDBJ ids, one per line",
                },
                "nf_core_pipeline": {
                    "type": "string",
                    "enum": ["rnaseq", "atacseq", "viralrecon", "taxprofiler"],
                    "description": "Name of a downstream nf-core pipeline",
                },
                # A boolean enum: the schema spells it `false`, Python `False`.
                "force_sratools_download": {"type": "boolean", "enum": [False]},
                "download_method": {
                    "type": "string",
                    "enum": ["aspera", "ftp", "sratools"],
                    "default": "ftp",
                    "description": "How to download FastQ files",
                },
                "outdir": {"type": "string", "format": "directory-path"},
            },
        },
        "generic_options": {"properties": {"version": {"type": "boolean"}}},
    },
}

RNASEQ_SCHEMA = {
    "title": "nf-core/rnaseq pipeline parameters",
    "description": "RNA sequencing analysis pipeline",
    "$defs": {
        "input_output_options": {
            "required": ["input", "outdir"],
            "properties": {
                "input": {
                    "type": "string",
                    "format": "file-path",
                    "mimetype": "text/csv",
                    "pattern": r"^\S+\.csv$",
                    "description": "Path to the sample sheet",
                },
                "outdir": {"type": "string", "format": "directory-path"},
            },
        },
        "reference_genome_options": {
            "properties": {
                "genome": {"type": "string", "description": "iGenomes reference key"},
                "aligner": {
                    "type": "string",
                    "enum": ["star_salmon", "star_rsem", "hisat2"],
                    "default": "star_salmon",
                    "description": "Alignment algorithm",
                },
            }
        },
        "generic_options": {"properties": {"version": {"type": "boolean"}}},
    },
}

ATACSEQ_SCHEMA = {
    "title": "nf-core/atacseq pipeline parameters",
    "description": "ATAC-seq",
    "$defs": {
        "input_output_options": {
            "required": ["input", "outdir"],
            "properties": {
                "input": {
                    "type": "string",
                    "format": "file-path",
                    "mimetype": "text/csv",
                    "description": "Samplesheet",
                },
                "outdir": {"type": "string", "format": "directory-path"},
            },
        }
    },
}

SAREK_SCHEMA = {
    "title": "nf-core/sarek pipeline parameters",
    "description": "Variant calling",
    "$defs": {
        "input_output_options": {
            "required": ["input", "outdir"],
            "properties": {
                "input": {
                    "type": "string",
                    "format": "file-path",
                    "mimetype": "text/csv",
                    "description": "Samplesheet",
                },
                "outdir": {"type": "string", "format": "directory-path"},
            },
        }
    },
}

SCHEMAS = {
    "fetchngs": FETCHNGS_SCHEMA,
    "rnaseq": RNASEQ_SCHEMA,
    "atacseq": ATACSEQ_SCHEMA,
    "sarek": SAREK_SCHEMA,
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Serve the registry and every schema from fixtures — no network in tests."""

    def fake_registry_fetch(url, root, ttl=None, refresh=False):
        assert url == registry.PIPELINES_URL, url
        return REGISTRY

    def fake_schema_fetch(url, root, ttl=None, refresh=False):
        # https://raw.githubusercontent.com/nf-core/<name>/<rev>/nextflow_schema.json
        name = url.split("/nf-core/")[1].split("/")[0]
        return SCHEMAS[name]

    monkeypatch.setattr(registry, "fetch_json", fake_registry_fetch)
    monkeypatch.setattr(schema, "fetch_json", fake_schema_fetch)


@pytest.fixture
def root(tmp_path):
    return tmp_path
