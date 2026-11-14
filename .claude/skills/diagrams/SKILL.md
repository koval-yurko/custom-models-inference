---
name: diagrams
description: Make or change a diagram in this repo's docs (docs/*.md, READMEs). Use when you add or edit a Mermaid block, when a diagram reads badly, or when you consider D2 or draw.io. Gives the Mermaid -> D2 -> draw.io escalation rule, the style rules, reference examples and the render check in the Paseo browser.
---

# Diagrams

Good diagrams in this repo are small, tell one story, and render on GitHub without a build step.

## Escalation rule: Mermaid, then D2, then draw.io

1. **Mermaid first.** GitHub renders it, a diff shows the change, and an agent can edit it. Use it for flows, pipelines, sequences and small architecture maps.
2. **D2 only when Mermaid fails after you applied the style rules below.** Typical case: one picture must show many cross-zone edges (request path and data flow together), and Mermaid crosses edges or puts labels in the wrong place. D2 with `--layout elk` routes edges at right angles.
3. **draw.io only when D2 is not enough.** Typical case: a slide-quality overview with vendor icons (GCP), for readers outside the team. Positions are by hand, so it costs the most to keep current.

Before you escalate, try to split the diagram. Two clear Mermaid diagrams are better than one D2 diagram.

## Style rules (all tools)

- One diagram, one story. Remove the edges that belong to another story and link to that diagram.
- 3 to 8 nodes. Above 8, split.
- Label every edge that is not obvious. Use 1 to 3 words (`ID token`, `apply first`).
- Labels in nodes: 2 short lines at most (`<br/>`). Put details in the text under the diagram.
- Left to right (`LR`) for chains. A top-down chain of more than 4 nodes gets very tall in a 980 px page.
- Use a sequence diagram for request and answer in time order. Do not draw back edges in a flowchart.
- Colors carry meaning, the same in every diagram:

| Class | Fill | Stroke | Meaning |
|---|---|---|---|
| `public` | `#fff4e5` | `#d97706` | Reachable from the internet |
| `private` | `#e8f1ff` | `#2563eb` | Private GCP service |
| `store` | `#ecfdf3` | `#059669` | Bucket, data |
| `ext` | `#f3f4f6` | `#6b7280` | Outside system (Hugging Face) |
| `cost` | `#fde8e8` | `#dc2626` | Step that starts GPU cost |
| `layer` | `#f8fafc` | `#475569` | Folder or Terraform root |

- Always set `color:#111` in a `classDef`, so text stays dark in the GitHub dark theme.
- Text follows the docs style: Simplified Technical English, no contractions.

## Mermaid pitfalls (found in this repo)

- `direction` inside a subgraph is ignored when an edge goes to or from the subgraph. Many unlinked nodes then form one very long column or row. Use one node with a short list instead (example 3).
- `&lt;` in a label disappears. Write `#lt;` and `#gt;` (`deployments/#lt;name#gt;`).
- Edges between subgraphs that go back against the flow cross other nodes. Remove them or split the diagram.
- Do not use `layout: elk` in Mermaid: GitHub does not load the ELK plugin.

## Files for D2 and draw.io

Put them next to the doc in `docs/diagrams/`, and embed the SVG with a Markdown image. Keep the source in git.

```sh
d2 --layout elk --pad 20 docs/diagrams/<name>.d2 docs/diagrams/<name>.svg
drawio -x -f svg -e -b 10 -o docs/diagrams/<name>.drawio.svg <name>.drawio   # -e embeds the editable XML; delete <name>.drawio after
```

Run the export again after every change of the source. For draw.io GCP icons, use the `drawio` skill and `search_shapes` (`mxgraph.gcp3.cloudrun`, `mxgraph.gcp3.vertexai`, `mxgraph.gcp3.cloud_storage`).

## Reference examples

[examples.md](examples.md) has one example per diagram type, approved by the user on 2026-11-14: architecture with zones, sequence, list nodes, pipeline, D2 system map, draw.io overview. Copy the closest one.

## Render check in the Paseo browser

Check every diagram you change before you finish.

1. Serve the repo root in the background: `python3 -m http.server 8765 --bind 127.0.0.1`.
2. Open `http://127.0.0.1:8765/.claude/skills/diagrams/preview.html?f=docs/<file>.md` in a Paseo browser tab. Add `&d=<n>` to show only diagram `n` (from 0). The page uses GitHub Markdown CSS and Mermaid 11, like GitHub.
3. Take a screenshot. Check: no crossed edges through nodes, no label on top of a line, the text is not tiny, the diagram is not very tall.
4. Check that all blocks parse: the tab title starts with `OK`, not `ERR`.
5. Stop the server.
