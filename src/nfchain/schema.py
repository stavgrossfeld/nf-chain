"""Fetch and flatten a pipeline's `nextflow_schema.json` into a param list.

This is the "pull the inputs on the fly" half of nf-chain: the set of things a
pipeline accepts is never hardcoded, it's read from the pipeline's own schema at
the pinned revision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cache import fetch_json
from .registry import PipelineRef

# Params every nf-core pipeline inherits from the template. They're noise in
# completions and are handled by nf-chain itself, so they're hidden by default.
BOILERPLATE_GROUPS = {
    "institutional_config_options",
    "generic_options",
    "max_job_request_options",
}


@dataclass(frozen=True)
class Param:
    name: str
    type: str = "string"
    description: str = ""
    help_text: str = ""
    default: Any = None
    enum: tuple[str, ...] = ()
    fmt: str | None = None  # nf-core "format": file-path | directory-path
    mimetype: str | None = None  # e.g. text/csv
    pattern: str | None = None
    required: bool = False
    group: str = ""

    @property
    def is_path(self) -> bool:
        return self.fmt in ("file-path", "directory-path")

    @property
    def is_samplesheet(self) -> bool:
        """A CSV/TSV file input — the currency of nf-core pipeline chaining."""
        return self.fmt == "file-path" and (self.mimetype or "").startswith("text/")


@dataclass
class PipelineSchema:
    ref: PipelineRef
    title: str
    description: str
    params: dict[str, Param] = field(default_factory=dict)

    @property
    def required(self) -> list[Param]:
        return [p for p in self.params.values() if p.required]

    def user_params(self) -> list[Param]:
        """Params worth showing a developer: required first, then optional."""
        visible = [p for p in self.params.values() if p.group not in BOILERPLATE_GROUPS]
        return sorted(visible, key=lambda p: (not p.required, p.name))

    def primary_input(self) -> Param | None:
        """The required param a chained upstream pipeline should feed."""
        for p in self.required:
            if p.name == "input" and p.is_samplesheet:
                return p
        for p in self.required:
            if p.is_samplesheet:
                return p
        return None


def _defs(doc: dict) -> dict:
    # nf-core moved definitions -> $defs when it adopted JSON Schema 2020-12.
    return doc.get("$defs") or doc.get("definitions") or {}


def _param_from_prop(name: str, prop: dict, group: str, required: bool) -> Param:
    return Param(
        name=name,
        type=prop.get("type", "string"),
        description=prop.get("description", "") or "",
        help_text=prop.get("help_text", "") or "",
        default=prop.get("default"),
        enum=tuple(prop.get("enum", ()) or ()),
        fmt=prop.get("format"),
        mimetype=prop.get("mimetype"),
        pattern=prop.get("pattern"),
        required=required,
        group=group,
    )


def load(ref: PipelineRef, root: Path, refresh: bool = False) -> PipelineSchema:
    doc = fetch_json(ref.schema_url, root, refresh=refresh)

    params: dict[str, Param] = {}
    for group_name, group in _defs(doc).items():
        req = set(group.get("required", []))
        for pname, prop in (group.get("properties") or {}).items():
            params[pname] = _param_from_prop(pname, prop, group_name, pname in req)

    # Some pipelines declare params at the top level, outside any group.
    top_req = set(doc.get("required", []))
    for pname, prop in (doc.get("properties") or {}).items():
        if pname not in params:
            params[pname] = _param_from_prop(pname, prop, "", pname in top_req)

    return PipelineSchema(
        ref=ref,
        title=doc.get("title", ref.full_name),
        description=doc.get("description", ref.description),
        params=params,
    )
