"""XML helpers for RimWorld's files (About.xml, ModsConfig.xml).

Behavioral port of Electron's src/electron/lib/xml.js, built on stdlib
ElementTree instead of fast-xml-parser's dict shape: lookups work on child
elements, values are always strings, and list_() always returns a list.
Attributes are never consulted (the JS parser ignored them too).
"""

import xml.etree.ElementTree as ET


def parse_xml(text: str) -> ET.Element:
    """Root element. Raises ET.ParseError on malformed XML."""
    return ET.fromstring(str(text).removeprefix("﻿"))


def _ci(element: ET.Element | None, tag: str):
    if element is None:
        return
    lower = tag.lower()
    for child in element:
        if isinstance(child.tag, str) and child.tag.lower() == lower:
            yield child


def get_ci(element: ET.Element | None, tag: str) -> ET.Element | None:
    """First direct child whose tag matches case-insensitively (exact match
    first) - RimWorld's own loader is lenient about tag casing."""
    if element is None:
        return None
    exact = next((c for c in element if c.tag == tag), None)
    return exact if exact is not None else next(_ci(element, tag), None)


def text(node: ET.Element | None) -> str:
    """Leaf text, stripped; '' for None."""
    return "" if node is None else (node.text or "").strip()


def list_(element: ET.Element | None) -> list[str]:
    """<foo><li>a</li><li>b</li></foo> -> ['a', 'b']"""
    return [t for li in _ci(element, "li") if (t := text(li))]


def list_field(element: ET.Element | None, field: str) -> list[str]:
    """<foo><li><packageId>a</packageId>...</li>...</foo>, field 'packageId'
    -> ['a', ...]. Entries without the field (or plain-text <li>s) are skipped."""
    return [t for li in _ci(element, "li") if (t := text(get_ci(li, field)))]


def escape_xml(s) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
