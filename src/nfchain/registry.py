"""Resolve a bare name like `rnaseq` to a real, pinned nf-core pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .cache import fetch_json
from .contracts import ALIASES

PIPELINES_URL = "https://nf-co.re/pipelines.json"


class UnknownPipeline(LookupError):
    def __init__(self, name: str, suggestions: list[str]):
        self.name = name
        self.suggestions = suggestions
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        super().__init__(f"'{name}' is not an nf-core pipeline.{hint}")


@dataclass(frozen=True)
class PipelineRef:
    """A concrete, version-pinned pipeline."""

    name: str  # e.g. "fetchngs"
    full_name: str  # e.g. "nf-core/fetchngs"
    revision: str  # e.g. "1.12.0" or "master"
    description: str
    imported_as: str  # the name the user actually typed

    @property
    def schema_url(self) -> str:
        return (
            f"https://raw.githubusercontent.com/{self.full_name}/"
            f"{self.revision}/nextflow_schema.json"
        )


def load_registry(root: Path, refresh: bool = False) -> dict[str, dict]:
    doc = fetch_json(PIPELINES_URL, root, refresh=refresh)
    return {wf["name"]: wf for wf in doc.get("remote_workflows", [])}


def _latest_release(wf: dict) -> str:
    """Newest release tag, or the default branch if the pipeline has none."""
    releases = [r["tag_name"] for r in wf.get("releases", []) if r.get("tag_name")]
    # nf-co.re lists releases newest-first; `dev` is a pseudo-release, not a tag.
    for tag in releases:
        if tag != "dev":
            return tag
    return wf.get("default_branch", "master")


def _suggest(name: str, known: list[str], limit: int = 3) -> list[str]:
    import difflib

    return difflib.get_close_matches(name, known, n=limit, cutoff=0.5)


def resolve(name: str, root: Path, revision: str | None = None, refresh: bool = False) -> PipelineRef:
    """Map an imported name to a pinned PipelineRef.

    Applies aliases first, so `sratools` lands on the pipeline that actually
    exists (`fetchngs`) rather than the sra-tools *module* it's named after.
    """
    canonical = ALIASES.get(name, name)
    registry = load_registry(root, refresh=refresh)

    wf = registry.get(canonical)
    if wf is None:
        raise UnknownPipeline(name, _suggest(canonical, sorted(registry)))

    return PipelineRef(
        name=canonical,
        full_name=wf["full_name"],
        revision=revision or _latest_release(wf),
        description=wf.get("description") or "",
        imported_as=name,
    )
