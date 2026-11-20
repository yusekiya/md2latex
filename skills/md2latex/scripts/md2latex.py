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
    python3 md2latex.py target.md  [--outdir DIR] [--template NAME]
                                   [--vault DIR] [--figdir DIR]
    python3 md2latex.py target_dir [--abstract FILE] [same options]

A directory input merges every ``*.md`` directly inside it (natural filename
order, e.g. 2_x before 10_x) into one document; each file's H1 becomes a
\\section (headings shift down one level). A file named ``abstract`` (after an
optional leading number, e.g. ``00_abstract.md``) becomes the abstract and its
H1 the document title.

Outputs (into --outdir, default = current working directory):
    <basename>.tex      the assembled LaTeX document (<dirname>.tex for a dir)
    latexmkrc           the compiler config from the chosen template, with its
                        @default_files target rewritten to <basename>.tex
    config.tex          the preamble settings, when the template ships one
    <basename>.bib      BibTeX records of cited notes ([[note]] whose note has a
                        ```bibtex block); merged into an existing file
    figure files        copied next to the .tex (or into --figdir)

A human-readable "post-edit hints" report is printed to stderr listing the few
places that still need a human/agent decision (semantic labels, cross
references, empty captions, subproblem grouping, ...).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote


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

# ---------------------------------------------------------------------------
# Obsidian callout mapping (> [!type] Title)
# ---------------------------------------------------------------------------

# Templates whose preamble (config.tex) defines the callout/theorem
# environments. Other templates degrade callouts to a plain quote.
CALLOUT_TEMPLATES = {"general_jp", "general_en"}

# Theorem-like callout types -> amsthm environment names; rendered as
# \begin{callout}[Title]{env} ... \end{callout}. Numbered variants are used;
# switch to the starred env (thm* etc.) by hand if numbering is unwanted.
CALLOUT_THEOREM_MAP = {
    "theorem": "thm",
    "lemma": "lem",
    "proposition": "prop",
    "corollary": "cor",
    "conjecture": "conj",
    "assumption": "asm",
    "definition": "dfn",
    "remark": "rem",
    "exercise": "exc",       # run-in style; the callout title is NOT shown (exc ignores it)
    "exercise-b": "excb",    # line-break style; shows the optional title (shares exc's counter)
    "law": "law",       # title is mandatory (lawbreak style shows only the title)
}

# Standalone callout-box environments (NewCalloutBoxEnv in config.tex);
# rendered as \begin{env}[Title] ... \end{env}.
CALLOUT_BOX_ENVS = {"objective", "summary", "info"}

# Non-boxed run-in environments defined directly in config.tex (NOT wrapped in a
# callout tcolorbox). Rendered as \begin{env}[Title] ... \end{env}; the Obsidian
# callout title maps to the environment's heading-override argument, e.g.
#   > [!solution] 略解   ->   \begin{sol}[略解] ... \end{sol}
# Typically nested inside an [!exercise] callout (the sol env is meant for use
# inside exc, but works outside it too).
CALLOUT_PLAIN_ENVS = {
    "solution": "sol",
    "sol": "sol",
}

# Unknown callout types fall back to this box environment (title preserved).
CALLOUT_FALLBACK_ENV = "info"

# ---------------------------------------------------------------------------
# Multi-file input, bibliography, figures
# ---------------------------------------------------------------------------

# In a directory input, a file whose name (minus a leading number/separators)
# equals one of these (case-insensitive) is the abstract: its body becomes the
# abstract environment and its H1 the document title.
ABSTRACT_STEMS = {"abstract"}

# Fenced code-block languages that hold BibTeX records in a cited note.
BIBTEX_FENCE_LANGS = {"bibtex", "bib"}

# \bibliographystyle used when the document cites anything.
BIB_STYLE = "unsrt"

# Directories never indexed when resolving Obsidian links inside the vault.
VAULT_SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules"}


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
    """Return (tags_list, body_text_without_frontmatter, n_frontmatter_lines).

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
        return [], text, 0
    # find closing '---'
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return [], text, 0  # malformed; treat whole thing as body

    fm = lines[1:end]
    body = "\n".join(lines[end + 1:])
    tags = _extract_tags(fm)
    return tags, body, end + 1


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

# Obsidian wikilink [[Note]] / [[Note|alias]] / [[Note#heading]] (not an embed)
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\[\]\n]+?)\]\]")
# A resolved citation is first marked \x01key\x01 so that adjacent ones (only
# whitespace / a comma between them) can be merged into a single \cite{a,b}.
CITE_MARK_RE = re.compile(r"\x01([^\x01]+)\x01")
CITE_GROUP_RE = re.compile(r"\x01[^\x01]+\x01(?:[ \t]*[,，、]?[ \t]*\x01[^\x01]+\x01)*")
# Markdown backslash escape: '\' + ASCII punctuation (CommonMark). Matched
# left to right, so '\\' is consumed as one pair.
MD_ESCAPE_RE = re.compile(r"\\([!-/:-@\[-`{-~])")
# LaTeX for the literal character an escape stands for; characters not listed
# are emitted as-is ('\*' -> '*', '\(' -> '(', ...). '\\' is passed through
# unchanged (LaTeX line break), as authors use it in LaTeX-flavoured Markdown.
MD_ESCAPE_LATEX = {
    "\\": "\\\\", "#": r"\#", "$": r"\$", "%": r"\%", "&": r"\&", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "`": r"\textasciigrave{}", "|": r"\textbar{}", "<": r"\textless{}",
    ">": r"\textgreater{}",
}
# Escaped brackets stay visible as markers until the end of Inline.convert so
# that bracketed citations can be recognised; restored as {[} / {]} (braced so
# they are never read as an optional argument, e.g. right after \item).
ESC_LBRACK, ESC_RBRACK = "\x02", "\x03"
# Square brackets (escaped or not) enclosing nothing but citations
# ([[[A]]], \[[[A]], [[B]]\]): \cite already prints its own brackets, so these
# would show up doubled ([[1]]). Not when followed by '(' -- then the brackets
# are a Markdown link's text.
BRACKETED_CITES_RE = re.compile(
    r"[\[\x02][ \t]*(" + CITE_GROUP_RE.pattern + r")[ \t]*[\]\x03](?!\()")


