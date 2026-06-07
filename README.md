# md2latex

A [Claude Code](https://claude.com/claude-code) agent skill that converts a
Markdown file into a compilable **LaTeX** document (`.tex` + `latexmkrc`),
following a set of bundled templates.

It is built to be **token-efficient**: a small, dependency-free Python script
does all the mechanical Markdown→LaTeX grammar conversion, and the agent only
makes the few semantic edits the script reports (label naming, cross-references,
captions).

## What it does

Given `target.md`, it produces `target.tex` and a `latexmkrc` in the current
directory:

- Auto-selects a template from the YAML frontmatter and body language:
  - `exercise` — when `tags:` contains `lecture/exercise`
  - `general_jp` — Japanese body (LuaLaTeX / `ltjsarticle`)
  - `general_en` — otherwise (pdfLaTeX / `scrartcl`)
- Converts: H1→title and H2…→`\section`…; `$$…$$`→`equation`/`align`/…;
  `\tag`→`\label`; pipe tables→`table`/`tabular`; Obsidian/Markdown images→
  `figure`; figure/table captions from adjacent `>` blockquotes; footnotes;
  `**bold**`/`_italic_`/`` `code` ``/links/lists; and (exercise) `**(a)**`
  subproblems → a `subproblems` environment.
- Leaves the Markdown source untouched and translates **grammar only** — the
  author's wording is preserved.

See [`skills/md2latex/reference/conversion-spec.md`](skills/md2latex/reference/conversion-spec.md)
for the full mapping.

## Requirements

- Python 3 (standard library only)
- A TeX distribution with `latexmk`, `lualatex`, and `pdflatex` (e.g. TeX Live)
  to compile the output.

## Install (via `gh skill`)

```bash
gh skill install <owner>/md2latex md2latex
```

(Requires GitHub CLI ≥ 2.90 with the `skill` command.)

## Usage

In Claude Code:

```
/md2latex target.md
```

The skill runs the converter, applies the semantic post-edits, and (optionally)
compiles the result:

```bash
latexmk target.tex
```

You can also run the converter directly:

```bash
python3 skills/md2latex/scripts/md2latex.py target.md [--outdir DIR] [--template NAME]
```

## Repository layout

```
skills/md2latex/        # the installable skill (self-contained)
  SKILL.md              #   runtime instructions
  scripts/md2latex.py   #   the converter
  reference/            #   conversion spec + post-editing guide
  templates/            #   general_jp / general_en / exercise
tests/                  # sample Markdown fixtures (for development)
CLAUDE.md, .claude/     # developer documentation
```

## Notes

- Captions are taken from a `>` blockquote next to the figure/table; if there is
  none, the caption is left empty for you to fill in.
- Templates keep `\author{names}` as a placeholder — fill in author info
  locally; it is intentionally not auto-populated.
