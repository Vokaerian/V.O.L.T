"""Minimal parser for Valve's KeyValues text format (port of Electron's
src/electron/lib/vdf.js). Used for libraryfolders.vdf and appmanifest_*.acf.

Returns nested plain dicts; all leaf values are strings.
"""

from typing import Any


def parse_vdf(src: str) -> dict:
    src = str(src)
    n = len(src)
    i = 0

    def skip() -> None:
        nonlocal i
        while True:
            while i < n and src[i].isspace():
                i += 1
            if src.startswith("//", i):
                while i < n and src[i] != "\n":
                    i += 1
                continue
            # Conditional suffixes like [$WIN32] - ignored.
            if i < n and src[i] == "[":
                while i < n and src[i] != "]":
                    i += 1
                i += 1
                continue
            return

    def read_string() -> str:
        nonlocal i
        if i < n and src[i] == '"':
            i += 1
            out = []
            while i < n and src[i] != '"':
                if src[i] == "\\" and i + 1 < n:
                    c = src[i + 1]
                    out.append("\n" if c == "n" else "\t" if c == "t" else c)
                    i += 2
                else:
                    out.append(src[i])
                    i += 1
            if i >= n:
                raise ValueError("VDF: unterminated string")
            i += 1
            return "".join(out)
        start = i
        while i < n and not (src[i].isspace() or src[i] in '{}"'):
            i += 1
        if i == start:
            ch = src[i] if i < n else ""
            raise ValueError(f'VDF: unexpected character "{ch}" at offset {i}')
        return src[start:i]

    def read_object(top: bool) -> dict:
        nonlocal i
        obj: dict = {}
        while True:
            skip()
            if i >= n:
                if top:
                    return obj
                raise ValueError("VDF: unexpected end of input")
            if src[i] == "}":
                if top:
                    raise ValueError('VDF: unmatched "}"')
                i += 1
                return obj
            key = read_string()
            skip()
            if i < n and src[i] == "{":
                i += 1
                obj[key] = read_object(False)
            else:
                obj[key] = read_string()

    return read_object(True)


def get_ci(obj: Any, key: str) -> Any:
    """Case-insensitive dict lookup ("AppState" vs "appstate"); exact key first.

    None for non-dict input or no match (JS returns undefined in both cases).
    """
    if not isinstance(obj, dict):
        return None
    if key in obj:
        return obj[key]
    lower = key.lower()
    for k, v in obj.items():
        if k.lower() == lower:
            return v
    return None