class Inline:
    """Converts a single Markdown text fragment to LaTeX.

    Protects inline code, inline math and link URLs from escaping, converts
    citations/decoration/links/footnotes, then escapes the remaining literal
    specials.

    ``cite`` is an optional callback ``(link_text) -> bibkey | None`` used for
    Obsidian wikilinks; a link it resolves becomes ``\\cite{key}``, any other
    wikilink is left as literal text.
    """

    def __init__(self, cite=None):
        self._store = {}
        self._n = 0
        self.cite = cite

    def _wikilink(self, m):
        key = self.cite(m.group(1)) if self.cite else None
        return "\x01" + key + "\x01" if key else m.group(0)

    def _cite_group(self, m):
        keys = CITE_MARK_RE.findall(m.group(0))
        return self._ph("\\cite{" + ",".join(keys) + "}")

    def _md_escape(self, m):
        ch = m.group(1)
        if ch == "[":
            return ESC_LBRACK
        if ch == "]":
            return ESC_RBRACK
        return self._ph(MD_ESCAPE_LATEX.get(ch, ch))

    def _ph(self, value):
        key = f"\x00{self._n}\x00"
        self._store[key] = value
        self._n += 1
        return key

    def convert(self, text):
        self._store = {}
        self._n = 0
        s = text

        # 1. protect inline code `...` (an escaped \` does not open one)
        s = re.sub(r"(?<!\\)`([^`]+)`",
                   lambda m: self._ph(_texttt(m.group(1))), s)
        # 2. protect inline math $...$ (kept verbatim); an escaped \$ never
        #    opens one
        s = re.sub(r"(?<![\\$])\$(?!\$)((?:\\\$|[^$])+?)\$(?!\$)",
                   lambda m: self._ph("$" + m.group(1) + "$"), s)
        # 2a. Obsidian wikilinks to notes holding a BibTeX record -> cite
        #     markers (before escapes, so a link's own '\|' still resolves)
        has_links = self.cite is not None and "[[" in s
        if has_links:
            s = WIKILINK_RE.sub(self._wikilink, s)
        # 2b. Markdown backslash escapes -> the literal character (never runs
        #     inside the math/code protected above)
        if "\\" in s:
            s = MD_ESCAPE_RE.sub(self._md_escape, s)
        # 2c. drop brackets around citations only; adjacent citations merge
        #     into one \cite{a,b}
        if has_links:
            s = BRACKETED_CITES_RE.sub(r"\1", s)
            s = CITE_GROUP_RE.sub(self._cite_group, s)
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
        s = s.replace(ESC_LBRACK, "{[}").replace(ESC_RBRACK, "{]}")
        # 8. tie references to the preceding character
        return tie_refs(s)


# A reference command is tied to the preceding character with '~' (no line
# break before it). The whitespace between them -- including a newline from a
# wrapped Markdown line -- is replaced; with none, '~' is inserted.
TIE_RE = re.compile(r"(?P<prev>\S)\s*(?P<cmd>\\(?:ref|eqref|cite)(?=[\[{]))")
# ...except after an opening bracket (式(\ref{..}), \footnote{\cite{..}}), an
# existing tie, a backslash (\\ line break) or 第 (第\ref{sec:..}節 is a
# Japanese numeral expression, spaced by LuaTeX-ja itself)
TIE_SKIP_AFTER = set("([{（［｛「『【〔〈《~\\第")


def tie_refs(s):
    """Insert '~' between \\ref / \\eqref / \\cite and the preceding character."""
    def repl(m):
        if m.group("prev") in TIE_SKIP_AFTER:
            return m.group(0)
        return m.group("prev") + "~" + m.group("cmd")
    return TIE_RE.sub(repl, s)


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
# An explicit blank-line marker authors use (e.g. in Obsidian) to force a blank
# line; rendered as a kept paragraph break, never as literal text.
SPAN_RE = re.compile(r"^\s*<span\s*>\s*</span\s*>\s*$")
# First stripped line of an Obsidian callout blockquote: [!type] / [!type]- Title
CALLOUT_HEAD_RE = re.compile(r"^\[!([A-Za-z][\w-]*)\]([+-]?)\s*(.*)$")


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
        or SPAN_RE.match(line)
        # A line-leading '**(x)**' subproblem marker is its own logical unit, so
        # it must start a fresh block even without a surrounding blank line —
        # otherwise a continuation paragraph would swallow the next marker(s),
        # leaving them as literal '\textbf{(b)}' text instead of new \item's.
        or SUBPROBLEM_RE.match(line)
    )


def segment(lines):
    """Split body lines into a list of block dicts.

    Each block records how it was separated from the previous one in the source:
    ``blank_before`` (a blank line preceded it) and ``span_before`` (an explicit
    ``<span></span>`` marker preceded it). The renderer uses these to reproduce
    the source's paragraph structure instead of forcing blank lines everywhere.
    """
    blocks = []
    i = 0
    n = len(lines)
    blank_before = False
    span_before = False

    def push(block):
        block["blank_before"] = blank_before
        block["span_before"] = span_before
        blocks.append(block)

    while i < n:
        line = lines[i]
        if is_blank(line):
            blank_before = True
            i += 1
            continue
        if SPAN_RE.match(line):
            span_before = True
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
            push({"type": "code", "lines": buf})
        elif line.strip().startswith("$$"):
            i_ref = [i]
            push(_collect_math(lines, i_ref))
            i = i_ref[0]
        elif HEADING_RE.match(line):
            m = HEADING_RE.match(line)
            push({"type": "heading", "level": len(m.group(1)), "text": m.group(2)})
            i += 1
        elif IMAGE_RE.match(line):
            m = IMAGE_RE.match(line)
            push({"type": "figure", "file": _image_filename(m),
                  "obsidian": m.group("obsidian") is not None,
                  "caption": None, "human_no": None})
            i += 1
        elif BLOCKQUOTE_RE.match(line):
            buf = []
            while i < n and BLOCKQUOTE_RE.match(lines[i]):
                buf.append(BLOCKQUOTE_RE.match(lines[i]).group(1))
                i += 1
            m = CALLOUT_HEAD_RE.match(buf[0].strip())
            if m:
                push({"type": "callout", "kind": m.group(1).lower(),
                      "title": m.group(3).strip(), "lines": buf[1:]})
            else:
                push({"type": "blockquote", "lines": buf})
        elif "|" in line and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]):
            tbl, i = _collect_table(lines, i)
            push(tbl)
        elif LISTITEM_RE.match(line):
            buf = []
            while i < n and (LISTITEM_RE.match(lines[i]) or
                             (not is_blank(lines[i]) and lines[i].startswith((" ", "\t")) and buf)):
                buf.append(lines[i])
                i += 1
            push({"type": "list", "lines": buf})
        else:
            # paragraph: until blank, a span marker, or a new block start
            buf = [line]
            i += 1
            while i < n and not is_blank(lines[i]) and not is_block_start(lines[i]):
                buf.append(lines[i])
                i += 1
            push({"type": "para", "lines": buf})

        blank_before = False
        span_before = False
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

