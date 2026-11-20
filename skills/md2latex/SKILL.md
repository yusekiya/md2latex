---
name: md2latex
description: Convert a Markdown file — or a directory of Markdown files merged in filename order, with an optional abstract file — into a compilable LaTeX document (.tex + latexmkrc, plus a .bib for Obsidian-linked references and copies of the figure files). Auto-selects a bundled template (general_jp / general_en / exercise) from the YAML frontmatter and body language, runs a deterministic Python converter for the mechanical grammar, then does a small semantic pass (labels, cross-references, captions). Use when the user asks to turn Markdown into LaTeX/TeX, e.g. "/md2latex target.md" or "/md2latex paper_dir/".
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
   python3 "$SKILL_DIR/scripts/md2latex.py" <target.md | target_dir>
   ```

   It writes `./<basename>.tex`, `./latexmkrc` and — for templates that split
   their preamble — `./config.tex`, and prints a **POST-EDIT HINTS** report to
   stderr. It auto-selects the template; override with
   `--template general_jp|general_en|exercise` only if the user asks.

   - **Directory input** merges every `*.md` directly in it into one
     `<dirname>.tex`, in natural filename order (`2_x` before `10_x`). Each
     file's H1 becomes a `\section` (H2 → `\subsection`, …). A file named
     `abstract` after an optional number (`00_abstract.md`) becomes the
     `abstract` environment and its H1 the document title; pass
     `--abstract <file>` if the user names a different one.
   - **Citations**: a wikilink `[[Note]]` whose note contains a ```` ```bibtex ````
     code block becomes `\cite{key}`, and the record is added once to
     `./<basename>.bib` (an existing `.bib` is kept; only new keys are
     appended). Notes are looked up in the Obsidian vault (nearest ancestor
     with `.obsidian/`, else the input's directory); pass `--vault <dir>` if
     the user's notes live elsewhere.
   - **Figures**: the converter copies every referenced image file into the
     same directory as the generated `.tex` and points `\includegraphics` at
     the copy. **Unless the user specified where figure files should be
     stored, keep this default** (figures next to the `.tex`) and say so in
     your report. If the user did specify a location, pass
     `--figdir <dir>` (relative to the output directory, e.g. `--figdir figs`).

2. **Read the hints** from stderr. They tell you exactly which lines still need
   a human decision — do not re-scan the whole file.

3. **Apply only the reported edits** to the generated `.tex` (use `Edit`):
   - **Equation labels**: the script turned each `\tag{N}` into a placeholder
     `\label{eq:eqN}`. Optionally rename to a meaningful label (e.g.
     `eq:sin_function`) — if you do, update every reference to it.
   - **Cross-references**: rewrite the listed prose references to
     `\eqref{eq:...}` (equations) or `\ref{...}` (figures/tables/sections),
     using the label map in the hints, tied with `~` to the preceding
     character (`式~\eqref{…}`, `Fig.~\ref{…}`; not after `(` or in
     `第\ref{…}節`). **Verify each candidate** — some matches
     (e.g. a number that appears inside a caption) are not references. For a
     referenced section, add a `\label{sec:...}` to that `\section` first.
   - **Empty captions**: figures/tables with no adjacent `>` caption block get
     `\caption{}`. Leave them empty (do not invent text) unless the user
     provides the caption.
   - **Subproblems / lists**: the script folds each subproblem's full body
     (math, continuation prose, nested lists, figures) into its `\item`; just
     confirm the `(a)/(b)/...` order matches the source.
   - **Callouts**: Obsidian callouts (`> [!theorem]` …) are converted
     automatically; act only on flagged ones (a title-less `[!law]`, an
     unmapped type rendered as `info`, or a degradation to `quote` in the
     `exercise` template).
   - **Directory input**: hints and reference candidates are prefixed with the
     source file (`[02_method.md]`, `02_method.md:15`); match each reference
     to the label from the **same file**. A repeated `\tag{1}` gets a suffixed
     label (`eq:eq1_2`). If there is no abstract file, `\title{title}` stays a
     placeholder — ask the user for the title; never invent it.
   - **Unresolved wikilinks / missing figures**: a `[[link]]` that is not a
     citation is left as literal text, and a figure file that cannot be found
     keeps its original path. Report them; do not invent BibTeX records,
     captions or images.

4. **(Recommended) Compile** to confirm it builds, then report the PDF:

   ```bash
   latexmk <basename>.tex
   ```

   `general_jp` and `exercise` use LuaLaTeX; `general_en` uses pdfLaTeX (the
   bundled `latexmkrc` selects the right engine). Re-run once after adding
   references so the `.aux` cross-references resolve. Fix any compile errors.

5. **Report** the generated files (including the `.bib` and where the figure
   files were copied) and any captions left empty / references / wikilinks /
   figures you were unsure about, so the user can finish those.

## Conversion rules & template selection

The full, authoritative grammar mapping and the template-selection rules live in
[`reference/conversion-spec.md`](reference/conversion-spec.md). The semantic
post-edit details live in [`reference/post-editing.md`](reference/post-editing.md).
Read them when you hit a case not covered above.
