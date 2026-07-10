"""Resolve a parsed Flow into a validated, wired chain of pipelines."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from . import contracts, registry, schema
from .dsl import Flow, Ref, Step

# nf-chain owns these: they're set per-step by the generated workflow.
MANAGED_PARAMS = frozenset({"outdir"})


class ChainError(RuntimeError):
    def __init__(self, msg: str, path: Path, lineno: int):
        super().__init__(msg)
        self.path = path
        self.lineno = lineno

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: {self.args[0]}"


@dataclass
class Wire:
    """A resolved edge: `consumer.param` is fed by `producer`'s artifact."""

    param: str
    source_step: str
    artifact: contracts.Artifact
    auto: bool  # inferred, not written by the user


@dataclass
class ResolvedStep:
    step: Step
    ref: registry.PipelineRef
    sch: schema.PipelineSchema
    params: dict[str, object] = field(default_factory=dict)  # literal params
    wires: list[Wire] = field(default_factory=list)
    accession_input: list[str] | None = None  # fetchngs-style id list
    auto_params: set[str] = field(default_factory=set)  # params nf-chain filled in

    @property
    def var(self) -> str:
        return self.step.var

    @property
    def name(self) -> str:
        return self.ref.name

    @property
    def process(self) -> str:
        return f"NFCORE_{self.var.upper()}"


@dataclass
class Chain:
    flow: Flow
    steps: list[ResolvedStep]

    def by_var(self, var: str) -> ResolvedStep | None:
        return next((s for s in self.steps if s.var == var), None)


def _unknown_param(step: Step, key: str, sch: schema.PipelineSchema, path: Path) -> ChainError:
    close = difflib.get_close_matches(key, list(sch.params), n=3, cutoff=0.5)
    hint = f" Did you mean: {', '.join(close)}?" if close else ""
    return ChainError(
        f"nf-core/{sch.ref.name} has no param '{key}'.{hint}", path, step.lineno
    )


def _resolve_ref(
    value: Ref, consumer: ResolvedStep, prior: dict[str, ResolvedStep], param: str, path: Path
) -> Wire:
    producer = prior.get(value.step)
    if producer is None:
        raise ChainError(f"unknown step '{value.step}'", path, consumer.step.lineno)

    art = next((a for a in contracts.emits(producer.name) if a.name == value.attr), None)
    if art is None:
        available = ", ".join(a.name for a in contracts.emits(producer.name)) or "none"
        raise ChainError(
            f"nf-core/{producer.name} does not emit '{value.attr}' "
            f"(available: {available})",
            path,
            consumer.step.lineno,
        )
    return Wire(param=param, source_step=producer.var, artifact=art, auto=False)


def _autowire(consumer: ResolvedStep, prior: list[ResolvedStep], path: Path) -> Wire | None:
    """Feed a consumer's required samplesheet from the nearest upstream emitter."""
    target = consumer.sch.primary_input()
    if target is None or target.name in consumer.params:
        return None
    if any(w.param == target.name for w in consumer.wires):
        return None

    for producer in reversed(prior):
        art = contracts.find_emit(producer.name, contracts.SAMPLESHEET)
        if art is not None:
            return Wire(param=target.name, source_step=producer.var, artifact=art, auto=True)
    return None


def _link_fetchngs(producer: ResolvedStep, consumer: ResolvedStep) -> None:
    """fetchngs can pre-format its samplesheet for a named downstream pipeline.

    This is the pipeline's own chaining hook (`--nf_core_pipeline rnaseq`), so
    use it rather than hoping the generic samplesheet happens to line up.
    """
    if producer.name != "fetchngs":
        return
    param = producer.sch.params.get("nf_core_pipeline")
    if param is None:
        return
    if "nf_core_pipeline" in producer.params:
        return  # user was explicit; don't second-guess them
    if param.enum and consumer.name not in param.enum:
        # fetchngs only knows how to format a samplesheet for a few pipelines.
        # For anything else its generic samplesheet is the best we can do.
        return
    producer.params["nf_core_pipeline"] = consumer.name
    producer.auto_params.add("nf_core_pipeline")


def resolve(flow: Flow, root: Path, refresh: bool = False) -> Chain:
    resolved: list[ResolvedStep] = []
    by_var: dict[str, ResolvedStep] = {}

    for step in flow.steps:
        ref = registry.resolve(step.imported_as, root, revision=step.revision, refresh=refresh)
        sch = schema.load(ref, root, refresh=refresh)
        rs = ResolvedStep(step=step, ref=ref, sch=sch)

        # 1. Bind the user's kwargs to real params.
        for key, value in step.kwargs.items():
            param = contracts.resolve_param_alias(ref.name, key)
            if param not in sch.params:
                raise _unknown_param(step, key, sch, flow.path)
            if param in MANAGED_PARAMS:
                raise ChainError(
                    f"'{param}' is managed by nf-chain; set it with `--outdir`",
                    flow.path,
                    step.lineno,
                )
            if isinstance(value, Ref):
                rs.wires.append(_resolve_ref(value, rs, by_var, param, flow.path))
            else:
                rs.params[param] = value

        # 2. An accession list is a value, not a path — codegen materialises it.
        if ref.name in contracts.ACCESSION_INPUT and "input" in rs.params:
            ids = rs.params.pop("input")
            rs.accession_input = [ids] if isinstance(ids, str) else list(ids)

        # 3. Chain: fill a missing required samplesheet from upstream.
        auto = _autowire(rs, resolved, flow.path)
        if auto is not None:
            rs.wires.append(auto)

        for wire in rs.wires:
            producer = by_var[wire.source_step]
            _link_fetchngs(producer, rs)

        # 4. Everything required must now be satisfied.
        supplied = set(rs.params) | {w.param for w in rs.wires} | MANAGED_PARAMS
        if rs.accession_input is not None:
            supplied.add("input")
        missing = [p.name for p in sch.required if p.name not in supplied]
        if missing:
            raise ChainError(
                f"nf-core/{ref.name} requires {', '.join(missing)} — pass it "
                f"explicitly, or chain it from a step that emits a samplesheet",
                flow.path,
                step.lineno,
            )

        resolved.append(rs)
        by_var[rs.var] = rs

    return Chain(flow=flow, steps=resolved)
