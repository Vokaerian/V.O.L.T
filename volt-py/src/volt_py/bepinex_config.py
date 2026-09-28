"""The Edit Config data layer (THUNDERSTORE.md §7): the files a load order's
mods wrote under its `BepInEx/config/`, and BepInEx's own `ConfigFile`
format parsed into a structured form (and written back).

No Qt in here - screens/bepinex_config_window.py is the split-pane window
over this; tools/checks/volt_py_bepinex_config.py drives this module
against real generated files (temp/Vinland).

The .cfg format, read from BepInEx.Core/Configuration/ConfigFile.cs
(`Save` / `Reload`) and ConfigEntryBase.cs (`WriteDescription`):

    ## Settings file was created by plugin <Name> v<Version>     <- header,
    ## Plugin GUID: <GUID>                                           only when
                                                                     the owner
    [Section]                                                        is known

    ## <Description>                <- every line of a multi-line one
    # Setting type: <CLR type name>
    # Default value: <serialized default>
    # Acceptable values: A, B, C     <- an AcceptableValueList or any enum
    # Multiple values can be set at the same time by separating them with , (e.g. Debug, Warning)
                                     <- a [Flags] enum only
    # Acceptable value range: From <min> to <max>   <- an AcceptableValueRange
    Key = Value

Only the `[Section]` and `Key = Value` lines are data: BepInEx's `Reload`
trims each line, skips anything starting with `#`, tracks `[...]` and splits
the rest on the first `=` (both halves trimmed). The comment lines are a
courtesy written fresh from the live ConfigDescription on every `Save`
(`GenerateSettingDescriptions`, default true - a plugin can turn them off,
leaving bare Key = Value pairs), never read back. So this parser collects
the comment block directly above each `Key = Value` line as that entry's
metadata, and the writer leaves every byte it doesn't own alone: a save
replaces only the `Key = Value` lines whose value changed (BepInEx's next
Save regenerates the same comments anyway), so an unchanged document renders
back byte-for-byte - CRLF, mixed line endings, a BOM, stray comments
(shudnal.ConditionalConfigSync's policy files are nothing but `# ` notes)
and orphaned entries all survive.

Serialized value formats (TomlTypeConverter.cs / UnityTomlTypeConverters.cs /
KeyboardShortcut.cs): strings as written (BepInEx escapes a newline as the
two characters `\\n`, so a value can never span lines); bool `true`/`false`;
numbers plain; enums by name, a [Flags] enum as `A, B`; Color = RRGGBBAA hex,
no `#`; KeyboardShortcut = `MainKey` or `MainKey + Modifier + ...` (main key first,
modifiers in enum order; `None` when unset - "Not set" is only its display
string), any KeyCode name, with or without an Acceptable values line
(UNITY_KEYCODES below is the picker list either way); Vector2/3/4 /
Quaternion / Rect as JSON - shown as text.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .bepinex_install import CONFIG_FOLDER
from .fsutil import write_text_atomic

# Shown by default in the file browser; anything else needs "Show all files"
# (.dat saves, .oprint blueprint exports and other data some mods keep under
# config/ aren't meant to be hand-edited - THUNDERSTORE.md §7's open call,
# settled at build time in favor of the filter).
TEXT_EXTENSIONS = {".cfg", ".json", ".yml", ".yaml", ".txt", ".ini", ".xml", ".toml", ".md"}
SORT_KEYS = ("name", "modified", "type")
SORT_LABELS = {"name": "Sort: Name", "modified": "Sort: Modified", "type": "Sort: Type"}

_SETTING_TYPE = "# Setting type:"
_DEFAULT = "# Default value:"
_ACCEPTABLE = "# Acceptable values:"
_RANGE = re.compile(r"^# Acceptable value range: From (.*?) to (.*)$")
_FLAGS = "# Multiple values can be set"
_PLUGIN_HEADER = re.compile(r"^## Settings file was created by plugin (.*) v(\S+)$")
_GUID_HEADER = "## Plugin GUID:"

# Unity's KeyCode enum names, in enum order (what a KeyboardShortcut's own
# `# Acceptable values` line lists when a plugin bothers to attach one - most
# don't: 25 of the 28 KeyboardShortcut entries in temp/Vinland have no list at
# all, so the picker needs this table). Captured from a real generated file
# (Azumatt.AzuClock.cfg's "Show Clock Key" line).
UNITY_KEYCODES = (
    "None", "Backspace", "Tab", "Clear", "Return", "Pause", "Escape", "Space", "Exclaim",
    "DoubleQuote", "Hash", "Dollar", "Percent", "Ampersand", "Quote", "LeftParen", "RightParen",
    "Asterisk", "Plus", "Comma", "Minus", "Period", "Slash", "Alpha0", "Alpha1", "Alpha2",
    "Alpha3", "Alpha4", "Alpha5", "Alpha6", "Alpha7", "Alpha8", "Alpha9", "Colon", "Semicolon",
    "Less", "Equals", "Greater", "Question", "At", "LeftBracket", "Backslash", "RightBracket",
    "Caret", "Underscore", "BackQuote", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K",
    "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "LeftCurlyBracket", "Pipe", "RightCurlyBracket", "Tilde", "Delete", "Keypad0", "Keypad1",
    "Keypad2", "Keypad3", "Keypad4", "Keypad5", "Keypad6", "Keypad7", "Keypad8", "Keypad9",
    "KeypadPeriod", "KeypadDivide", "KeypadMultiply", "KeypadMinus", "KeypadPlus",
    "KeypadEnter", "KeypadEquals", "UpArrow", "DownArrow", "RightArrow", "LeftArrow", "Insert",
    "Home", "End", "PageUp", "PageDown", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9",
    "F10", "F11", "F12", "F13", "F14", "F15", "Numlock", "CapsLock", "ScrollLock", "RightShift",
    "LeftShift", "RightControl", "LeftControl", "RightAlt", "LeftAlt", "RightMeta", "RightMeta",
    "RightMeta", "LeftMeta", "LeftMeta", "LeftMeta", "LeftWindows", "RightWindows", "AltGr",
    "Help", "Print", "SysReq", "Break", "Menu", "WheelUp", "WheelDown", "Mouse0", "Mouse1",
    "Mouse2", "Mouse3", "Mouse4", "Mouse5", "Mouse6", "JoystickButton0", "JoystickButton1",
    "JoystickButton2", "JoystickButton3", "JoystickButton4", "JoystickButton5",
    "JoystickButton6", "JoystickButton7", "JoystickButton8", "JoystickButton9",
    "JoystickButton10", "JoystickButton11", "JoystickButton12", "JoystickButton13",
    "JoystickButton14", "JoystickButton15", "JoystickButton16", "JoystickButton17",
    "JoystickButton18", "JoystickButton19", "Joystick1Button0", "Joystick1Button1",
    "Joystick1Button2", "Joystick1Button3", "Joystick1Button4", "Joystick1Button5",
    "Joystick1Button6", "Joystick1Button7", "Joystick1Button8", "Joystick1Button9",
    "Joystick1Button10", "Joystick1Button11", "Joystick1Button12", "Joystick1Button13",
    "Joystick1Button14", "Joystick1Button15", "Joystick1Button16", "Joystick1Button17",
    "Joystick1Button18", "Joystick1Button19", "Joystick2Button0", "Joystick2Button1",
    "Joystick2Button2", "Joystick2Button3", "Joystick2Button4", "Joystick2Button5",
    "Joystick2Button6", "Joystick2Button7", "Joystick2Button8", "Joystick2Button9",
    "Joystick2Button10", "Joystick2Button11", "Joystick2Button12", "Joystick2Button13",
    "Joystick2Button14", "Joystick2Button15", "Joystick2Button16", "Joystick2Button17",
    "Joystick2Button18", "Joystick2Button19", "Joystick3Button0", "Joystick3Button1",
    "Joystick3Button2", "Joystick3Button3", "Joystick3Button4", "Joystick3Button5",
    "Joystick3Button6", "Joystick3Button7", "Joystick3Button8", "Joystick3Button9",
    "Joystick3Button10", "Joystick3Button11", "Joystick3Button12", "Joystick3Button13",
    "Joystick3Button14", "Joystick3Button15", "Joystick3Button16", "Joystick3Button17",
    "Joystick3Button18", "Joystick3Button19", "Joystick4Button0", "Joystick4Button1",
    "Joystick4Button2", "Joystick4Button3", "Joystick4Button4", "Joystick4Button5",
    "Joystick4Button6", "Joystick4Button7", "Joystick4Button8", "Joystick4Button9",
    "Joystick4Button10", "Joystick4Button11", "Joystick4Button12", "Joystick4Button13",
    "Joystick4Button14", "Joystick4Button15", "Joystick4Button16", "Joystick4Button17",
    "Joystick4Button18", "Joystick4Button19", "Joystick5Button0", "Joystick5Button1",
    "Joystick5Button2", "Joystick5Button3", "Joystick5Button4", "Joystick5Button5",
    "Joystick5Button6", "Joystick5Button7", "Joystick5Button8", "Joystick5Button9",
    "Joystick5Button10", "Joystick5Button11", "Joystick5Button12", "Joystick5Button13",
    "Joystick5Button14", "Joystick5Button15", "Joystick5Button16", "Joystick5Button17",
    "Joystick5Button18", "Joystick5Button19", "Joystick6Button0", "Joystick6Button1",
    "Joystick6Button2", "Joystick6Button3", "Joystick6Button4", "Joystick6Button5",
    "Joystick6Button6", "Joystick6Button7", "Joystick6Button8", "Joystick6Button9",
    "Joystick6Button10", "Joystick6Button11", "Joystick6Button12", "Joystick6Button13",
    "Joystick6Button14", "Joystick6Button15", "Joystick6Button16", "Joystick6Button17",
    "Joystick6Button18", "Joystick6Button19", "Joystick7Button0", "Joystick7Button1",
    "Joystick7Button2", "Joystick7Button3", "Joystick7Button4", "Joystick7Button5",
    "Joystick7Button6", "Joystick7Button7", "Joystick7Button8", "Joystick7Button9",
    "Joystick7Button10", "Joystick7Button11", "Joystick7Button12", "Joystick7Button13",
    "Joystick7Button14", "Joystick7Button15", "Joystick7Button16", "Joystick7Button17",
    "Joystick7Button18", "Joystick7Button19", "Joystick8Button0", "Joystick8Button1",
    "Joystick8Button2", "Joystick8Button3", "Joystick8Button4", "Joystick8Button5",
    "Joystick8Button6", "Joystick8Button7", "Joystick8Button8", "Joystick8Button9",
    "Joystick8Button10", "Joystick8Button11", "Joystick8Button12", "Joystick8Button13",
    "Joystick8Button14", "Joystick8Button15", "Joystick8Button16", "Joystick8Button17",
    "Joystick8Button18", "Joystick8Button19", "F16", "F17", "F18", "F19", "F20", "F21", "F22",
    "F23", "F24",
)

INTEGER_TYPES = {"Int32", "UInt32", "Int64", "UInt64", "Int16", "UInt16", "Byte", "SByte"}
FLOAT_TYPES = {"Single", "Double", "Decimal"}
# A String this long (or with an escaped newline) gets the multi-line box.
LONG_TEXT_CHARS = 80
# An Acceptable values list this long is elided behind "Show more (N values)"
# (the KeyboardShortcut KeyCode list is ~330 names; an enum is a handful).
MANY_VALUES = 20


# ---- the file browser ----
@dataclass
class ConfigFile:
    rel: str  # POSIX-style path under BepInEx/config/, e.g. "EpicLoot/baseconfig/abilities.json"
    path: Path
    size: int
    mtime: float

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def extension(self) -> str:
        return os.path.splitext(self.rel)[1].lower()

    @property
    def is_text(self) -> bool:
        return self.extension in TEXT_EXTENSIONS


def config_dir(bepinex_dir: Path) -> Path:
    return Path(bepinex_dir) / CONFIG_FOLDER


def list_config_files(bepinex_dir: Path, *, all_files: bool = False) -> list[ConfigFile]:
    """Every file under BepInEx/config/, recursively, flat (no grouping by
    mod: a mod's config path is whatever its code chose, unrelated to its
    package name). Text/config extensions only unless all_files. Sorted by
    name; an unreadable entry is skipped. Missing folder = []."""
    root = config_dir(bepinex_dir)
    files: list[ConfigFile] = []
    if not root.is_dir():
        return files
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in filenames:
            path = Path(dirpath) / name
            try:
                st = path.stat()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            f = ConfigFile(rel, path, st.st_size, st.st_mtime)
            if all_files or f.is_text:
                files.append(f)
    return sort_files(files, "name")


def sort_files(files: list[ConfigFile], key: str) -> list[ConfigFile]:
    if key == "modified":
        return sorted(files, key=lambda f: (-f.mtime, f.rel.casefold()))
    if key == "type":
        return sorted(files, key=lambda f: (f.extension, f.rel.casefold()))
    return sorted(files, key=lambda f: f.rel.casefold())


def file_matches(f: ConfigFile, query: str) -> bool:
    q = query.strip().casefold()
    return not q or q in f.rel.casefold()


# ---- reading / writing text ----
def read_text(path: Path) -> str | None:
    """The file as text, a UTF-8 BOM kept as the leading U+FEFF so a save
    writes it back. None when the bytes aren't UTF-8 (a .dat save, say)."""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def write_text(path: Path, text: str) -> None:
    write_text_atomic(Path(path), text)


