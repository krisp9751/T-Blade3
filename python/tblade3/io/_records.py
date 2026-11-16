"""Positional reading of T-Blade3 input files the way the Fortran reader does it.

``Records`` is a cursor over the lines (records) of a file. ``line()`` is ``read(u,'(A)')``,
``values()`` is a list-directed ``read(u,*)``: it may span several records, skips blank records,
honours commas, slashes and repeat counts, and ignores the rest of the last record it touched.
Number formatting helpers for the writers live here too.
"""
from __future__ import annotations

import re

from ..errors import InputFormatError

_INT_RE = re.compile(r"^[+-]?\d+$")
_REAL_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+))(?:([eEdDqQ])([+-]?\d+)|([+-]\d+))?$")
_SPECIAL_RE = re.compile(r"^[+-]?(inf|infinity|nan(\(.*\))?)$", re.IGNORECASE)
_REPEAT_RE = re.compile(r"^(\d+)\*(.*)$")
_SLASH = object()


def fortran_real(token: str) -> float | None:
    """The value Fortran reads from ``token`` as a real, or None if it is not a valid real."""
    m = _REAL_RE.match(token)
    if m:
        mant, _, exp1, exp2 = m.groups()
        exp = exp1 if exp1 is not None else exp2
        return float(mant if exp is None else f"{mant}e{exp}")
    m = _SPECIAL_RE.match(token)
    if m:
        return float(token.split("(")[0])
    return None


def fortran_int(token: str) -> int | None:
    return int(token) if _INT_RE.match(token) else None


def _split_record(rec: str, last: str) -> tuple[list, str]:
    """List-directed tokens of one record: strings, None (null value) or _SLASH (ends the read).

    ``last`` is 'comma' or 'value': what preceded this record within the same read.
    """
    out: list = []
    i, n = 0, len(rec)
    while i < n:
        c = rec[i]
        if c in " \t\r":
            i += 1
        elif c == ",":
            if last == "comma":
                out.append(None)
            last = "comma"
            i += 1
        elif c == "/":
            out.append(_SLASH)
            return out, last
        elif c in "'\"":
            j, buf = i + 1, []
            while j < n:
                if rec[j] == c:
                    if j + 1 < n and rec[j + 1] == c:
                        buf.append(c)
                        j += 2
                        continue
                    break
                buf.append(rec[j])
                j += 1
            out.append("".join(buf))
            last = "value"
            i = j + 1
        else:
            j = i
            while j < n and rec[j] not in " \t\r,/":
                j += 1
            token = rec[i:j]
            m = _REPEAT_RE.match(token)
            if m:
                out.extend([m.group(2) or None] * int(m.group(1)))
            else:
                out.append(token)
            last = "value"
            i = j
    return out, last


class Records:
    """Cursor over the records of a text file, mirroring Fortran sequential reads."""

    def __init__(self, text: str, filename: str = "input file"):
        self.lines = [line.rstrip("\r") for line in text.splitlines()]
        self.pos = 0
        self.filename = filename

    def error(self, what: str, lineno: int | None = None) -> InputFormatError:
        lineno = self.pos if lineno is None else lineno
        got = self.lines[lineno - 1] if 0 < lineno <= len(self.lines) else "end of file"
        return InputFormatError(f"{self.filename}, line {lineno}: expected {what}, got {got!r}")

    @property
    def at_end(self) -> bool:
        return self.pos >= len(self.lines)

    def line(self, what: str = "a label line") -> str:
        """read(u,'(A)'): the next record, whatever it holds."""
        if self.pos >= len(self.lines):
            raise InputFormatError(f"{self.filename}: expected {what}, got end of file")
        self.pos += 1
        return self.lines[self.pos - 1]

    def lines_n(self, n: int, what: str = "label lines") -> list[str]:
        return [self.line(what) for _ in range(n)]

    def rest(self) -> list[str]:
        out = self.lines[self.pos:]
        self.pos = len(self.lines)
        return out

    def raw(self, n: int, what: str) -> tuple[list, int, int]:
        """List-directed read of ``n`` items as raw tokens (None = null / not filled).

        Returns (tokens, first record number, last record number), 1-based.
        """
        out: list = []
        last = "comma"
        first = None
        while len(out) < n:
            if self.pos >= len(self.lines):
                raise InputFormatError(f"{self.filename}: expected {what}, got end of file")
            rec = self.lines[self.pos]
            self.pos += 1
            tokens, last = _split_record(rec, last)
            if tokens and first is None:
                first = self.pos
            for t in tokens:
                if t is _SLASH:
                    out.extend([None] * (n - len(out)))
                    break
                out.append(t)
                if len(out) == n:
                    break
            if tokens and tokens[-1] is _SLASH:
                break
        return out[:n], first or self.pos, self.pos

    def values(self, kinds: str, what: str) -> list:
        """List-directed read: ``kinds`` holds one letter per item, i (integer), f (real), s (string)."""
        tokens, first, last = self.raw(len(kinds), what)
        out = []
        for k, t in zip(kinds, tokens):
            if t is None:
                if k == "s":
                    out.append(None)
                    continue
                raise self.error(what, last)
            if k == "i":
                v = fortran_int(t)
            elif k == "f":
                v = fortran_real(t)
            else:
                v = t
            if v is None:
                raise self.error(what, last)
            out.append(v)
        return out


# --------------------------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------------------------

def num(x) -> str:
    """Shortest text that reads back to exactly the same double (or integer)."""
    if isinstance(x, (bool,)):
        return str(int(x))
    if isinstance(x, int) or (hasattr(x, "dtype") and getattr(x.dtype, "kind", "") in "iu"):
        return str(int(x))
    return repr(float(x))


def row(values, width: int = 22) -> str:
    return "".join(f"{num(v):>{width}}" for v in values)


def first_token(line: str) -> str | None:
    """First list-directed token of a line (None for a blank line or a null value)."""
    tokens, _ = _split_record(line, "comma")
    if not tokens or tokens[0] is _SLASH:
        return None
    return tokens[0]
