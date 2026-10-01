# Third-party notices

VOLT's own code is MIT-licensed (`LICENSE`). A VOLT release folder also
contains the third-party components below, each under its own terms; VOLT's
MIT licence does not cover them. Full licence texts ship in `licenses/` next
to this file: `LGPL-3.0.txt`, `GPL-3.0.txt` and `Python-3.14.txt`.

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
It is the only Steamworks file VOLT ships: no other part of the SDK, and no
wrapper or binding library, is included. VOLT's own code (MIT) calls the
library's exported C API directly. VOLT is not affiliated with or endorsed by
Valve.

How VOLT uses it: only to talk to the Steam client already running and signed
in on your machine, and only from a short-lived helper process (`VOLT.exe
--steam-worker`), never from the VOLT window itself. The helper subscribes to,
unsubscribes from, and reads the download state of RimWorld Workshop items on
RimWorld's behalf (its App ID, 294100), so that an item you pick in VOLT is
downloaded and kept up to date by Steam itself, exactly as if you had
subscribed on the Workshop website. While a helper is connected, Steam shows
RimWorld as running for a moment; that is inherent to the SDK.

A plain statement of where this stands: VOLT is a mod manager, not a game.
Valve's Workshop documentation describes `ISteamUGC::SubscribeItem` and
`UnsubscribeItem` as supporting "in-game item subscription management", and we
have found no Valve statement that either permits or prohibits a third-party
tool from making those calls on a game's behalf. VOLT's author treats this as
an unresolved gray area, accepts it knowingly, and ships the feature on that
basis, as other community mod managers for RimWorld do (RimSort, among others,
bundles the same redistributable for the same purpose). If Valve clarifies its
position, this notice and the feature will follow. This is a good-faith
description, not legal advice.

## Qt for Python (PySide6, shiboken6) and the Qt 6 libraries

PySide6 and shiboken6 6.11.2 (The Qt Company Ltd. and the Qt Project
contributors) and the Qt 6.11.2 libraries they bind are used under the
**GNU Lesser General Public License v3.0** (`licenses/LGPL-3.0.txt`, which
incorporates `licenses/GPL-3.0.txt`). Qt is also available under GPLv2/GPLv3
and commercial licences; VOLT uses the LGPLv3 option. VOLT uses these
libraries unmodified.

Where they are in the release folder: the Qt libraries (`qt6core.dll`,
`qt6gui.dll`, `qt6widgets.dll`, `qt6network.dll`, `qt6svg.dll`, `qt6pdf.dll`)
and the binding libraries (`pyside6.abi3.dll`, `shiboken6.abi3.dll`) are
separate files in the folder root, the Qt plugins are in
`PySide6/qt-plugins/`, and the binding extension modules are `PySide6/*.pyd`
and `shiboken6/Shiboken.pyd`. All of these are loaded at run time, so you can
replace them with your own interface-compatible build of the same libraries
(LGPLv3 section 4(d)(1)). The small Python-level parts of PySide6 and
shiboken6 are compiled into `VOLT.exe` by Nuitka; to use modified versions of
those, rebuild `VOLT.exe` from VOLT's MIT-licensed source and build script
(https://github.com/Vokaerian/V.O.L.T, `tools/release.py`) against your
modified PySide6 (LGPLv3 section 4(d)(0)).

Source code (6.11.2 tags): https://code.qt.io/cgit/pyside/pyside-setup.git
and https://code.qt.io/cgit/qt/qt5.git; binary wheels:
https://pypi.org/project/PySide6/. The Qt libraries themselves bundle further
third-party components (e.g. FreeType, HarfBuzz, libpng, libjpeg-turbo, PCRE2,
zlib, and the Public Suffix List under the Mozilla Public License 2.0); their
notices are listed in Qt's documentation, "Third-Party Code Used in Qt"
(https://doc.qt.io/qt-6/licenses-used-in-qt.html; pick the 6.11 version of the
page).

## Python (`python314.dll`, `python3.dll`, the `*.pyd` modules in the folder root, the standard library)

CPython 3.14.7, Copyright (c) 2001 Python Software Foundation; All Rights
Reserved, and others, under the PSF License Agreement. The licence text and
the history of the software ship in `licenses/Python-3.14.txt`, which is the
`LICENSE.txt` of the Python 3.14.7 Windows build VOLT is built with. The
standard library is compiled into `VOLT.exe` by Nuitka without changes to its
source.

The same file also carries the licence texts of the libraries that build of
Python bundles and that ship here: OpenSSL 3.5.7 (`libcrypto-3.dll`,
`libssl-3.dll`; Apache License 2.0; also used by Qt's TLS plugin), libffi
(`libffi-8.dll`), bzip2 1.0.8 (inside `_bz2.pyd`) and Zstandard 1.5.7 (inside
`_zstd.pyd`). For the other components bundled with CPython, see
https://docs.python.org/3/license.html.

## Other Python packages

- certifi 2026.7.22: its Python module is compiled into `VOLT.exe`, and its CA
  certificate bundle (derived from Mozilla's root certificate list) ships
  unmodified as `certifi/cacert.pem`. Mozilla Public License 2.0
  (https://www.mozilla.org/MPL/2.0/). Source:
  https://github.com/certifi/python-certifi and
  https://pypi.org/project/certifi/.
- PyYAML 6.0.3: its Python modules are compiled into `VOLT.exe`; its C
  extension `yaml/_yaml.pyd` includes libyaml 0.2.5 (also MIT, same authors,
  https://github.com/yaml/libyaml). PyYAML's licence:

```
Copyright (c) 2017-2021 Ingy döt Net
Copyright (c) 2006-2016 Kirill Simonov

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Nuitka runtime

`VOLT.exe` was produced by Nuitka 4.2.2 (Copyright (c) 2008-2026 Kay Hayen)
and links Nuitka's runtime library, licensed under the GNU Affero General
Public License v3 **with the Nuitka Runtime Library Exception, Version 1.0**,
which permits conveying the compiled output under terms of the author's
choice. The Nuitka compiler itself is not part of VOLT.

## Microsoft Visual C++ runtime

These files are Microsoft Visual C++ Redistributable files, (c) Microsoft
Corporation, distributed unmodified under the Distributable Code terms of
Microsoft's Visual Studio licence
(https://learn.microsoft.com/visualstudio/releases/2026/redistribution).
VOLT's MIT licence does not cover them; Microsoft's terms apply, and they may
not be modified.

- Folder root, version 14.51.36247: `vcruntime140.dll`, `vcruntime140_1.dll`,
  `msvcp140.dll`, `msvcp140_1.dll`, `msvcp140_2.dll`.
- `shiboken6/`, version 14.44.35211 (as shipped in the shiboken6 package):
  `msvcp140.dll`, `msvcp140_1.dll`, `msvcp140_2.dll`,
  `msvcp140_codecvt_ids.dll`.

## Not covered by VOLT's licence

The VOLT logo, lettering and other artwork (`docs/brand/` in the repository,
`volt_py/assets/icon` and `volt_py/assets/brand` in a release) are all rights
reserved. Game names and cover art shown in the app belong to their respective
owners. RimWorld is a trademark of Ludeon Studios.