def is_cfg(rel_or_path) -> bool:
    return str(rel_or_path).lower().endswith(".cfg")


# ---- the .cfg document ----
@dataclass
class Entry:
    section: str
    key: str
    value: str  # serialized, trimmed - what BepInEx's Reload would read
    line: int  # index into ConfigDocument.lines of its `Key = Value` line
    description: str = ""  # the `## ` lines, joined with "\n" (trailing blank lines dropped)
    setting_type: str | None = None
    default: str | None = None
    acceptable: list[str] | None = None  # `# Acceptable values:`
    value_range: tuple[str, str] | None = None  # `# Acceptable value range: From a to b`
    flags: bool = False  # a [Flags] enum: comma-separated multi-select
    notes: list[str] = field(default_factory=list)  # other `# ` lines in the block, as written

    @property
    def has_metadata(self) -> bool:
        return self.setting_type is not None


@dataclass
class ConfigDocument:
    lines: list[str]  # raw, each with its own terminator ("\r\n", "\n" or none on the last)
    entries: list[Entry]
    plugin_name: str | None = None
    plugin_version: str | None = None
    plugin_guid: str | None = None

    @property
    def sections(self) -> list[str]:
        seen: list[str] = []
        for e in self.entries:
            if e.section not in seen:
                seen.append(e.section)
        return seen

    @property
    def has_metadata(self) -> bool:
        return any(e.has_metadata for e in self.entries)

    def set_value(self, entry: Entry, value: str) -> bool:
        """Puts `value` (trimmed; a raw newline becomes BepInEx's escaped
        `\\n`) on the entry's line. False when nothing changed."""
        value = value.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\r").strip()
        if value == entry.value:
            return False
        entry.value = value
        self.lines[entry.line] = f"{entry.key} = {value}{_terminator(self.lines[entry.line])}"
        return True

    def render(self) -> str:
        return "".join(self.lines)


