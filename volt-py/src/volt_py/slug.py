"""Load-order folder naming (port of Electron's src/electron/lib/slug.js,
SCOPE.md §2a): lowercase, punctuation stripped, spaces -> "-".
"My first load order!" -> "my-first-load-order".

Stdlib re has no \\p{L}/\\p{M}/\\p{N}, so letter/mark/number is tested per
character with unicodedata.category instead.
"""

import re
import unicodedata

WINDOWS_RESERVED = re.compile(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])")
MAX_LEN = 64


def _is_lmn(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LMN"


def slugify(name) -> str:
    s = unicodedata.normalize("NFC", "" if name is None else str(name)).lower()
    # Keep letters (any script), marks, digits, whitespace, hyphens.
    s = "".join(ch for ch in s if ch == "-" or ch.isspace() or _is_lmn(ch))
    s = re.sub(r"-+", "-", re.sub(r"\s+", "-", s.strip())).strip("-")
    if len(s) > MAX_LEN:
        s = s[:MAX_LEN].rstrip("-")
    s = s or "load-order"
    if WINDOWS_RESERVED.fullmatch(s):
        s += "-load-order"
    return s


def is_valid_slug(s) -> bool:
    """A slug as it may arrive from the UI: no dots or separators, so it can
    never escape the load-orders folder."""
    return isinstance(s, str) and 0 < len(s) <= MAX_LEN + 8 and all(ch == "-" or _is_lmn(ch) for ch in s)
