#!/usr/bin/env python3
"""md2latex — deterministic Markdown -> LaTeX converter.

This script does the *mechanical* part of converting a Markdown document into a
LaTeX document, so that the agent (Claude) only has to spend tokens on the
semantic post-editing it reports at the end (see "post-edit hints").

Design notes:
  * Standard library only (no PyYAML / no pandoc) so the skill is portable and
    installable via `gh skill` anywhere Python 3 exists.
  * The Markdown source is never modified; we only read it.
  * Only Markdown<->LaTeX *grammar* is converted, never the wording/content.
  * Templates live next to this script (../templates/<name>/{main.tex,latexmkrc})
    and are selected from the YAML frontmatter + body language.

Usage:
    python3 md2latex.py target.md [--outdir DIR] [--template NAME]

Outputs (into --outdir, default = current working directory):
    <basename>.tex      the assembled LaTeX document
    latexmkrc           the compiler config copied from the chosen template

A human-readable "post-edit hints" report is printed to stderr listing the few
places that still need a human/agent decision (semantic labels, cross
references, empty captions, subproblem grouping, ...).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------

# Priority-ordered rules. Evaluated top to bottom: the first frontmatter tag
# match wins. To support a new tag, just add a row here -- no other code change
# is needed. (See .claude/rules/template-selection.md for the rationale.)
TAG_RULES = [
    ("lecture/exercise", "exercise"),
    # ("lecture/report", "report"),   # example: future extension
]

# Fallback when no tag rule matched: Japanese body -> general_jp else general_en.
FALLBACK_JP = "general_jp"
FALLBACK_EN = "general_en"

VALID_TEMPLATES = {"general_jp", "general_en", "exercise"}


def select_template(tags, body_text):
    """Return (template_name, reason)."""
    tagset = {t.strip() for t in tags}
    for tag, template in TAG_RULES:
        if tag in tagset:
            return template, f"frontmatter tag '{tag}'"
    if is_japanese(body_text):
        return FALLBACK_JP, "no matching tag; body detected as Japanese"
    return FALLBACK_EN, "no matching tag; body detected as non-Japanese"


def is_japanese(text):
    """Heuristic: Japanese if kana+kanji outnumber latin letters."""
    kana = len(re.findall(r"[぀-ゟ゠-ヿ]", text))
    cjk = len(re.findall(r"[一-鿿]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return (kana + cjk) > latin


# ---------------------------------------------------------------------------
# Frontmatter parsing (minimal: only what template selection needs)
# ---------------------------------------------------------------------------

def parse_frontmatter(text):
    """Return (tags_list, body_text_without_frontmatter).

    Supports a leading YAML block delimited by '---' lines, extracting only the
    ``tags`` field in either block form::

        tags:
          - a
          - b

    or inline form ``tags: [a, b]``. Anything else in the frontmatter is
    ignored. No external YAML dependency.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], text
    # find closing '---'
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return [], text  # malformed; treat whole thing as body

    fm = lines[1:end]
    body = "\n".join(lines[end + 1:])
    tags = _extract_tags(fm)
    return tags, body


