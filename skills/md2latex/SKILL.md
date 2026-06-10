---
name: md2latex
description: Convert a Markdown file into a compilable LaTeX document (.tex + latexmkrc). Auto-selects a bundled template (general_jp / general_en / exercise) from the YAML frontmatter and body language, runs a deterministic Python converter for the mechanical grammar, then does a small semantic pass (labels, cross-references, captions). Use when the user asks to turn a Markdown file into LaTeX/TeX, e.g. "/md2latex target.md".
allowed-tools: Bash, Read, Edit, Write
license: MIT
---

# md2latex

Convert a Markdown file to LaTeX. The heavy, mechanical work is done by a
bundled Python script (zero model tokens); you only spend tokens on the few
semantic fixes the script reports.

## Guardrails (always)

- **Never modify the source Markdown.** Read it only.
- **Convert grammar, not content.** Never reword, add, or drop the author's text.
- **No personal data in output.** Leave `\author{names}` as-is; never insert real
  names, emails, IDs, or passwords (outputs may be published).

## Workflow

Let `SKILL_DIR` be the directory containing this SKILL.md.

1. **Run the converter** (it writes into the current working directory):

   ```bash
   python3 "$SKILL_DIR/scripts/md2latex.py" <target.md>
   ```

   It writes `./<basename>.tex`, `./latexmkrc` and — for templates that split
   their preamble — `./config.tex`, and prints a **POST-EDIT HINTS** report to
   stderr. It auto-selects the template; override with
   `--template general_jp|general_en|exercise` only if the user asks.

2. **Read the hints** from stderr. They tell you exactly which lines still need
   a human decision — do not re-scan the whole file.

3. **Apply only the reported edits** to the generated `.tex` (use `Edit`):
   - **Equation labels**: the script turned each `\tag{N}` into a placeholder
     `\label{eq:eqN}`. Optionally rename to a meaningful label (e.g.
     `eq:sin_function`) — if you do, update every reference to it.
   - **Cross-references**: rewrite the listed prose references to
     `\eqref{eq:...}` (equations) or `\ref{...}` (figures/tables/sections),
     using the label map in the hints. **Verify each candidate** — some matches
     (e.g. a number that appears inside a caption) are not references. For a
     referenced section, add a `\label{sec:...}` to that `\section` first.
   - **Empty captions**: figures/tables with no adjacent `>` caption block get
     `\caption{}`. Leave them empty (do not invent text) unless the user
     provides the caption.
   - **Subproblems / lists**: verify the generated `subproblems`/list grouping
     matches the source, especially multi-paragraph items.
   - **Callouts**: Obsidian callouts (`> [!theorem]` …) are converted
     automatically; act only on flagged ones (a title-less `[!law]`, an
     unmapped type rendered as `info`, or a degradation to `quote` in the
     `exercise` template).

4. **(Recommended) Compile** to confirm it builds, then report the PDF:

   ```bash
   latexmk <basename>.tex
   ```

   `general_jp` and `exercise` use LuaLaTeX; `general_en` uses pdfLaTeX (the
   bundled `latexmkrc` selects the right engine). Re-run once after adding
   references so the `.aux` cross-references resolve. Fix any compile errors.

5. **Report** the generated files and any captions left empty / references you
   were unsure about, so the user can finish those.

## Conversion rules & template selection

The full, authoritative grammar mapping and the template-selection rules live in
[`reference/conversion-spec.md`](reference/conversion-spec.md). The semantic
post-edit details live in [`reference/post-editing.md`](reference/post-editing.md).
Read them when you hit a case not covered above.
