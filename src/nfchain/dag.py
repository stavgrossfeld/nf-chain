"""Render a resolved Chain as a graph.

Two formats, both from the same resolved chain nf-chain already builds:
  - mermaid: pastes into a Markdown fence, renders on GitHub / in VSCode
  - dot:     `dot -Tsvg` with Graphviz

Nodes are pipeline steps (with the params set on them); edges are the wired
outputs→inputs, labelled with the artifact kind and marked when nf-chain
inferred them.
"""

from __future__ import annotations

from .graph import Chain, ResolvedStep


def _param_lines(step: ResolvedStep) -> list[str]:
    lines: list[str] = []
    if step.accession_input is not None:
        lines.append("ids = " + ", ".join(step.accession_input))
    for key, value in sorted(step.params.items()):
        mark = " (auto)" if key in step.auto_params else ""
        lines.append(f"{key} = {value}{mark}")
    return lines


def _esc_mermaid(text: str) -> str:
    return text.replace('"', "&quot;").replace("(", "&#40;").replace(")", "&#41;")


def render_mermaid(chain: Chain) -> str:
    lines = ["```mermaid", "flowchart TD"]

    for step in chain.steps:
        body = [f"<b>{step.var}</b>", f"{step.ref.full_name}@{step.ref.revision}"]
        body += _param_lines(step)
        label = _esc_mermaid("<br/>".join(body)).replace("&lt;", "<").replace("&gt;", ">")
        lines.append(f'    {step.var}["{label}"]')

    lines.append("")
    for step in chain.steps:
        for wire in step.wires:
            tag = " ~auto~" if wire.auto else ""
            lbl = _esc_mermaid(f"{wire.param}: {wire.artifact.kind}{tag}")
            lines.append(f"    {wire.source_step} -->|{lbl}| {step.var}")

    lines.append("```")
    return "\n".join(lines) + "\n"


def _esc_dot(text: str) -> str:
    return text.replace('"', '\\"')


def render_dot(chain: Chain) -> str:
    lines = [
        "digraph nfchain {",
        "    rankdir=TD;",
        '    node [shape=box, style=rounded, fontname="monospace"];',
        '    edge [fontname="monospace", fontsize=10];',
        "",
    ]
    for step in chain.steps:
        body = [f"{step.var}", f"{step.ref.full_name}@{step.ref.revision}"] + _param_lines(step)
        label = _esc_dot("\\n".join(body))
        lines.append(f'    {step.var} [label="{label}"];')

    lines.append("")
    for step in chain.steps:
        for wire in step.wires:
            style = ' style=dashed' if wire.auto else ""
            lbl = _esc_dot(f"{wire.param} ({wire.artifact.kind})")
            lines.append(f'    {wire.source_step} -> {step.var} [label="{lbl}"{style}];')

    lines.append("}")
    return "\n".join(lines) + "\n"


def render(chain: Chain, fmt: str) -> str:
    if fmt == "mermaid":
        return render_mermaid(chain)
    if fmt == "dot":
        return render_dot(chain)
    raise ValueError(f"unknown dag format: {fmt!r} (use 'mermaid' or 'dot')")