KNOWN_ENV_RE = re.compile(r"^\s*\\begin\{([A-Za-z*]+)\}")
# Environments that are a display equation on their own (used outside math
# mode); $$ content opening with one is emitted as-is. Any other environment
# (aligned, gathered, split, cases, pmatrix, array, user-defined, ...) only
# works inside math mode, so it is wrapped in equation.
DISPLAY_MATH_ENVS = {
    base + star
    for base in ("equation", "align", "alignat", "gather", "multline",
                 "flalign", "eqnarray")
    for star in ("", "*")
} | {"subequations"}
TAG_RE = re.compile(r"\\tag\{([^}]*)\}")
ENV_NAME_RE = re.compile(r"\\(?:begin|end)\{([A-Za-z*]+)\}")


INDENT_UNIT = "  "
# environments whose body is typeset literally: neither their content nor their
# \end line may be re-indented (spaces before \end{verbatim} print as an extra
# line)
VERBATIM_ENVS = {"verbatim", "verbatim*"}
ENV_TOKEN_RE = re.compile(r"\\(begin|end)\{([A-Za-z*]+)\}")
LEADING_ENDS_RE = re.compile(r"^(?:\s*\\end\{[A-Za-z*]+\})+")


def _code_part(line):
    """The line up to its first unescaped '%' (LaTeX comment start)."""
    m = re.search(r"(?<!\\)(?:\\\\)*%", line)
    return line[:m.start()] if m else line


def indent_environments(text):
    """Re-indent `text` so every line inside an environment is indented by
    INDENT_UNIT per nesting level (\\begin/\\end depth).

    Leading whitespace is insignificant in LaTeX outside verbatim, so existing
    indentation (from the source or the renderer) is replaced, not added to.
    Blank lines stay empty. Verbatim bodies and their \\end line are copied
    unchanged; only the \\begin{verbatim} line is indented.
    """
    out = []
    depth = 0
    verbatim_end = None  # the literal "\end{...}" that closes the current verbatim
    for line in text.split("\n"):
        if verbatim_end is not None:
            out.append(line)
            if verbatim_end in line:
                verbatim_end = None
            continue
        body = line.lstrip()
        if not body:
            out.append("")
            continue
        code = _code_part(body)
        lead = LEADING_ENDS_RE.match(code)
        n_lead = len(ENV_TOKEN_RE.findall(lead.group(0))) if lead else 0
        out.append(INDENT_UNIT * max(0, depth - n_lead) + body)
        for kind, name in ENV_TOKEN_RE.findall(code):
            if kind == "begin" and name in VERBATIM_ENVS:
                # the rest of this line already belongs to the verbatim body
                verbatim_end = "\\end{" + name + "}"
                break
            depth = depth + 1 if kind == "begin" else max(0, depth - 1)
    return "\n".join(out)


def _gap_sep(prev_trail_type, block):
    """Separator to place before `block`, given the previous block's last type.

    In LaTeX a blank line starts a new paragraph, so spacing is meaningful:
    - an explicit ``<span></span>`` marker -> a blank line (paragraph break),
      kept even next to math;
    - a display-math neighbour -> tight (single newline, no blank line) so the
      equation stays inside its surrounding paragraph instead of splitting it;
    - otherwise mirror the source: a blank line only where the source had one.
    """
    if block.get("span_before"):
        return "\n\n"
    if prev_trail_type == "math" or block["type"] == "math":
        return "\n"
    if block.get("blank_before"):
        return "\n\n"
    return "\n"