def _terminator(line: str) -> str:
    return "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""


def _split_lines(text: str) -> list[str]:
    # After every "\n", keeping it. (str.splitlines would also split on
    # \x0b, \x0c, \x1c-\x1e, \x85, \u2028, \u2029 - none of which end a
    # line for BepInEx's File.ReadAllLines.)
    if not text:
        return []
    return re.split(r"(?<=\n)", text)


def parse(text: str) -> ConfigDocument:
    lines = _split_lines(text)
    doc = ConfigDocument(lines, [])
    section = ""
    seen_section = False
    block: list[str] = []  # the comment lines (trimmed) directly above the current line

    for i, raw in enumerate(lines):
        line = raw.rstrip("\r\n").strip()
        if line.startswith("#"):
            block.append(line)
            continue
        if line.startswith("[") and line.endswith("]"):
            if not seen_section:
                _read_header(doc, block)
            seen_section = True
            section = line[1:-1]
            block = []
            continue
        key, sep, value = line.partition("=")
        if not sep:  # blank or invalid: ends any comment block
            if not seen_section and block and doc.plugin_guid is None:
                _read_header(doc, block)
            block = []
            continue
        entry = Entry(section, key.strip(), value.strip(), i)
        _read_block(entry, block)
        doc.entries.append(entry)
        block = []
    return doc


