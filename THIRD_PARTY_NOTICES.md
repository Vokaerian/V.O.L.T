# Third-party notices

VOLT's own code is MIT-licensed (`LICENSE`). A VOLT release folder also
contains the third-party components below, each under its own terms. The full
LGPLv3 and GPLv3 texts ship in `licenses/` next to this file.

## Valve Steamworks SDK redistributable (`steamworks/steam_api64.dll`)

Copyright (c) Valve Corporation. All rights reserved. Steam and the Steam logo
are trademarks and/or registered trademarks of Valve Corporation.

`steam_api64.dll` is the Steamworks SDK's redistributable client library
(`sdk/redistributable_bin/win64` of Steamworks SDK 1.64). It is not open
source. It is redistributed with VOLT under the Steamworks SDK Access
Agreement, section 1.1(b), which licenses the files in the SDK's
`redistributable_bin` folder for distribution along with software that uses
the Steamworks services, in object code form, under the terms of that
agreement (https://partner.steamgames.com/documentation/sdk_access_agreement).
No other part of the Steamworks SDK is included. VOLT is not affiliated with
or endorsed by Valve.

VOLT uses this library only to talk to the Steam client already running and
signed in on your machine (subscribe / unsubscribe / download status for
RimWorld Workshop items). It is loaded by a short-lived helper process, never
by the VOLT window itself.

## SteamworksPy (`steamworks/SteamworksPy64.dll` and the `steamworks` Python package)

https://github.com/philippj/SteamworksPy - MIT License.
Copyright (c) 2016 GP Garcia, CoaguCo Industries.

The repository's `LICENSE` file (MIT, text below) covers the whole repository,
including the C++ source of the native wrapper (`library/SteamworksPy.cpp`),
which carries no separate licence header. VOLT's `SteamworksPy64.dll` is built
from that source at commit `c021d1c` (upstream master as of 2026-05-25, via the
fork `Vokaerian/SteamworksPyV`, which changes no licence terms) against the
Steamworks SDK 1.64 headers and import library. Because it is compiled against
the SDK, the binary also derives from Valve's SDK headers; Valve's agreement
names only `redistributable_bin` explicitly (section 1.1(b)), so the wrapper
DLL's standing under that agreement should be taken as "built from the SDK
under the agreement's general licence" - verify against the current agreement
if you redistribute it separately from VOLT. The Python package is compiled
into `VOLT.exe` unmodified apart from a runtime patch of its library loader
(tolerating missing exports), applied in VOLT's own code.

```
Copyright (c) 2016 GP Garcia, CoaguCo Industries

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Qt for Python (PySide6, shiboken6) and the Qt 6 libraries (`PySide6/`, `shiboken6/`)

PySide6 and shiboken6 6.11.2 (The Qt Company Ltd. and the Qt Project
contributors) and the Qt 6 libraries they bind are used under the
**GNU Lesser General Public License v3.0** (`licenses/LGPL-3.0.txt`, which
incorporates `licenses/GPL-3.0.txt`). Qt is also available under GPLv2/GPLv3
and commercial licences; VOLT uses the LGPLv3 option. VOLT uses these
libraries unmodified and does not link them statically: the Qt DLLs, plugins
and the PySide6/shiboken6 extension modules are separate files under
`PySide6/` and `shiboken6/` in the release folder, so you can replace or
relink them with your own build of the same libraries (LGPLv3 section 4).
Source code: https://code.qt.io/cgit/pyside/pyside-setup.git and
https://code.qt.io/cgit/qt/qt5.git (Qt 6 branches); binary wheels:
https://pypi.org/project/PySide6/. The Qt libraries themselves bundle further
third-party components (e.g. FreeType, HarfBuzz, libpng, PCRE2, zlib); their
notices are listed in Qt's documentation, "Licenses Used in Qt"
(https://doc.qt.io/qt-6/licenses-used-in-qt.html).

## Python (`python314.dll`, the standard library)

CPython 3.14, Copyright (c) 2001 Python Software Foundation and others, under
the PSF License Agreement (https://docs.python.org/3/license.html). The
licence text itself is not copied into this folder - verify whether a copy
should be added if you redistribute the folder further.

## Other Python packages compiled into `VOLT.exe`

- certifi 2026.7.22 (Mozilla's CA certificate bundle) - Mozilla Public
  License 2.0 (https://www.mozilla.org/MPL/2.0/).
- PyYAML 6.0.3 - MIT License, Copyright (c) 2017-2021 Ingy döt Net,
  Copyright (c) 2006-2016 Kirill Simonov.

## Nuitka runtime

`VOLT.exe` was produced by Nuitka 4.2.2 (Copyright (c) 2008-2026 Kay Hayen)
and links Nuitka's runtime library, licensed under the GNU Affero General
Public License v3 **with the Nuitka Runtime Library Exception, Version 1.0**,
which permits conveying the compiled output under terms of the author's
choice. The Nuitka compiler itself is not part of VOLT.

## Microsoft Visual C++ runtime

If `vcruntime140.dll` / `msvcp140.dll` / `vcruntime140_1.dll` are present in
the release folder, they are Microsoft Visual C++ Redistributable files,
distributed under Microsoft's redistribution terms for Visual Studio
(https://learn.microsoft.com/visualstudio/releases/2022/redistribution).
Verify which of them a given build actually contains.

## Not covered by VOLT's licence

The VOLT logo, lettering and other artwork (`docs/brand/` in the repository,
`volt_py/assets/icon` and `volt_py/assets/brand` in a release) are all rights
reserved. Game names and cover art shown in the app belong to their respective
owners. RimWorld is a trademark of Ludeon Studios.
