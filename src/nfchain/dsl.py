"""Parse a `.flow` file into steps.

A flow file is Python, with one concession: `nf-core` is spelled with a hyphen
because that's what the pipelines are actually called. nf-chain rewrites that
single token to `nf_core` and then parses with `ast`, so the rest of the file is
real Python syntax and the type stubs in `.nfchain/stubs` light up in VSCode.

    from nf-core import sratools
    from nf-core import rnaseq

    sra = sratools(ids=["SRR6357070", "SRR6357071"])
    rna = rnaseq(input=sra.samplesheet, genome="GRCh38")

Flow files are parsed, never executed.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODULE = "nf_core"
_HYPHEN_IMPORT = re.compile(r"^(\s*from\s+)nf-core(\s+import\s+)", re.MULTILINE)


class DslError(SyntaxError):
    """A problem with the flow file, anchored to a line."""

    def __init__(self, msg: str, path: Path, lineno: int):
        super().__init__(msg)
        self.path = path
        self.lineno = lineno

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: {self.args[0]}"


@dataclass(frozen=True)
class Ref:
    """A reference to an upstream step's output: `sra.samplesheet`."""

    step: str
    attr: str

    def __str__(self) -> str:
        return f"{self.step}.{self.attr}"


@dataclass
class Step:
    var: str  # `rna`
    imported_as: str  # `rnaseq` (pre-alias, as the user typed it)
    lineno: int
    kwargs: dict[str, Any | Ref] = field(default_factory=dict)
    revision: str | None = None  # from `rev="3.14.0"`


@dataclass
class Flow:
    path: Path
    imports: dict[str, str]  # local name -> imported name
    steps: list[Step]


def normalize(source: str) -> str:
    """`from nf-core import x` -> `from nf_core import x`."""
    return _HYPHEN_IMPORT.sub(rf"\1{MODULE}\2", source)


def _literal(node: ast.AST, path: Path) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        raise DslError(
            "argument must be a literal (str/number/bool/list) or an upstream "
            "output like `sra.samplesheet`",
            path,
            getattr(node, "lineno", 0),
        ) from None


def _value(node: ast.AST, path: Path, known_steps: set[str]) -> Any | Ref:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        step = node.value.id
        if step not in known_steps:
            raise DslError(f"unknown step '{step}'", path, node.lineno)
        return Ref(step, node.attr)
    if isinstance(node, ast.Name):
        raise DslError(
            f"'{node.id}' is a step, not a value — did you mean "
            f"`{node.id}.<output>`?",
            path,
            node.lineno,
        )
    return _literal(node, path)


def _parse_call(call: ast.Call, var: str, path: Path, known_steps: set[str]) -> Step:
    if not isinstance(call.func, ast.Name):
        raise DslError("only direct pipeline calls are supported", path, call.lineno)
    if call.args:
        raise DslError(
            "pipeline arguments must be keywords, e.g. `rnaseq(input=...)`",
            path,
            call.lineno,
        )

    step = Step(var=var, imported_as=call.func.id, lineno=call.lineno)
    for kw in call.keywords:
        if kw.arg is None:
            raise DslError("`**kwargs` is not supported", path, call.lineno)
        if kw.arg == "rev":
            step.revision = _literal(kw.value, path)
            continue
        step.kwargs[kw.arg] = _value(kw.value, path, known_steps)
    return step


def parse(source: str, path: Path) -> Flow:
    try:
        tree = ast.parse(normalize(source), filename=str(path))
    except SyntaxError as e:
        raise DslError(e.msg or "invalid syntax", path, e.lineno or 0) from None

    imports: dict[str, str] = {}
    steps: list[Step] = []
    known: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.module != MODULE:
                raise DslError(
                    f"only `from nf-core import ...` is supported, got "
                    f"`from {node.module} import ...`",
                    path,
                    node.lineno,
                )
            for alias in node.names:
                imports[alias.asname or alias.name] = alias.name
            continue

        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise DslError("each step needs exactly one name", path, node.lineno)
            if not isinstance(node.value, ast.Call):
                raise DslError("a step must call an imported pipeline", path, node.lineno)

            var = node.targets[0].id
            step = _parse_call(node.value, var, path, known)
            if step.imported_as not in imports:
                raise DslError(
                    f"'{step.imported_as}' was never imported from nf-core",
                    path,
                    node.lineno,
                )
            if var in known:
                raise DslError(f"step '{var}' is defined twice", path, node.lineno)
            steps.append(step)
            known.add(var)
            continue

        if isinstance(node, (ast.Expr, ast.Pass)) and isinstance(
            getattr(node, "value", None), (ast.Constant, type(None))
        ):
            continue  # docstring / bare literal

        raise DslError(
            "a flow file may only contain nf-core imports and step assignments",
            path,
            node.lineno,
        )

    # Resolve the import alias (`x as y`) to the real imported symbol.
    for step in steps:
        step.imported_as = imports[step.imported_as]

    return Flow(path=path, imports=imports, steps=steps)


def parse_file(path: Path) -> Flow:
    return parse(path.read_text(), path)
