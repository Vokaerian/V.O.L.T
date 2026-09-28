"""Windows registry reads (port of Electron's src/electron/lib/registry.js).

Electron shells out to reg.exe because Node has no registry API; Python's
stdlib winreg reads it natively. Every function returns None / [] off Windows
or on any failure - never raises.
"""

try:
    import winreg
except ImportError:  # not Windows
    winreg = None

_HIVES = {"HKCU": "HKEY_CURRENT_USER", "HKLM": "HKEY_LOCAL_MACHINE"}

def _split(key: str):
    """'HKCU\\Software\\X' -> (hive handle, 'Software\\X', 'HKEY_CURRENT_USER')."""
    prefix, _, sub = key.partition("\\")
    long = _HIVES.get(prefix.upper(), prefix.upper())
    return getattr(winreg, long), sub, long

def read_reg_value(key: str, name: str) -> str | None:
    if winreg is None:
        return None
    try:
        hive, sub, _ = _split(key)
        with winreg.OpenKey(hive, sub) as k:
            value, _ = winreg.QueryValueEx(k, name)
    except (OSError, AttributeError):
        return None
    # JS treats an empty string as "not found" too.
    return str(value) if value not in (None, "") else None

def read_reg_tree(key: str) -> list[dict]:
    """[{"key": full path, "values": {lowercased name: str value}}] for `key`
    and every subkey, recursively (mirrors `reg query <key> /s`)."""
    if winreg is None:
        return []
    try:
        hive, sub, long = _split(key)
    except AttributeError:
        return []
    out: list[dict] = []

    def walk(path: str) -> None:
        try:
            with winreg.OpenKey(hive, path) as k:
                n_sub, n_val, _ = winreg.QueryInfoKey(k)
                values = {}
                for j in range(n_val):
                    name, data, _ = winreg.EnumValue(k, j)
                    values[name.lower()] = "" if data is None else str(data)
                out.append({"key": f"{long}\\{path}", "values": values})
                children = [winreg.EnumKey(k, j) for j in range(n_sub)]
        except OSError:
            return
        for c in children:
            walk(f"{path}\\{c}")

    walk(sub)
    return out