def _extract_tags(fm_lines):
    tags = []
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        m = re.match(r"^tags:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        inline = m.group(1).strip()
        if inline.startswith("[") and inline.endswith("]"):
            inner = inline[1:-1]
            tags = [t.strip().strip("'\"") for t in inner.split(",") if t.strip()]
            return tags
        # block form: subsequent '- item' lines (indented)
        j = i + 1
        while j < len(fm_lines):
            mm = re.match(r"^\s*-\s+(.*)$", fm_lines[j])
            if not mm:
                break
            tags.append(mm.group(1).strip().strip("'\""))
            j += 1
        return tags
    return tags


# ---------------------------------------------------------------------------
# Inline conversion (text spans only; never math/code blocks)
# ---------------------------------------------------------------------------

class Inline:
    """Converts a single Markdown text fragment to LaTeX.

    Protects inline code, inline math and link URLs from escaping, converts
    decoration/links/footnotes, then escapes the remaining literal specials.
    """

    def __init__(self):
        self._store = {}
        self._n = 0

    def _ph(self, value):
        key = f"\x00{self._n}\x00"
        self._store[key] = value
        self._n += 1
        return key

    def convert(self, text):
        self._store = {}
        self._n = 0
        s = text

        # 1. protect inline code `...`
        s = re.sub(r"`([^`]+)`",
                   lambda m: self._ph(_texttt(m.group(1))), s)
        # 2. protect inline math $...$ (kept verbatim)
        s = re.sub(r"(?<!\$)\$(?!\$)((?:\\\$|[^$])+?)\$(?!\$)",
                   lambda m: self._ph("$" + m.group(1) + "$"), s)
        # 3. links [text](url) -> \href{url}{text}; protect url from escaping
        s = re.sub(r"(?<!\!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)",
                   lambda m: r"\href{" + self._ph(m.group(2)) + "}{" + m.group(1) + "}",
                   s)
        # 4. footnotes ^[ ... ] (balanced brackets) -> \footnote{...}
        s = _convert_footnotes(s)
        # 5. bold then italic (bold first so ** is consumed before *)
        s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
        s = re.sub(r"__(.+?)__", r"\\textbf{\1}", s)
        s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\\textit{\1}", s)
        s = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\\textit{\1}", s)
        # 6. escape remaining literal LaTeX specials in prose
        s = _escape_text(s)
        # 7. restore protected fragments
        for key, value in self._store.items():
            s = s.replace(key, value)
        return s


def _convert_footnotes(s):
    out = []
    i = 0
    while i < len(s):
        if s.startswith("^[", i):
            depth = 1
            j = i + 2
            while j < len(s) and depth:
                if s[j] == "[":
                    depth += 1
                elif s[j] == "]":
                    depth -= 1
                j += 1
            if depth == 0:
                inner = s[i + 2:j - 1]
                out.append(r"\footnote{" + inner + "}")
                i = j
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


# Escapes for plain prose. Math/code/urls are already protected by placeholders
# at the point this runs, and the LaTeX commands we emit use only \ { } which we
# deliberately leave untouched. We keep this minimal to avoid breaking content.
_TEXT_ESCAPES = [("%", r"\%"), ("&", r"\&"), ("#", r"\#"), ("_", r"\_")]


def _escape_text(s):
    for ch, rep in _TEXT_ESCAPES:
        s = s.replace(ch, rep)
    return s


# Full escaping for code-span content rendered with \texttt{}.
def _texttt(code):
    repl = {
        "\\": r"\textbackslash{}",
        "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&",
        "#": r"\#", "%": r"\%", "_": r"\_",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    out = "".join(repl.get(c, c) for c in code)
    return r"\texttt{" + out + "}"


# ---------------------------------------------------------------------------
# Block segmentation
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
IMAGE_RE = re.compile(r"^\s*(?:!\[\[(?P<obsidian>[^\]]+)\]\]|!\[(?P<alt>[^\]]*)\]\((?P<path>[^)\s]+)(?:\s+\"[^\"]*\")?\))\s*$")
BLOCKQUOTE_RE = re.compile(r"^>\s?(.*)$")
LISTITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
SUBPROBLEM_RE = re.compile(r"^\*\*\(([^)]+)\)\*\*\s*(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


def is_blank(line):
    return line.strip() == ""


def is_block_start(line):
    return bool(
        HEADING_RE.match(line)
        or FENCE_RE.match(line)
        or line.strip().startswith("$$")
        or IMAGE_RE.match(line)
        or BLOCKQUOTE_RE.match(line)
        or LISTITEM_RE.match(line)
    )


def segment(lines):
    """Split body lines into a list of block dicts."""
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if is_blank(line):
            i += 1
            continue

        m = FENCE_RE.match(line)
        if m:
            fence = m.group(2)[0]
            buf = []
            i += 1
            while i < n and not re.match(rf"^\s*{re.escape(fence)}{{3,}}\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1  # consume closing fence
            blocks.append({"type": "code", "lines": buf})
            continue

        if line.strip().startswith("$$"):
            blocks.append(_collect_math(lines, i_ref := [i]))
            i = i_ref[0]
            continue

        m = HEADING_RE.match(line)
        if m:
            blocks.append({"type": "heading", "level": len(m.group(1)),
                           "text": m.group(2)})
            i += 1
            continue

        m = IMAGE_RE.match(line)
        if m:
            blocks.append({"type": "figure",
                           "file": _image_filename(m),
                           "caption": None, "human_no": None})
            i += 1
            continue

        if BLOCKQUOTE_RE.match(line):
            buf = []
            while i < n and BLOCKQUOTE_RE.match(lines[i]):
                buf.append(BLOCKQUOTE_RE.match(lines[i]).group(1))
                i += 1
            blocks.append({"type": "blockquote", "lines": buf})
            continue

        if "|" in line and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]):
            tbl, i = _collect_table(lines, i)
            blocks.append(tbl)
            continue

        if LISTITEM_RE.match(line):
            buf = []
            while i < n and (LISTITEM_RE.match(lines[i]) or
                             (not is_blank(lines[i]) and lines[i].startswith((" ", "\t")) and buf)):
                buf.append(lines[i])
                i += 1
            blocks.append({"type": "list", "lines": buf})
            continue

        # paragraph: until blank or a new block start
        buf = [line]
        i += 1
        while i < n and not is_blank(lines[i]) and not is_block_start(lines[i]):
            buf.append(lines[i])
            i += 1
        blocks.append({"type": "para", "lines": buf})
    return blocks


def _collect_math(lines, i_ref):
    i = i_ref[0]
    n = len(lines)
    first = lines[i].strip()
    inner = []
    if first == "$$":
        i += 1
        while i < n and lines[i].strip() != "$$":
            inner.append(lines[i])
            i += 1
        i += 1  # consume closing $$
    else:
        # single-line $$ ... $$ or $$ starting line
        content = first
        if content.startswith("$$"):
            content = content[2:]
        if content.endswith("$$"):
            content = content[:-2]
            inner = [content] if content.strip() else []
            i += 1
        else:
            inner.append(content)
            i += 1
            while i < n and not lines[i].strip().endswith("$$"):
                inner.append(lines[i])
                i += 1
            if i < n:
                last = lines[i].rstrip()
                last = last[:last.rfind("$$")] if "$$" in last else last
                if last.strip():
                    inner.append(last)
                i += 1
    i_ref[0] = i
    return {"type": "math", "lines": inner}


def _image_filename(m):
    if m.group("obsidian") is not None:
        spec = m.group("obsidian")
        # strip "#anchor" and "|alt" parts -> keep the file path
        return re.split(r"[#|]", spec, maxsplit=1)[0].strip()
    return m.group("path").strip()


def _collect_table(lines, i):
    header = lines[i]
    sep = lines[i + 1]
    aligns = _parse_aligns(sep)
    rows = []
    j = i + 2
    while j < len(lines) and "|" in lines[j] and not is_blank(lines[j]):
        rows.append(_split_row(lines[j]))
        j += 1
    return ({"type": "table",
             "header": _split_row(header),
             "aligns": aligns,
             "rows": rows,
             "caption": None,
             "human_no": None}, j)


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _parse_aligns(sep):
    cells = _split_row(sep)
    out = []
    for c in cells:
        c = c.strip()
        left = c.startswith(":")
        right = c.endswith(":")
        if left and right:
            out.append("c")
        elif right:
            out.append("r")
        else:
            out.append("l")
    return out


# ---------------------------------------------------------------------------
# Caption extraction from blockquotes
# ---------------------------------------------------------------------------

CAPTION_LABEL_RE = re.compile(
    r"^\s*(?:表|図|Table|Figure|Fig\.?)\s*(\d+)\s*[\.:、　]?\s*", re.IGNORECASE)


def build_caption(bq_lines, inline):
    """Return (caption_latex, human_number)."""
    text_lines = [ln for ln in bq_lines]
    human_no = None
    if text_lines:
        m = CAPTION_LABEL_RE.match(text_lines[0])
        if m:
            human_no = m.group(1)
            text_lines[0] = text_lines[0][m.end():]
    joined = "".join(ln.strip() for ln in text_lines if ln.strip() != "")
    return inline.convert(joined), human_no


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

SECTION_BY_LEVEL = {2: "section", 3: "subsection", 4: "subsubsection",
                    5: "paragraph", 6: "subparagraph"}

KNOWN_ENV_RE = re.compile(r"^\s*\\begin\{[A-Za-z*]+\}")
TAG_RE = re.compile(r"\\tag\{([^}]*)\}")
ENV_NAME_RE = re.compile(r"\\(?:begin|end)\{([A-Za-z*]+)\}")


class Renderer:
    def __init__(self, template, inline, hints):
        self.template = template
        self.inline = inline
        self.hints = hints
        self.eq_n = 0
        self.fig_n = 0
        self.tbl_n = 0

    # -- block association (captions, subproblems) --------------------------
    def associate(self, blocks):
        nonblank = [b for b in blocks]
        used = set()
        for idx, b in enumerate(nonblank):
            if b["type"] != "blockquote":
                continue
            prev_b = nonblank[idx - 1] if idx > 0 else None
            next_b = nonblank[idx + 1] if idx + 1 < len(nonblank) else None
            cap, human = build_caption(b["lines"], self.inline)
            if prev_b is not None and prev_b["type"] == "figure" and prev_b["caption"] is None:
                prev_b["caption"] = cap
                prev_b["human_no"] = human
                used.add(idx)
            elif next_b is not None and next_b["type"] == "table" and next_b["caption"] is None:
                next_b["caption"] = cap
                next_b["human_no"] = human
                used.add(idx)
        return [b for k, b in enumerate(nonblank) if k not in used]

    # -- top level ----------------------------------------------------------
    def render(self, blocks):
        blocks = self.associate(blocks)
        out = []
        i = 0
        while i < len(blocks):
            b = blocks[i]
            if (self.template == "exercise" and b["type"] == "para"
                    and SUBPROBLEM_RE.match(b["lines"][0])):
                run = []
                while (i < len(blocks) and blocks[i]["type"] == "para"
                       and SUBPROBLEM_RE.match(blocks[i]["lines"][0])):
                    run.append(blocks[i])
                    i += 1
                out.append(self.render_subproblems(run))
                continue
            out.append(self.render_block(b))
            i += 1
        return "\n\n".join(x for x in out if x is not None and x != "")

    def render_block(self, b):
        return getattr(self, "r_" + b["type"])(b)

    # -- individual blocks --------------------------------------------------
    def r_heading(self, b):
        level = b["level"]
        if level == 1:
            self.hints.append(
                f"Extra H1 heading in body treated as \\section: {b['text']!r}")
            cmd = "section"
        else:
            cmd = SECTION_BY_LEVEL.get(level, "subparagraph")
        return f"\\{cmd}{{{self.inline.convert(b['text'])}}}"

    def r_para(self, b):
        return "\n".join(self.inline.convert(ln) for ln in b["lines"])

    def r_code(self, b):
        body = "\n".join(b["lines"])
        return "\\begin{verbatim}\n" + body + "\n\\end{verbatim}"

    def r_blockquote(self, b):
        body = "\n".join(self.inline.convert(ln) for ln in b["lines"] if ln.strip() != "")
        return "\\begin{quote}\n" + body + "\n\\end{quote}"

    def r_math(self, b):
        inner = list(b["lines"])
        stripped = [ln for ln in inner if ln.strip() != ""]
        if stripped and KNOWN_ENV_RE.match(stripped[0]):
            return self._render_known_env(inner)
        # plain $$...$$ -> equation
        body = "\n".join(inner).strip("\n")
        body, _ = self._convert_tags(body)
        return "\\begin{equation}\n" + body + "\n\\end{equation}"

    def _render_known_env(self, inner):
        # locate the final \end{env} and strip a trailing '\\' on the last
        # content line before it (matches the spec's align example).
        end_idx = None
        for k in range(len(inner) - 1, -1, -1):
            if re.match(r"^\s*\\end\{[A-Za-z*]+\}", inner[k]):
                end_idx = k
                break
        if end_idx is not None:
            for k in range(end_idx - 1, -1, -1):
                if inner[k].strip() != "":
                    inner[k] = re.sub(r"\\\\\s*$", "", inner[k].rstrip())
                    break
        text = "\n".join(inner)
        text, _ = self._convert_tags(text)
        return text

    def _convert_tags(self, text):
        labels = []

        def repl(m):
            self.eq_n += 1
            raw = m.group(1)
            safe = re.sub(r"[^0-9A-Za-z]+", "_", raw).strip("_") or str(self.eq_n)
            label = f"eq:eq{safe}"
            labels.append((raw, label))
            return f"\\label{{{label}}}"

        new = TAG_RE.sub(repl, text)
        for raw, label in labels:
            self.hints.append(
                f"equation \\tag{{{raw}}} -> \\label{{{label}}}  "
                f"(rename to a semantic name if helpful; update its references)")
        return new, labels

    def r_figure(self, b):
        self.fig_n += 1
        label = f"fig:fig{self.fig_n}"
        caption = b["caption"] or ""
        if not caption:
            self.hints.append(
                f"figure '{b['file']}' has no caption (empty \\caption{{}}); "
                f"label {label}")
        if b.get("human_no"):
            self.hints.append(
                f"figure source number {b['human_no']} -> {label}")
        return (
            "\\begin{figure}[h]\n"
            "  \\centering\n"
            f"  \\includegraphics[width=0.65\\linewidth]{{{b['file']}}}\n"
            f"  \\caption{{{caption}}}\n"
            f"  \\label{{{label}}}\n"
            "\\end{figure}"
        )

    def r_table(self, b):
        self.tbl_n += 1
        label = f"table:table{self.tbl_n}"
        caption = b["caption"] or ""
        if not caption:
            self.hints.append(
                f"table #{self.tbl_n} has no caption (empty \\caption{{}}); "
                f"label {label}")
        if b.get("human_no"):
            self.hints.append(
                f"table source number {b['human_no']} -> {label}")
        cols = "".join(b["aligns"])
        lines = []
        lines.append("\\begin{table}[h]")
        lines.append("  \\centering")
        lines.append(f"  \\caption{{{caption}}}")
        lines.append(f"  \\label{{{label}}}")
        lines.append(f"  \\begin{{tabular}}{{ {cols} }}")
        lines.append("  \\hline")
        lines.append("  " + self._row(b["header"]))
        lines.append("  \\hline")
        for row in b["rows"]:
            lines.append("  " + self._row(row))
        lines.append("  \\hline")
        lines.append("  \\end{tabular}")
        lines.append("\\end{table}")
        return "\n".join(lines)

    def _row(self, cells):
        return " & ".join(self.inline.convert(c) for c in cells) + r" \\"

    def r_list(self, b):
        return render_list(b["lines"], self.inline)

    def render_subproblems(self, run):
        items = []
        for b in run:
            text = "\n".join(b["lines"])
            m = SUBPROBLEM_RE.match(b["lines"][0])
            rest_first = m.group(2)
            other = b["lines"][1:]
            content_lines = ([rest_first] + other) if rest_first or other else [rest_first]
            content = "\n".join(self.inline.convert(ln) for ln in content_lines)
            items.append("\\item " + content)
        self.hints.append(
            f"subproblems environment generated from {len(run)} '**(x)**' "
            f"item(s); verify grouping and that multi-paragraph bodies stayed together")
        return "\\begin{subproblems}\n" + "\n".join(items) + "\n\\end{subproblems}"


def render_list(lines, inline):
    """Stack-based nested list renderer (itemize/enumerate)."""
    items = []  # (indent, ordered, content)
    for ln in lines:
        m = LISTITEM_RE.match(ln)
        if m:
            indent = len(m.group(1).expandtabs(4))
            ordered = bool(re.match(r"\d+[.)]", m.group(2)))
            items.append([indent, ordered, m.group(3)])
        else:
            # continuation line of the previous item
            if items:
                items[-1][2] += " " + ln.strip()
    out = []
    stack = []  # list of (indent, env)

    def env_for(ordered):
        return "enumerate" if ordered else "itemize"

    for indent, ordered, content in items:
        while stack and indent < stack[-1][0]:
            out.append("  " * (len(stack) - 1) + f"\\end{{{stack[-1][1]}}}")
            stack.pop()
        if not stack or indent > stack[-1][0]:
            env = env_for(ordered)
            out.append("  " * len(stack) + f"\\begin{{{env}}}")
            stack.append((indent, env))
        out.append("  " * len(stack) + "\\item " + inline.convert(content))
    while stack:
        out.append("  " * (len(stack) - 1) + f"\\end{{{stack[-1][1]}}}")
        stack.pop()
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Reference-candidate scan (hints only; the agent rewrites them)
# ---------------------------------------------------------------------------

REF_PATTERNS = [
    re.compile(r"式\s*\(?\d+\)?"),
    re.compile(r"図\s*\d+"),
    re.compile(r"表\s*\d+"),
    re.compile(r"(?:Eq|Fig|Table|Figure)\.?~?\s*\(?\d+\)?", re.IGNORECASE),
    re.compile(r"第\s*\d+\s*節"),
]


def scan_reference_candidates(body_lines):
    found = []
    for idx, line in enumerate(body_lines, start=1):
        for pat in REF_PATTERNS:
            for m in pat.finditer(line):
                found.append((idx, m.group(0)))
    return found


# ---------------------------------------------------------------------------
# Template assembly
# ---------------------------------------------------------------------------

def assemble(template_dir, title_latex, body_latex):
    main = (template_dir / "main.tex").read_text(encoding="utf-8")
    # replace the placeholder title (templates ship literally as \title{title})
    main = re.sub(r"\\title\{[^}]*\}", lambda _m: "\\title{" + title_latex + "}",
                  main, count=1)
    # links need hyperref, which the templates do not load; inject it on demand
    # so the output compiles without editing the templates themselves.
    if "\\href" in body_latex and "hyperref" not in main:
        main = main.replace("\\begin{document}",
                            "\\usepackage{hyperref}\n\\begin{document}", 1)
    # insert the body right after \maketitle
    marker = "\\maketitle"
    pos = main.find(marker)
    if pos == -1:
        raise RuntimeError("template main.tex has no \\maketitle")
    insert_at = pos + len(marker)
    return main[:insert_at] + "\n\n\n" + body_latex + "\n" + main[insert_at:]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def convert(md_path, outdir, template_override=None):
    md_path = Path(md_path)
    raw = md_path.read_text(encoding="utf-8")

    tags, after_fm = parse_frontmatter(raw)

    # body = from the first H1 line downward (title from that H1)
    body_lines_all = after_fm.splitlines()
    title = None
    body_lines = []
    for k, line in enumerate(body_lines_all):
        m = re.match(r"^#\s+(.*?)\s*#*\s*$", line)
        if m:
            title = m.group(1)
            body_lines = body_lines_all[k + 1:]
            break
    if title is None:
        raise SystemExit("error: no H1 ('# title') heading found; nothing to convert")

    body_text = "\n".join(body_lines)
    if template_override:
        template = template_override
        reason = "forced via --template"
    else:
        template, reason = select_template(tags, body_text)
    if template not in VALID_TEMPLATES:
        raise SystemExit(f"error: unknown template '{template}'")

    inline = Inline()
    hints = []
    renderer = Renderer(template, inline, hints)
    blocks = segment(body_lines)
    body_latex = renderer.render(blocks)
    title_latex = inline.convert(title)

    template_dir = Path(__file__).resolve().parent.parent / "templates" / template
    tex = assemble(template_dir, title_latex, body_latex)

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = md_path.stem
    tex_out = outdir / f"{stem}.tex"
    latexmkrc_out = outdir / "latexmkrc"
    tex_out.write_text(tex, encoding="utf-8")
    latexmkrc_out.write_text((template_dir / "latexmkrc").read_text(encoding="utf-8"),
                             encoding="utf-8")

    refs = scan_reference_candidates(body_lines)
    _print_report(template, reason, tex_out, latexmkrc_out, hints, refs)
    return tex_out


def _print_report(template, reason, tex_out, latexmkrc_out, hints, refs):
    e = sys.stderr
    print("=" * 70, file=e)
    print("md2latex: conversion complete", file=e)
    print("=" * 70, file=e)
    print(f"template : {template}  ({reason})", file=e)
    print(f"written  : {tex_out}", file=e)
    print(f"           {latexmkrc_out}", file=e)
    print("", file=e)
    print("POST-EDIT HINTS (agent: handle only these, then compile):", file=e)
    if not hints:
        print("  - none (mechanical conversion is self-contained)", file=e)
    for h in hints:
        print(f"  - {h}", file=e)
    if refs:
        print("", file=e)
        print("  Cross-reference CANDIDATES in body (rewrite to \\eqref/\\ref"
              " using the label map above; verify each):", file=e)
        for line_no, text in refs:
            print(f"    body line {line_no}: {text}", file=e)
    print("=" * 70, file=e)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert Markdown to LaTeX.")
    ap.add_argument("markdown", help="input Markdown file")
    ap.add_argument("--outdir", default=".", help="output directory (default: cwd)")
    ap.add_argument("--template", choices=sorted(VALID_TEMPLATES),
                    help="force a template instead of auto-selecting")
    args = ap.parse_args(argv)
    convert(args.markdown, args.outdir, args.template)


if __name__ == "__main__":
    main()
