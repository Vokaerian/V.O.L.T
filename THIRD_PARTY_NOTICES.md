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
