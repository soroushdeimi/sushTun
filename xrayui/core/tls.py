"""The TLS context for sushTun's own outbound HTTPS (subscriptions, updates, geo).

A frozen Python's OpenSSL looks for its CA bundle where the build machine kept
it (Ubuntu), so on Fedora and friends every fetch failed with "unable to get
local issuer certificate". When the default has no bundle we load the first of
the usual distro locations. Verification is never relaxed.
"""
from __future__ import annotations

import functools
import ssl
import sys
from collections.abc import Iterable

# Fedora/RHEL first, then Debian, SUSE, Alpine/macOS, FreeBSD.
CA_BUNDLES = (
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/ca-bundle.pem",
    "/etc/ssl/cert.pem",
    "/usr/local/share/certs/ca-root-nss.crt",
)


def load_context(candidates: Iterable = CA_BUNDLES, verify_paths=None) -> tuple[ssl.SSLContext, bool]:
    """(context, whether any CA source is available). Pure: tests pass both inputs."""
    ctx = ssl.create_default_context()
    paths = verify_paths if verify_paths is not None else ssl.get_default_verify_paths()
    if paths.cafile or paths.capath:
        return ctx, True
    if sys.platform == "win32":
        return ctx, True  # the Windows store is read by create_default_context
    for candidate in candidates:
        try:
            ctx.load_verify_locations(cafile=str(candidate))
        except (ssl.SSLError, OSError):
            continue
        return ctx, True
    return ctx, False


@functools.cache
def _loaded() -> tuple[ssl.SSLContext, bool]:
    return load_context()


def https_context() -> ssl.SSLContext:
    return _loaded()[0]


https_context.cache_clear = _loaded.cache_clear  # type: ignore[attr-defined]


def ca_found() -> bool:
    return _loaded()[1]


def needs_ca_hint(error: object) -> bool:
    """A certificate failure while no CA bundle was found at all (not a bad server cert)."""
    return "CERTIFICATE_VERIFY_FAILED" in str(error) and not ca_found()
