# Rule: skill development, packaging & operational guardrails

## Operational guardrails (do not violate)

- **The repository is public** at <https://github.com/yusekiya/md2latex>.
  Routine pushes and `gh skill publish` releases are expected maintenance; still
  pause before irreversible actions (force-push, deleting tags/releases).
- **No personal data anywhere.** Outputs may be published. Keep `\author{names}`
  a placeholder; never embed real names, emails, IDs, or passwords in code,
  templates, fixtures, docs, or generated `.tex`.

## `gh skill` packaging

- Layout follows the `gh skill` convention: `skills/<name>/SKILL.md` (plus
  `scripts/`, `reference/`, `templates/`). This repo uses `skills/md2latex/`.
- `SKILL.md` frontmatter requires `name` (lowercase-hyphen, matches the dir) and
  `description`; `license` is optional (this skill declares `license: MIT`).
- Keep the skill **self-contained**: only relative references inside
  `skills/md2latex/`. `scripts/md2latex.py` resolves templates relative to its
  own location (`Path(__file__).parent.parent/"templates"`), so it works from
  any working directory and any install location.
- `gh skill install` writes provenance metadata into `SKILL.md` frontmatter on
  install — do not add it by hand.
- Validate the package shape locally with `gh skill preview <path>` (does not
  publish).

## SKILL.md authoring

- Keep it short and action-oriented; push detail into `reference/*` (progressive
  disclosure). The model reads `reference/conversion-spec.md` /
  `reference/post-editing.md` only when needed.
- The runtime workflow is: run the script → read stderr hints → apply only those
  edits → compile → report. Never re-scan the whole document.

## Maintenance checklist (per change)

1. Update `scripts/md2latex.py` **and** `reference/conversion-spec.md` together.
2. Update/extend `tests/sample_*.md` and re-run all three through the converter.
3. Compile each with `latexmk` (Lua/pdf as per template) — confirm no errors and
   no undefined references after the semantic pass.
4. Keep `general_jp`/`exercise` on LuaLaTeX and `general_en` on pdfLaTeX.
