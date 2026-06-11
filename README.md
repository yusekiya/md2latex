# md2latex

A [Claude Code](https://claude.com/claude-code) agent skill that converts a
Markdown file into a compilable **LaTeX** document (`.tex` + `latexmkrc`),
following a set of bundled templates.

It is built to be **token-efficient**: a small, dependency-free Python script
does all the mechanical Markdown→LaTeX grammar conversion, and the agent only
makes the few semantic edits the script reports (label naming, cross-references,
captions).

## What it does

Given `target.md`, it produces `target.tex` and a `latexmkrc` (plus the
template's `config.tex` preamble, for `general_jp`/`general_en`) in the current
directory. The `latexmkrc`'s default target is set to `target.tex`, so a bare
`latexmk` (no file argument) builds the document.

- Auto-selects a template from the YAML frontmatter and body language:
  - `exercise` — when `tags:` contains `lecture/exercise`
  - `general_jp` — Japanese body (LuaLaTeX / `ltjsarticle`)
  - `general_en` — otherwise (pdfLaTeX / `scrartcl`)
- Converts: H1→title and H2…→`\section`…; `$$…$$`→`equation`/`align`/…;
  `\tag`→`\label`; pipe tables→`table`/`tabular`; Obsidian/Markdown images→
  `figure`; figure/table captions from adjacent `>` blockquotes; footnotes;
  `**bold**`/`_italic_`/`` `code` ``/links/lists; Obsidian callouts
  (`> [!theorem]`, `> [!definition]`, `> [!info]`, …) → the templates'
  theorem/callout box environments; and (exercise) `**(a)**` subproblems → a
  `subproblems` environment.
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
gh skill install yusekiya/md2latex md2latex --agent claude-code --scope user
```

(Requires GitHub CLI ≥ 2.90 with the `skill` command. Drop `--scope user` for
project-local install, or change `--agent` for other agents.)

To update the installed skill to the latest published release:

```bash
gh skill update md2latex
```

(Run this outside a clone of this repository. `gh skill update` also scans the
current git repo at project scope, so inside the clone it would try to update the
source `skills/md2latex/` — which has no install metadata — and prompt for a
repository. From outside the clone it just updates the installed copy.)

## Usage

In Claude Code:

```
/md2latex target.md
```

The skill runs the converter, applies the semantic post-edits, and (optionally)
compiles the result (the bundled `latexmkrc` selects the engine and targets
`target.tex`, so a bare `latexmk` works too):

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

## Development

After changing the skill, publish a new release so installs can pick it up:

```bash
git push
gh skill publish --tag <tag>   # e.g. v1.0.1
```

## Notes

- Captions are taken from a `>` blockquote next to the figure/table; if there is
  none, the caption is left empty for you to fill in.
- Templates keep `\author{names}` as a placeholder — fill in author info
  locally; it is intentionally not auto-populated.

## License

[MIT](LICENSE)