class Renderer:
    def __init__(self, template, inline, hints, figures=None, heading_shift=0):
        self.template = template
        self.inline = inline
        self.hints = hints
        self.figures = figures          # Figures (copies image files) or None
        self.heading_shift = heading_shift  # 1 in directory mode: H1 -> \section
        self.src_name = None            # current source file (directory mode)
        self.src_dir = Path(".")
        self.used_labels = set()
        self.eq_n = 0
        self.fig_n = 0
        self.tbl_n = 0

    def set_source(self, path, label_in_hints):
        self.src_dir = Path(path).resolve().parent
        self.src_name = Path(path).name if label_in_hints else None

    def hint(self, msg):
        self.hints.append(f"[{self.src_name}] {msg}" if self.src_name else msg)

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
        units = []  # (text, lead_block, trailing_type)
        i = 0
        while i < len(blocks):
            b = blocks[i]
            if (self.template == "exercise" and b["type"] == "para"
                    and SUBPROBLEM_RE.match(b["lines"][0])):
                # A subproblem group runs from the first '**(x)**' marker to the
                # next heading (= section) or EOF. Collect every block in between
                # regardless of type so each marker's body — display math,
                # continuation paragraphs, nested lists, figures/tables — stays
                # inside the environment; render_subproblems re-splits per marker.
                run = []
                while i < len(blocks) and blocks[i]["type"] != "heading":
                    run.append(blocks[i])
                    i += 1
                units.append((self.render_subproblems(run), run[0], run[-1]["type"]))
                continue
            units.append((self.render_block(b), b, b["type"]))
            i += 1

        units = [u for u in units if u[0] is not None and u[0] != ""]
        if not units:
            return ""
        parts = [units[0][0]]
        prev_trail = units[0][2]
        for text, lead, trail in units[1:]:
            parts.append(_gap_sep(prev_trail, lead))
            parts.append(text)
            prev_trail = trail
        return "".join(parts)

    def render_block(self, b):
        return getattr(self, "r_" + b["type"])(b)

    # -- individual blocks --------------------------------------------------
    def r_heading(self, b):
        # directory mode shifts every file's headings down one level, so each
        # file's H1 is a \section and its H2 a \subsection (capped at
        # \subparagraph)
        level = b["level"] + self.heading_shift
        if level == 1:
            self.hint(
                f"Extra H1 heading in body treated as \\section: {b['text']!r}")
            cmd = "section"
        else:
            cmd = SECTION_BY_LEVEL.get(level, "subparagraph")
        return f"\\{cmd}{{{self.inline.convert(b['text'])}}}"

    def r_para(self, b):
        # tie_refs again on the joined lines: a reference opening a wrapped
        # line is pulled up onto the previous one
        return tie_refs("\n".join(self.inline.convert(ln) for ln in b["lines"]))

    def r_code(self, b):
        body = "\n".join(b["lines"])
        return "\\begin{verbatim}\n" + body + "\n\\end{verbatim}"

    def r_blockquote(self, b):
        body = "\n".join(self.inline.convert(ln) for ln in b["lines"] if ln.strip() != "")
        return "\\begin{quote}\n" + body + "\n\\end{quote}"

    def r_callout(self, b):
        kind = b["kind"]
        title = self.inline.convert(b["title"]) if b["title"] else None
        # the callout body is full Markdown -> render it recursively
        inner = self.render(segment(b["lines"]))
        opt = "[{" + title + "}]" if title else ""

        if self.template not in CALLOUT_TEMPLATES:
            # template has no callout environments; degrade to a plain quote
            self.hint(
                f"callout [!{kind}] degraded to quote (template "
                f"'{self.template}' has no callout environments)")
            head = ("\\textbf{" + title + "}\\\\\n") if title else ""
            return "\\begin{quote}\n" + head + inner + "\n\\end{quote}"

        if kind in CALLOUT_THEOREM_MAP:
            env = CALLOUT_THEOREM_MAP[kind]
            if env == "law" and not title:
                self.hint(
                    "callout [!law] has no title, but the law environment "
                    "requires one — add a title in \\begin{callout}[{...}]{law}")
                opt = "[{}]"
            return ("\\begin{callout}" + opt + "{" + env + "}\n"
                    + inner + "\n\\end{callout}")

        if kind in CALLOUT_PLAIN_ENVS:
            # non-boxed run-in env (e.g. sol); title -> heading-override argument
            env = CALLOUT_PLAIN_ENVS[kind]
            return ("\\begin{" + env + "}" + opt + "\n"
                    + inner + "\n\\end{" + env + "}")

        if kind in CALLOUT_BOX_ENVS:
            return ("\\begin{" + kind + "}" + opt + "\n"
                    + inner + "\n\\end{" + kind + "}")

        # unknown type: keep the box (and the author's title) via the fallback env
        self.hint(
            f"callout [!{kind}] is not mapped; rendered as "
            f"'{CALLOUT_FALLBACK_ENV}' box — change the environment if a "
            f"better fit exists (see CALLOUT_THEOREM_MAP / CALLOUT_BOX_ENVS)")
        return ("\\begin{" + CALLOUT_FALLBACK_ENV + "}" + opt + "\n"
                + inner + "\n\\end{" + CALLOUT_FALLBACK_ENV + "}")

    def r_math(self, b):
        inner = list(b["lines"])
        stripped = [ln for ln in inner if ln.strip() != ""]
        m = KNOWN_ENV_RE.match(stripped[0]) if stripped else None
        if m:
            # strip a trailing '\\' on the last row of the environment
            self._strip_last_row_break(inner)
            if m.group(1) in DISPLAY_MATH_ENVS:
                text, _ = self._convert_tags("\n".join(inner))
                return text
        # plain $$...$$, or one opening with a math-mode-only env -> equation
        body = "\n".join(inner).strip("\n")
        body, _ = self._convert_tags(body)
        return "\\begin{equation}\n" + body + "\n\\end{equation}"

    @staticmethod
    def _strip_last_row_break(inner):
        # locate the final \end{env} and strip a trailing '\\' on the last
        # content line before it (matches the spec's align example). In place.
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

    def _convert_tags(self, text):
        labels = []

        def repl(m):
            self.eq_n += 1
            raw = m.group(1)
            safe = re.sub(r"[^0-9A-Za-z]+", "_", raw).strip("_") or str(self.eq_n)
            label = f"eq:eq{safe}"
            # the same \tag{N} may recur (e.g. each merged file restarts at 1)
            k = 2
            while label in self.used_labels:
                label = f"eq:eq{safe}_{k}"
                k += 1
            self.used_labels.add(label)
            labels.append((raw, label))
            return f"\\label{{{label}}}"

        new = TAG_RE.sub(repl, text)
        for raw, label in labels:
            self.hint(
                f"equation \\tag{{{raw}}} -> \\label{{{label}}}  "
                f"(rename to a semantic name if helpful; update its references)")
        return new, labels

    def r_figure(self, b):
        self.fig_n += 1
        label = f"fig:fig{self.fig_n}"
        caption = b["caption"] or ""
        if not caption:
            self.hint(
                f"figure '{b['file']}' has no caption (empty \\caption{{}}); "
                f"label {label}")
        if b.get("human_no"):
            self.hint(
                f"figure source number {b['human_no']} -> {label}")
        path = b["file"]
        if self.figures is not None:
            path = self.figures.place(b["file"], b.get("obsidian", False),
                                      self.src_dir, self.hint)
        return (
            "\\begin{figure}[h]\n"
            "\\centering\n"
            f"\\includegraphics[width=0.65\\linewidth]{{{path}}}\n"
            f"\\caption{{{caption}}}\n"
            f"\\label{{{label}}}\n"
            "\\end{figure}"
        )

    def r_table(self, b):
        self.tbl_n += 1
        label = f"table:table{self.tbl_n}"
        caption = b["caption"] or ""
        if not caption:
            self.hint(
                f"table #{self.tbl_n} has no caption (empty \\caption{{}}); "
                f"label {label}")
        if b.get("human_no"):
            self.hint(
                f"table source number {b['human_no']} -> {label}")
        cols = "".join(b["aligns"])
        lines = []
        lines.append("\\begin{table}[h]")
        lines.append("\\centering")
        lines.append(f"\\caption{{{caption}}}")
        lines.append(f"\\label{{{label}}}")
        lines.append(f"\\begin{{tabular}}{{ {cols} }}")
        lines.append("\\hline")
        lines.append(self._row(b["header"]))
        lines.append("\\hline")
        for row in b["rows"]:
            lines.append(self._row(row))
        lines.append("\\hline")
        lines.append("\\end{tabular}")
        lines.append("\\end{table}")
        return "\n".join(lines)

    def _row(self, cells):
        return " & ".join(self.inline.convert(c) for c in cells) + r" \\"

    def r_list(self, b):
        return render_list(b["lines"], self.inline)

    def render_subproblems(self, run):
        # Split the run into per-item block groups at each '**(x)**' marker. The
        # caller guarantees run[0] is a marker, so no blocks precede the first
        # group; everything between two markers (or after the last one, up to the
        # group boundary) is the body of the preceding item.
        groups = []  # each is [marker_para, *body_blocks]
        for b in run:
            if b["type"] == "para" and SUBPROBLEM_RE.match(b["lines"][0]):
                groups.append([b])
            elif groups:
                groups[-1].append(b)

        items = []
        for g in groups:
            marker = g[0]
            m = SUBPROBLEM_RE.match(marker["lines"][0])
            rest_first = m.group(2)
            other = marker["lines"][1:]
            head_lines = ([rest_first] + other) if rest_first or other else [rest_first]
            body = tie_refs("\n".join(self.inline.convert(ln) for ln in head_lines))
            prev_trail = "para"
            for bb in g[1:]:
                body += _gap_sep(prev_trail, bb) + self.render_block(bb)
                prev_trail = bb["type"]
            items.append("\\item " + body)
        self.hint(
            f"subproblems environment generated from {len(groups)} '**(x)**' "
            f"item(s); confirm the (a)/(b)/... order matches the source")
        return "\\begin{subproblems}\n" + "\n".join(items) + "\n\\end{subproblems}"


