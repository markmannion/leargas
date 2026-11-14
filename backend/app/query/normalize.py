"""Turn a question into (template, args) so translations and different room names collapse together.

    "How many rooms labelled 'Küche' are there on this floor?"
        -> ("How many rooms labelled <S> are there on this floor?", [("S", "Küche")])
    "What is the net floor area of room 7.01 ('Balkon') in m²?"
        -> ("What is the net floor area of room <N> (<S>) in m²?", [("N", "7.01"), ("S", "Balkon")])
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Quoted spans in any of the quote styles the dataset uses. A straight-quote span may contain
# apostrophes followed by a letter ('l'escalier'), and must open at a word boundary.
_QUOTED = re.compile(
    r"(?<!\w)'((?:[^']|'(?=\w))*)'(?=[\s?,.:;)]|$)"
    r"|«\s*([^»]*?)\s*»"
    r"|„([^“”\"]*)[“”\"]"
    r"|“([^”]*)”"
    r"|\"([^\"]*)\""
    r"|‘([^’]*)’"
    r"|’([^’]*)’"
)
# Room numbers and plain numbers: 7.01, U1.03, 12
_NUMBER = re.compile(r"(?<![\w.])([A-Z]{0,2}\d+(?:[.,]\d+)*)(?![\w])")
# Apartment letters: "apartment B", "Wohnung B", "l'appartement B", ...
_APT = re.compile(
    r"(?i:\b(apartment|wohnung|appartement|appartamento|apartamento|asunto|lejlighed|appartment))\s+([A-Z])\b"
)

Arg = Tuple[str, str]  # (kind, value): kind in S (quoted), N (number/id), L (apartment letter)


def normalize(question: str) -> Tuple[str, List[Arg]]:
    q = " ".join(question.strip().split())
    spans: List[Tuple[int, int, str, str]] = []

    for m in _QUOTED.finditer(q):
        val = next(g for g in m.groups() if g is not None)
        spans.append((m.start(), m.end(), "S", val))

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e, _, _ in spans)

    for m in _APT.finditer(q):
        if free(m.start(2), m.end(2)):
            spans.append((m.start(2), m.end(2), "L", m.group(2)))
    for m in _NUMBER.finditer(q):
        if free(m.start(1), m.end(1)):
            spans.append((m.start(1), m.end(1), "N", m.group(1)))

    spans.sort()
    out, args, pos = [], [], 0
    for s, e, kind, val in spans:
        out.append(q[pos:s])
        out.append(f"<{kind}>")
        args.append((kind, val))
        pos = e
    out.append(q[pos:])
    return "".join(out), args
