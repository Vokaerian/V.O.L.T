"""Shared HTTPS entry point: urllib's urlopen, verified against certifi's CA
bundle instead of the OS trust store.

Why: on Windows, Python's default context loads the Windows root store, which
can hold the expired "DST Root CA X3" but not yet ISRG Root X1 (Windows only
fetches missing roots on demand for its own APIs, never for OpenSSL). Servers
that still send Let's Encrypt's legacy cross-signed chain (thunderstore.io,
seen 2026-09-28) then fail with CERTIFICATE_VERIFY_FAILED "certificate has
expired" even though browsers reach them fine. certifi ships Mozilla's current
root set (no DST Root CA X3), so OpenSSL builds the valid chain. Verification
stays fully on - never swap this for an unverified context.

Every module that hits the network routes through urlopen() here (the
per-module `env.urlopen` check-harness seams point at it).
"""

import ssl
import urllib.request

import certifi

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def urlopen(url, *args, **kwargs):
    """urllib.request.urlopen with SSL_CONTEXT as the default context."""
    kwargs.setdefault("context", SSL_CONTEXT)
    return urllib.request.urlopen(url, *args, **kwargs)