def render_list(lines, inline):
    """Stack-based nested list renderer (itemize/enumerate). Output is flat;
    indentation is applied afterwards by indent_environments."""
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
            out.append(f"\\end{{{stack[-1][1]}}}")
            stack.pop()
        if not stack or indent > stack[-1][0]:
            env = env_for(ordered)
            out.append(f"\\begin{{{env}}}")
            stack.append((indent, env))
        out.append("\\item " + inline.convert(content))
    while stack:
        out.append(f"\\end{{{stack[-1][1]}}}")
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


def scan_reference_candidates(body_lines, first_line=1, src_name=None):
    """Return [(location, matched_text)]; location is 'file.md:LINE' (or
    'line N' for a single input), LINE being the line number in the source."""
    found = []
    for idx, line in enumerate(body_lines):
        line_no = first_line + idx
        loc = f"{src_name}:{line_no}" if src_name else f"line {line_no}"
        for pat in REF_PATTERNS:
            for m in pat.finditer(line):
                found.append((loc, m.group(0)))
    return found


# ---------------------------------------------------------------------------
# Obsidian vault: link resolution (citations, embedded figures)
# ---------------------------------------------------------------------------

def find_vault_root(start):
    """Nearest ancestor (inclusive) holding an Obsidian ``.obsidian/`` folder;
    falls back to ``start`` itself."""
    start = Path(start).resolve()
    for d in (start, *start.parents):
        if (d / ".obsidian").is_dir():
            return d
    return start


