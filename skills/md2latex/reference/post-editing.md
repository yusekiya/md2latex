# Post-editing guide (the semantic pass)

After `scripts/md2latex.py` runs, it prints a **POST-EDIT HINTS** report to
stderr. That report is your work list — handle only what it names, then compile.
The goal is correctness with minimal tokens: do not re-read or re-scan the whole
document.

## What the script already did (don't redo)

- Selected the template and assembled the full `.tex`.
- Converted headings, display math, tables, figures, footnotes, decoration,
  lists, and (exercise) subproblems.
- Extracted captions from adjacent `>` blockquotes; left `\caption{}` empty
  where there was none.
- Converted Obsidian callouts (`> [!theorem]` …) into the template's
  `callout`/box environments (general_jp / general_en).
- Turned each `\tag{N}` into a placeholder `\label{eq:eqN}`.

## Your tasks, driven by the hints

### 1. Equation labels (optional rename)
Placeholders look like `\label{eq:eq1}`. You may rename them to meaningful
labels (e.g. `eq:sin_function`, `eq:gauss_law`). If you rename a label, update
**every** `\eqref` that points to it. Renaming is optional; `eq:eqN` compiles
fine.

### 2. Cross-references (the main task)
The hints list a label map and candidate reference sites (with body line
numbers and the matched text). For each candidate:
- Decide whether it is really a cross-reference. **Skip false positives** — e.g.
  the `表1` that appears *inside a caption blockquote* is the source's own
  numbering, not a reference; a bare `(1)` may be an enumeration.
- Rewrite genuine references, putting a non-breaking space `~` between the
  leading reference word and the macro (so they never split across a line):
  - equation → `式~\eqref{eq:…}` (likewise `Eq.~\eqref{eq:…}`)
  - figure → `図~\ref{fig:…}`, table → `表~\ref{table:…}`
    (likewise `Fig.~\ref{fig:…}`, `Table~\ref{table:…}`)
  - section → first add `\label{sec:…}` right after that `\section{…}`, then
    `\ref{sec:…}` (e.g. `第2節` → `第\ref{sec:…}節`, where no `~` applies)
- Match by number: the label map ties each source number (`表1`, `\tag{1}`, …)
  to the LaTeX label to use.

### 3. Empty captions
Figures/tables flagged "no caption" have `\caption{}`. Leave them empty unless
the user supplies caption text — never invent content. Mention them in your
final summary so the user can fill them in.

### 4. Subproblems & lists
Verify the generated `subproblems`/`itemize`/`enumerate` grouping matches the
source — especially items whose body spans multiple paragraphs (the script
groups one paragraph per `\item`; merge follow-on paragraphs into the right
`\item` if needed).

### 5. Callout hints
Only act when a callout is flagged:
- **`[!law]` without a title** — the `law` environment requires one; the script
  emitted `\begin{callout}[{}]{law}`. Put the proper title between the braces
  (take it from the surrounding prose only if unambiguous; otherwise ask).
- **Unmapped type rendered as `info`** — if a mapped environment clearly fits
  better (e.g. the author used a synonym of *theorem*), switch it; otherwise
  the `info` box is fine. Never invent title text.
- **Degraded to `quote` (exercise template)** — expected; mention it in the
  final summary.
- Theorem callouts use the **numbered** environments (`thm`, `dfn`, …). If the
  user asks for unnumbered ones, switch to the starred variants (`thm*`, …).

### 6. Anything else the hints flag
E.g. an extra H1 in the body (mapped to `\section`), or text that may need extra
LaTeX escaping. Resolve each, preserving the author's wording.

## Compile and verify

```bash
latexmk <basename>.tex
```

- `general_jp` / `exercise` → LuaLaTeX; `general_en` → pdfLaTeX (handled by the
  bundled `latexmkrc`).
- After adding `\label`/`\ref`, the first pass may warn "Reference … undefined"
  / "Rerun to get cross-references right" — that's normal; latexmk reruns and
  resolves them. Confirm the final pass reports **no undefined references**.
- If `\includegraphics` files are missing, the build fails on the image — tell
  the user which files to provide (do not fabricate images).

## Reminders

- Never edit the source `.md`.
- Never add personal data; keep `\author{names}`.
- Convert grammar only; keep the author's wording intact.