def _read_header(doc: ConfigDocument, block: list[str]) -> None:
    for line in block:
        m = _PLUGIN_HEADER.match(line)
        if m:
            doc.plugin_name, doc.plugin_version = m.group(1), m.group(2)
        elif line.startswith(_GUID_HEADER):
            doc.plugin_guid = line[len(_GUID_HEADER):].strip()


def _read_block(entry: Entry, block: list[str]) -> None:
    desc: list[str] = []
    for line in block:
        if line.startswith("##"):
            desc.append(line[3:] if line.startswith("## ") else line[2:])
        elif line.startswith(_SETTING_TYPE):
            entry.setting_type = line[len(_SETTING_TYPE):].strip()
        elif line.startswith(_DEFAULT):
            entry.default = line[len(_DEFAULT):].strip()
        elif line.startswith(_ACCEPTABLE):
            rest = line[len(_ACCEPTABLE):].strip()
            entry.acceptable = [v.strip() for v in rest.split(", ")] if rest else []
        elif line.startswith(_FLAGS):
            entry.flags = True
        elif _RANGE.match(line):
            m = _RANGE.match(line)
            entry.value_range = (m.group(1).strip(), m.group(2).strip())
        else:
            entry.notes.append(line[1:].strip())
    while desc and not desc[-1].strip():
        desc.pop()
    entry.description = "\n".join(desc)