class Vault:
    """Resolves Obsidian link targets roughly the way Obsidian does: first
    relative to the linking note, then anywhere in the vault by file name
    (case-insensitive; a ``dir/name`` link must match as a path suffix). The
    vault is indexed lazily, only when a lookup misses locally."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self._by_name = None

    def _index(self):
        if self._by_name is None:
            idx = {}
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = sorted(d for d in dirnames
                                     if d not in VAULT_SKIP_DIRS
                                     and not d.startswith("."))
                for fn in sorted(filenames):
                    idx.setdefault(fn.lower(), []).append(Path(dirpath) / fn)
            self._by_name = idx
        return self._by_name

    def find(self, link, src_dir, ext=None):
        """Return (path, other_matches) for an Obsidian link target, or
        (None, []). ``ext`` (e.g. '.md') is tried when the link has none."""
        link = link.strip().replace("\\", "/").lstrip("/")
        if not link:
            return None, []
        forms = [link]
        if ext and not link.lower().endswith(ext):
            forms.insert(0, link + ext)
        for f in forms:
            p = Path(src_dir) / f
            if p.is_file():
                return p.resolve(), []
        for f in forms:
            hits = self._index().get(f.rsplit("/", 1)[-1].lower(), [])
            if "/" in f:
                suffix = "/" + f.lower()
                hits = [h for h in hits if h.as_posix().lower().endswith(suffix)]
            if hits:
                hits = sorted(hits, key=lambda p: (len(p.parts), p.as_posix()))
                return hits[0].resolve(), hits[1:]
        return None, []


# ---------------------------------------------------------------------------
# Citations: [[note]] -> \cite{key}, BibTeX records collected into <stem>.bib
# ---------------------------------------------------------------------------

BIB_ENTRY_HEAD_RE = re.compile(r"@\s*([A-Za-z]+)\s*\{\s*([^,\s{}]+)\s*,")
BIB_NON_ENTRY_TYPES = {"comment", "string", "preamble"}


def split_bib_entries(text):
    """Return [(key, entry_text)] for each brace-balanced @type{key, ...}."""
    out = []
    pos = 0
    for m in BIB_ENTRY_HEAD_RE.finditer(text):
        if m.start() < pos or m.group(1).lower() in BIB_NON_ENTRY_TYPES:
            continue
        depth = 0
        j = text.index("{", m.start())
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            continue  # unbalanced; skip rather than emit a broken record
        out.append((m.group(2), text[m.start():j + 1].strip()))
        pos = j + 1
    return out


def extract_bibtex_blocks(md_text):
    """Concatenated content of every ```bibtex / ```bib fenced block."""
    blocks = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        m = FENCE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        fence = m.group(2)
        lang = (m.group(3).strip().split() or [""])[0].lower()
        buf = []
        i += 1
        while i < len(lines) and not re.match(
                rf"^\s*{re.escape(fence[0])}{{{len(fence)},}}\s*$", lines[i]):
            buf.append(lines[i])
            i += 1
        i += 1
        if lang in BIBTEX_FENCE_LANGS:
            blocks.append("\n".join(buf))
    return "\n".join(blocks)


class Citations:
    """Turns wikilinks to "reference notes" (notes with a ```bibtex block) into
    citation keys and collects each record once (deduplicated by key)."""

    def __init__(self, vault):
        self.vault = vault
        self.entries = {}       # key.lower() -> (key, text, note path)
        self._notes = {}        # note path -> (key, text, n_entries) | None
        self.unresolved = {}    # (src, link) -> reason   (insertion-ordered)
        self.conflicts = []
        self.src_name = None
        self.src_dir = Path(".")

    def set_source(self, path, label_in_hints):
        self.src_dir = Path(path).resolve().parent
        self.src_name = Path(path).name if label_in_hints else None

    def note_record(self, path):
        """(key, text, n_entries) of the first BibTeX record in a note, or None."""
        if path not in self._notes:
            rec = None
            try:
                entries = split_bib_entries(
                    extract_bibtex_blocks(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                entries = []
            if entries:
                rec = (entries[0][0], entries[0][1], len(entries))
            self._notes[path] = rec
        return self._notes[path]

    def resolve_note(self, link_text):
        target = link_text.replace("\\|", "|").split("|", 1)[0]
        note = target.split("#", 1)[0].strip()
        if not note:
            return None
        path, _ = self.vault.find(note, self.src_dir, ".md")
        return path if path is not None and path.suffix.lower() == ".md" else None

    def cite(self, link_text):
        """Inline callback: bib key for a citation wikilink, else None."""
        path = self.resolve_note(link_text)
        if path is None:
            self.unresolved.setdefault((self.src_name, link_text), "note not found")
            return None
        rec = self.note_record(path)
        if rec is None:
            self.unresolved.setdefault((self.src_name, link_text),
                                       f"no ```bibtex block in {path.name}")
            return None
        key, text, n = rec
        known = self.entries.get(key.lower())
        if known is None:
            self.entries[key.lower()] = (key, text, path)
            if n > 1:
                self.conflicts.append(
                    f"{path.name} holds {n} BibTeX records; only the first "
                    f"('{key}') is cited and added")
        elif known[2] != path and _norm_ws(known[1]) != _norm_ws(text):
            self.conflicts.append(
                f"BibTeX key '{key}' appears in both {known[2].name} and "
                f"{path.name} with different content; kept the first")
        return known[0] if known else key


def _norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def write_bib(path, entries):
    """Merge ``entries`` [(key, text)] into the .bib at ``path``: existing
    records are kept verbatim and only keys not yet present are appended.
    Returns (n_added, skipped_keys)."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    have = {m.group(2).lower() for m in BIB_ENTRY_HEAD_RE.finditer(existing)}
    new = [(k, t) for k, t in entries if k.lower() not in have]
    skipped = [k for k, _ in entries if k.lower() in have]
    if new or not path.exists():
        parts = [existing.rstrip()] if existing.strip() else []
        parts += [t for _, t in new]
        path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return len(new), skipped


# ---------------------------------------------------------------------------
# Figures: copy image files next to the .tex (or into --figdir)
# ---------------------------------------------------------------------------

# characters that are unsafe in an \includegraphics file name
_UNSAFE_FIG_CHARS_RE = re.compile(r"[\s#%&{}~$^\\]+")


class Figures:
    def __init__(self, vault, outdir, figdir="."):
        self.vault = vault
        self.dest_dir = (Path(outdir) / figdir).resolve()
        rel = Path(figdir).as_posix().strip("/")
        self.prefix = "" if rel in ("", ".") else rel + "/"
        self.by_src = {}      # source path -> path used in \includegraphics
        self.taken = {}       # dest file name (lower) -> source path
        self.copied = []
        self.missing = []

    def place(self, ref, obsidian, src_dir, hint):
        """Copy the image ``ref`` and return the path for \\includegraphics."""
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", ref):
            hint(f"figure '{ref}' is a remote URL; download it and fix "
                 f"\\includegraphics by hand")
            return ref
        if obsidian:
            src, _ = self.vault.find(ref, src_dir)
        else:
            cand = Path(src_dir) / unquote(ref)
            src = cand.resolve() if cand.is_file() else None
        if src is None:
            self.missing.append(ref)
            hint(f"figure file '{ref}' not found (searched next to the note and "
                 f"in {self.vault.root}); \\includegraphics left as-is")
            return ref
        if src in self.by_src:
            return self.by_src[src]
        name = _UNSAFE_FIG_CHARS_RE.sub("_", src.name)
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        k = 2
        while name.lower() in self.taken and self.taken[name.lower()] != src:
            name = f"{stem}_{k}.{ext}" if ext else f"{stem}_{k}"
            k += 1
        if name != src.name:
            hint(f"figure '{src.name}' copied as '{name}' (unsafe characters "
                 f"or a name clash)")
        self.taken[name.lower()] = src
        dest = self.dest_dir / name
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        if not (dest.exists() and dest.resolve() == src):
            shutil.copy2(src, dest)
        self.copied.append(dest)
        self.by_src[src] = self.prefix + name
        return self.by_src[src]


# ---------------------------------------------------------------------------
# Input loading (single file / directory)
# ---------------------------------------------------------------------------

H1_RE = re.compile(r"^#\s+(.*?)\s*#*\s*$")


def load_md(path):
    """Read one Markdown file -> dict(path, tags, title, body_lines, first_line).

    ``title`` is the first H1 (None if absent); ``body_lines`` are the lines
    after it (the whole post-frontmatter text when there is no H1);
    ``first_line`` is the 1-based source line number of body_lines[0]."""
    path = Path(path)
    tags, after_fm, fm_lines = parse_frontmatter(path.read_text(encoding="utf-8"))
    lines = after_fm.splitlines()
    for k, line in enumerate(lines):
        m = H1_RE.match(line)
        if m:
            return {"path": path, "tags": tags, "title": m.group(1),
                    "body_lines": lines[k + 1:], "first_line": fm_lines + k + 2}
    return {"path": path, "tags": tags, "title": None,
            "body_lines": lines, "first_line": fm_lines + 1}


def natural_key(name):
    """Sort key comparing digit runs numerically: '2_x' < '10_x'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def is_abstract_name(path):
    stem = re.sub(r"^[\d\s._-]+", "", Path(path).stem)
    return stem.lower() in ABSTRACT_STEMS


def collect_dir(dirpath, abstract_opt, citations):
    """Return (abstract_path | None, [chapter paths], hints) for a directory."""
    hints = []
    files = sorted((p for p in Path(dirpath).iterdir()
                    if p.is_file() and p.suffix.lower() == ".md"
                    and not p.name.startswith(".")),
                   key=lambda p: (natural_key(p.name), p.name))
    if abstract_opt:
        abstract = Path(abstract_opt).resolve()
        if not abstract.is_file():
            raise SystemExit(f"error: --abstract file not found: {abstract_opt}")
    else:
        found = [p for p in files if is_abstract_name(p)]
        if len(found) > 1:
            raise SystemExit("error: several abstract files ("
                             + ", ".join(p.name for p in found)
                             + "); choose one with --abstract")
        abstract = found[0].resolve() if found else None
    chapters = [p for p in files if p.resolve() != abstract]

    # Reference notes (cited, holding a ```bibtex block) that live in the same
    # directory are bibliography sources, not chapters.
    chapter_set = {p.resolve() for p in chapters}
    bib_notes = set()
    for p in chapters + ([abstract] if abstract else []):
        citations.set_source(p, False)
        for m in WIKILINK_RE.finditer(p.read_text(encoding="utf-8")):
            t = citations.resolve_note(m.group(1))
            if t in chapter_set and citations.note_record(t) is not None:
                bib_notes.add(t)
    if bib_notes:
        hints.append("reference notes excluded from the body: "
                     + ", ".join(sorted(p.name for p in bib_notes)))
    chapters = [p for p in chapters if p.resolve() not in bib_notes]
    if not chapters:
        raise SystemExit(f"error: no Markdown chapter files in {dirpath}")
    return abstract, chapters, hints


# ---------------------------------------------------------------------------
# Template assembly
# ---------------------------------------------------------------------------

def assemble(template_dir, title_latex, body_latex, abstract_latex=None,
             bib_name=None):
    main = (template_dir / "main.tex").read_text(encoding="utf-8")
    # replace the placeholder title (templates ship literally as \title{title});
    # None keeps the placeholder
    if title_latex is not None:
        main = re.sub(r"\\title\{[^}]*\}",
                      lambda _m: "\\title{" + title_latex + "}", main, count=1)
    # links need hyperref, which the templates do not load; inject it on demand
    # so the output compiles without editing the templates themselves.
    if "\\href" in body_latex and "hyperref" not in main:
        main = main.replace("\\begin{document}",
                            "\\usepackage{hyperref}\n\\begin{document}", 1)
    if bib_name:
        end = main.rfind("\\end{document}")
        main = (main[:end] + f"\\bibliographystyle{{{BIB_STYLE}}}\n"
                f"\\bibliography{{{bib_name}}}\n" + main[end:])
    # insert the (abstract and) body right after \maketitle
    marker = "\\maketitle"
    pos = main.find(marker)
    if pos == -1:
        raise RuntimeError("template main.tex has no \\maketitle")
    insert_at = pos + len(marker)
    head = ""
    if abstract_latex:
        head = "\\begin{abstract}\n" + abstract_latex + "\n\\end{abstract}\n\n"
    # only the generated part is re-indented; the template keeps its own layout
    content = indent_environments(head + body_latex)
    return main[:insert_at] + "\n\n" + content + "\n" + main[insert_at:]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def convert(input_path, outdir, template_override=None, abstract_opt=None,
            vault_opt=None, figdir="."):
    inp = Path(input_path)
    if not inp.exists():
        raise SystemExit(f"error: no such file or directory: {input_path}")
    dir_mode = inp.is_dir()
    if abstract_opt and not dir_mode:
        raise SystemExit("error: --abstract requires a directory input")

    base_dir = inp.resolve() if dir_mode else inp.resolve().parent
    vault = Vault(vault_opt if vault_opt else find_vault_root(base_dir))
    citations = Citations(vault)
    hints = []

    if dir_mode:
        abstract_path, chapter_paths, dir_hints = collect_dir(
            inp, abstract_opt, citations)
        hints += dir_hints
        abstract_doc = load_md(abstract_path) if abstract_path else None
        docs = [load_md(p) for p in chapter_paths]
        stem = inp.resolve().name
        if abstract_doc is None:
            title = None
            hints.append("no abstract file (e.g. 00_abstract.md): \\title{title} "
                         "left as a placeholder — ask the user for the title")
        else:
            title = abstract_doc["title"]
            if title is None:
                hints.append(f"abstract file {abstract_path.name} has no H1: "
                             f"\\title{{title}} left as a placeholder")
        for d in docs:
            if d["title"] is None:
                hints.append(f"[{d['path'].name}] no H1 heading: included "
                             f"without a \\section heading")
    else:
        abstract_doc = None
        docs = [load_md(inp)]
        stem = inp.stem
        title = docs[0]["title"]
        if title is None:
            raise SystemExit("error: no H1 ('# title') heading found; "
                             "nothing to convert")

    all_docs = ([abstract_doc] if abstract_doc else []) + docs
    body_text = "\n".join("\n".join(d["body_lines"]) for d in all_docs)
    if template_override:
        template = template_override
        reason = "forced via --template"
    else:
        tags = [t for d in all_docs for t in d["tags"]]
        template, reason = select_template(tags, body_text)
    if template not in VALID_TEMPLATES:
        raise SystemExit(f"error: unknown template '{template}'")

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    inline = Inline(cite=citations.cite)
    figures = Figures(vault, outdir, figdir)
    renderer = Renderer(template, inline, hints, figures,
                        heading_shift=1 if dir_mode else 0)

    refs = []

    def render_doc(d, with_heading):
        renderer.set_source(d["path"], dir_mode)
        citations.set_source(d["path"], dir_mode)
        blocks = segment(d["body_lines"])
        if with_heading and d["title"] is not None:
            blocks.insert(0, {"type": "heading", "level": 1, "text": d["title"],
                              "blank_before": False, "span_before": False})
        refs.extend(scan_reference_candidates(
            d["body_lines"], d["first_line"],
            d["path"].name if dir_mode else None))
        return renderer.render(blocks)

    abstract_latex = render_doc(abstract_doc, False) if abstract_doc else None
    parts = [render_doc(d, dir_mode) for d in docs]
    body_latex = "\n\n".join(p for p in parts if p)
    title_latex = inline.convert(title) if title is not None else None

    for (src, link), reason_ in citations.unresolved.items():
        where = f"[{src}] " if src else ""
        hints.append(f"{where}wikilink [[{link}]] is not a citation ({reason_}); "
                     f"left as literal text — rewrite or remove it")
    hints += citations.conflicts

    template_dir = Path(__file__).resolve().parent.parent / "templates" / template
    bib_name = stem if citations.entries else None
    tex = assemble(template_dir, title_latex, body_latex, abstract_latex,
                   bib_name)

    tex_out = outdir / f"{stem}.tex"
    latexmkrc_out = outdir / "latexmkrc"
    tex_out.write_text(tex, encoding="utf-8")
    # The template latexmkrc names main.tex as its default target; point it at
    # the actual output stem so a bare `latexmk` (no file argument) builds it.
    latexmkrc = (template_dir / "latexmkrc").read_text(encoding="utf-8")
    latexmkrc = re.sub(
        r"(@default_files\s*=\s*\(\s*')main\.tex('\s*\)\s*;)",
        rf"\g<1>{stem}.tex\g<2>",
        latexmkrc,
    )
    latexmkrc_out.write_text(latexmkrc, encoding="utf-8")
    written = [tex_out, latexmkrc_out]

    # templates that split their preamble into config.tex (\input{config})
    # need that file next to the generated .tex
    config_src = template_dir / "config.tex"
    if config_src.exists():
        config_out = outdir / "config.tex"
        config_out.write_text(config_src.read_text(encoding="utf-8"),
                              encoding="utf-8")
        written.append(config_out)

    if bib_name:
        bib_out = outdir / f"{stem}.bib"
        entries = [(k, t) for k, t, _ in citations.entries.values()]
        added, skipped = write_bib(bib_out, entries)
        written.append(bib_out)
        hints.append(f"bibliography: {len(entries)} cited record(s), {added} "
                     f"added to {bib_out.name}"
                     + (f"; already present, kept as-is: {', '.join(skipped)}"
                        if skipped else "")
                     + f" (style {BIB_STYLE})")
    if figures.copied:
        written.append(f"{len(figures.copied)} figure file(s) -> "
                       f"{figures.dest_dir}")

    _print_report(template, reason, written, hints, refs)
    return tex_out


def _print_report(template, reason, written, hints, refs):
    e = sys.stderr
    print("=" * 70, file=e)
    print("md2latex: conversion complete", file=e)
    print("=" * 70, file=e)
    print(f"template : {template}  ({reason})", file=e)
    print(f"written  : {written[0]}", file=e)
    for path in written[1:]:
        print(f"           {path}", file=e)
    print("", file=e)
    print("POST-EDIT HINTS (agent: handle only these, then compile):", file=e)
    if not hints:
        print("  - none (mechanical conversion is self-contained)", file=e)
    for h in hints:
        print(f"  - {h}", file=e)
    if refs:
        print("", file=e)
        print("  Cross-reference CANDIDATES in the source (rewrite to \\eqref/\\ref"
              " using the label map above; verify each). Put a non-breaking"
              " space '~' before the macro, e.g. 式~\\eqref{eq:..}, 図~\\ref{fig:..}:",
              file=e)
        for loc, text in refs:
            print(f"    {loc}: {text}", file=e)
    print("=" * 70, file=e)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert Markdown to LaTeX.")
    ap.add_argument("markdown",
                    help="input Markdown file, or a directory whose *.md files "
                         "are merged in natural filename order")
    ap.add_argument("--outdir", default=".", help="output directory (default: cwd)")
    ap.add_argument("--template", choices=sorted(VALID_TEMPLATES),
                    help="force a template instead of auto-selecting")
    ap.add_argument("--abstract",
                    help="(directory input) abstract file; default: the file "
                         "named 'abstract' (e.g. 00_abstract.md) if any")
    ap.add_argument("--vault",
                    help="root for resolving Obsidian [[links]] / ![[embeds]] "
                         "(default: nearest ancestor with .obsidian/, else the "
                         "input's directory)")
    ap.add_argument("--figdir", default=".",
                    help="where to copy figure files, relative to --outdir "
                         "(default: '.', i.e. next to the .tex)")
    args = ap.parse_args(argv)
    convert(args.markdown, args.outdir, args.template, args.abstract,
            args.vault, args.figdir)


if __name__ == "__main__":
    main()
