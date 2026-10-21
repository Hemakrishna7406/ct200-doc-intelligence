"""Hierarchy reconstruction — turning flat extracted lines into a tree.

This is the heart of the parser and where every structural irregularity in the
CT-200 manual is handled. The rules, and why:

1. **Headings are detected from typography + numbering, but their *level* comes
   from the number's depth, not its font size.** In this document ``3.2 Cuff
   Inflation Sequence`` is rendered at *body* size (11pt) while ``2.1.1.1`` is a
   level-4 number under a level-2 parent. Trusting font size for level would
   mis-place both. So: a line is a heading if it is **bold** and starts with a
   section number; its level is ``len(number.split('.'))``.

2. **The tree is built by a depth stack, then children are re-sorted by their
   numeric key.** Section ``3.4`` physically precedes ``3.3`` in the PDF; both
   are children of ``3``, and the tree presents them as 3.3 then 3.4. The
   original physical order is preserved in ``source_order``.

3. **A skipped level re-attaches to the nearest existing ancestor.** ``2.1.1.1``
   has no ``2.1.1`` parent, so it hangs off ``2.1`` and is flagged
   ``skipped_level`` — surfaced, never silently renumbered.

4. **Duplicate titles are kept as distinct nodes** because their numeric paths
   differ: ``4.2 Error Codes`` and ``7.1 Error Codes`` are two nodes with two
   parents.

5. **Body text is assembled across page boundaries.** Because we work on one
   merged reading-order stream, a paragraph split by a page break is joined
   back into one node rather than truncated at the page edge.

6. **Table cell lines are removed from body text** and re-emitted as dedicated
   ``table`` child nodes, so a spec table never leaks into the prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.parsing.extract import ExtractionResult, Line, TableBlock
from app.textutil import content_hash, content_hash_table, normalize_text

_HEADING_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<title>[^\s].*)$")
_LIST_RE = re.compile(r"^(?:\d+\.|[-•*])\s+\S")

MAX_TITLE_LEN = 90


@dataclass
class ParsedNode:
    logical_key: str
    number: str | None
    heading: str
    level: int
    kind: str = "section"
    body_text: str = ""
    source_order: int = 0
    parent_key: str | None = None
    table: list[list[str | None]] | None = None
    anomalies: list[dict] = field(default_factory=list)

    @property
    def sort_key(self) -> tuple:
        if self.number:
            return (0, tuple(int(x) for x in self.number.split(".")))
        return (1, (self.source_order,))


@dataclass
class ParseResult:
    nodes: list[ParsedNode]
    title: str
    body_size: float
    warnings: list[str] = field(default_factory=list)
    anomalies: list[dict] = field(default_factory=list)


def _num_key(num: str) -> tuple[int, ...]:
    return tuple(int(x) for x in num.split("."))


def _detect_body_size(lines: list[Line]) -> float:
    counts: dict[float, int] = {}
    for ln in lines:
        if not ln.bold and ln.size:
            counts[ln.size] = counts.get(ln.size, 0) + 1
    if not counts:
        return 11.0
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _line_in_table(ln: Line, tables: list[TableBlock]) -> bool:
    for t in tables:
        if t.page != ln.page:
            continue
        x0, y0, x1, y1 = t.bbox
        if x0 - 2 <= ln.x0 <= x1 + 2 and y0 - 2 <= ln.y0 <= y1 + 2:
            return True
    return False


def _merge_body(lines: list[str]) -> str:
    """Join wrapped prose into paragraphs, keeping list items on their own lines."""
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append(" ".join(buf).strip())
            buf.clear()

    for ln in lines:
        if _LIST_RE.match(ln.strip()):
            flush()
            out.append(ln.strip())
        else:
            buf.append(ln.strip())
    flush()
    return "\n".join(p for p in out if p)


def _classify(
    lines: list[Line], body_size: float
) -> list[tuple[str, Line, str | None, str | None]]:
    """Return (kind, line, number, title) tuples.

    kind ∈ {"heading", "body"}. Heading level is derived later from ``number``.
    """
    classified: list[tuple[str, Line, str | None, str | None]] = []
    seen_top: set[str] = set()
    for ln in lines:
        m = _HEADING_RE.match(ln.text)
        is_heading = False
        num = title = None
        if m and ln.bold:
            cand_num = m.group("num")
            cand_title = m.group("title").strip()
            ok = (
                len(cand_title) <= MAX_TITLE_LEN
                and not cand_title.endswith(".")
                and cand_title[:1].isupper()
            )
            if ok and "." not in cand_num:
                # a bare integer is only a top-level heading if it is the next
                # one in sequence — this is what stops "1. Normal: ..." list
                # items inside section 3.3 from being read as top-level sections
                expected = str(len(seen_top) + 1)
                ok = cand_num == expected and cand_num not in seen_top
            if ok:
                is_heading = True
                num, title = cand_num, cand_title
                if "." not in cand_num:
                    seen_top.add(cand_num)
        classified.append(("heading" if is_heading else "body", ln, num, title))
    return classified


def parse(extraction: ExtractionResult) -> ParseResult:
    lines = sorted(extraction.lines, key=lambda line: line.order)
    tables = extraction.tables
    body_size = _detect_body_size(lines)

    # Drop table cell lines from the prose stream.
    prose = [ln for ln in lines if not _line_in_table(ln, tables)]

    classified = _classify(prose, body_size)

    # --- title: any leading lines before the first heading ------------------ #
    title_lines: list[str] = []
    idx = 0
    while idx < len(classified) and classified[idx][0] != "heading":
        title_lines.append(classified[idx][1].text)
        idx += 1
    title = " ".join(title_lines).strip()

    nodes: list[ParsedNode] = []
    warnings: list[str] = list(extraction.warnings)
    doc_anomalies: list[dict] = []

    if title:
        nodes.append(
            ParsedNode(
                logical_key="title",
                number=None,
                heading=title,
                level=0,
                kind="document",
                source_order=-1,
            )
        )

    # --- build sections with a depth stack ---------------------------------- #
    stack: list[ParsedNode] = [nodes[0]] if nodes else []
    heading_positions: list[tuple[ParsedNode, int, float]] = []  # node, page, y0
    seen_titles: dict[str, list[str]] = {}
    current: ParsedNode | None = None

    for kind, ln, num, htitle in classified[idx:]:
        if kind == "heading":
            depth = num.count(".") + 1
            parent: ParsedNode | None = None
            while stack and stack[-1].level >= depth:
                stack.pop()
            parent = stack[-1] if stack else (nodes[0] if nodes else None)

            node = ParsedNode(
                logical_key=num,
                number=num,
                heading=htitle,
                level=depth,
                source_order=ln.order,
                parent_key=parent.logical_key if parent else None,
            )

            anomalies: list[dict] = []
            if parent is not None and depth > parent.level + 1:
                a = {
                    "code": "skipped_level",
                    "node_key": num,
                    "detail": (
                        f"number depth {depth} but nearest ancestor is "
                        f"'{parent.logical_key}' (level {parent.level}); "
                        f"re-attached to it"
                    ),
                }
                anomalies.append(a)

            # out-of-order sibling? (a smaller numeric key appeared earlier)
            if parent is not None:
                sibs = [n for n in nodes if n.parent_key == parent.logical_key and n.number]
                for sib in sibs:
                    if _num_key(sib.number) > _num_key(num):
                        anomalies.append(
                            {
                                "code": "out_of_order_section",
                                "node_key": num,
                                "detail": (
                                    f"section {num} appears after sibling "
                                    f"{sib.number} in the PDF; tree order follows "
                                    "the numeric key"
                                ),
                            }
                        )
                        break

            norm_title = normalize_text(htitle).lower()
            if seen_titles.get(norm_title):
                anomalies.append(
                    {
                        "code": "duplicate_heading_title",
                        "node_key": num,
                        "detail": (
                            f"heading text {htitle!r} also appears at "
                            f"{', '.join(seen_titles[norm_title])}; kept as distinct "
                            "nodes because their section numbers differ"
                        ),
                    }
                )
            seen_titles.setdefault(norm_title, []).append(num)

            node.anomalies.extend(anomalies)
            doc_anomalies.extend(anomalies)
            nodes.append(node)
            stack.append(node)
            heading_positions.append((node, ln.page, ln.y0))
            current = node
        else:
            if current is not None:
                current.body_text = (current.body_text + "\n" + ln.text).strip()

    # --- tables → child nodes of the heading that precedes them ------------- #
    for t in tables:
        owner = None
        for node, page, y0 in heading_positions:
            if (page, y0) <= (t.page, t.bbox[1]):
                owner = node
            else:
                break
        owner_key = owner.logical_key if owner else (nodes[0].logical_key if nodes else "title")
        n_existing = sum(1 for n in nodes if n.parent_key == owner_key and n.kind == "table")
        key = f"{owner_key}#table{n_existing + 1}"
        nodes.append(
            ParsedNode(
                logical_key=key,
                number=None,
                heading=f"Table {n_existing + 1}",
                level=(owner.level + 1) if owner else 1,
                kind="table",
                parent_key=owner_key,
                table=t.rows,
                source_order=owner.source_order + 1 if owner else 0,
            )
        )

    # --- finalise body text + hashes ---------------------------------------- #
    for node in nodes:
        if node.kind == "table":
            node.body_text = ""
        else:
            node.body_text = _merge_body(node.body_text.split("\n")) if node.body_text else ""

    return ParseResult(
        nodes=nodes, title=title, body_size=body_size,
        warnings=warnings, anomalies=doc_anomalies,
    )


def node_content_hash(node: ParsedNode) -> str:
    """Content hash used for change/staleness detection.

    * tables hash their cells,
    * the document/title node hashes its heading,
    * sections hash **heading + body**, so renaming a section is also a change.
    """
    if node.kind == "table" and node.table is not None:
        return content_hash_table(node.table)
    if node.kind == "document":
        return content_hash(node.heading)
    return content_hash(f"{node.heading}\n{node.body_text}")