# ---- which control renders an entry (the signed-off mockup's set) ----
def control_kind(entry: Entry) -> str:
    """One of: enum (a drop-down of the Acceptable values), flags (multi-
    select of them), shortcut (KeyboardShortcut: editable drop-down of the
    KeyCode list), bool, int, float, color, long-text, text. A bare entry
    (descriptions off) is text."""
    t = entry.setting_type
    if t == "KeyboardShortcut":
        return "shortcut"
    if entry.acceptable is not None:
        return "flags" if entry.flags else "enum"
    if t == "Boolean":
        return "bool"
    if t in INTEGER_TYPES:
        return "int"
    if t in FLOAT_TYPES:
        return "float"
    if t == "Color":
        return "color"
    if t == "String" and (len(entry.value) > LONG_TEXT_CHARS or len(entry.default or "") > LONG_TEXT_CHARS
                          or "\\n" in entry.value):
        return "long-text"
    return "text"


def split_flags(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def join_flags(names: list[str], acceptable: list[str]) -> str:
    """Checked names in the Acceptable-values order, as BepInEx writes a
    [Flags] enum; nothing checked = `None` when the enum has it."""
    chosen = [a for a in acceptable if a in names]
    if not chosen and "None" in acceptable:
        return "None"
    return ", ".join(chosen)


def color_to_rgb(value: str) -> tuple[int, int, int, int] | None:
    """RRGGBB[AA] hex (no `#`) -> (r, g, b, a); None when it isn't one."""
    v = value.strip().lstrip("#")
    if len(v) not in (6, 8) or not re.fullmatch(r"[0-9A-Fa-f]+", v):
        return None
    r, g, b = (int(v[i:i + 2], 16) for i in (0, 2, 4))
    a = int(v[6:8], 16) if len(v) == 8 else 255
    return r, g, b, a


def rgb_to_color(r: int, g: int, b: int, a: int = 255) -> str:
    return f"{r:02X}{g:02X}{b:02X}{a:02X}"  # ColorUtility.ToHtmlStringRGBA: upper-case


# ---- section jump + in-file search (the Edit Config toolbar, §7's QoL pass) ----
# A file with 2..CHIP_MAX sections gets one chip per section; more gets the
# "Sections (N)" popup list; fewer gets no jump control at all.
CHIP_MAX = 5
_SECTION_NUMBER = re.compile(r"^\d+\s*-\s*")
# What the search's matched substring is painted with, inside the key /
# description labels (the mockup's span: --warn at 45% under white text).
HIGHLIGHT_CSS = "background-color: rgba(224, 179, 65, 0.45); color: #ffffff;"


def jump_mode(section_count: int) -> str:
    """'none' (fewer than 2 sections), 'chips' (2..CHIP_MAX) or 'list'."""
    if section_count < 2:
        return "none"
    return "chips" if section_count <= CHIP_MAX else "list"


def section_label(header: str) -> str:
    """A chip's label: the header with a leading `N - ` number prefix
    dropped ("1 - General" -> "General"). The tooltip keeps the header."""
    return _SECTION_NUMBER.sub("", header, count=1) or header


def filter_sections(headers: list[str], text: str) -> list[str]:
    """The popup list's filter: case-insensitive substring of the header."""
    q = text.strip().casefold()
    return [h for h in headers if not q or q in h.casefold()]


def search_pattern(query: str) -> re.Pattern | None:
    """The in-file search as a pattern: a case-insensitive literal
    substring; None for a blank query (no search)."""
    q = query.strip()
    return re.compile(re.escape(q), re.IGNORECASE) if q else None


def entry_matches(entry: Entry, pattern: re.Pattern) -> bool:
    """Scope = the setting's name and description only - not its value,
    not its section."""
    return pattern.search(entry.key) is not None or pattern.search(entry.description) is not None


def highlight_html(text: str, pattern: re.Pattern, css: str = HIGHLIGHT_CSS) -> str:
    """`text` as rich text for a QLabel with every match wrapped in a
    styled span: HTML-escaped, a newline as <br>, runs of spaces kept
    (pre-wrap - rich text would otherwise collapse them)."""
    out: list[str] = ['<span style="white-space: pre-wrap;">']
    pos = 0
    for m in pattern.finditer(text):
        if m.end() == m.start():
            continue
        out.append(_html(text[pos:m.start()]))
        out.append(f'<span style="{css}">{_html(m.group(0))}</span>')
        pos = m.end()
    out.append(_html(text[pos:]))
    out.append("</span>")
    return "".join(out)


def _html(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>"))
