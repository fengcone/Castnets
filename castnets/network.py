"""Bounded public-source fetching. CLI only; no URL-taking HTTP endpoint."""
import os
import ssl
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .models import DomainError


def fetch(url: str, limit: int = 8 * 1024 * 1024) -> bytes:
    if urlsplit(url).scheme != "https":
        raise DomainError("Only HTTPS content sources are accepted")
    request = Request(quote(url, safe=":/?=&%+@"), headers={"User-Agent": "Castnets-M0/0.1"})
    context = ssl.create_default_context()
    # Homebrew's bundle may omit roots present in macOS's system bundle.
    # Respect an explicitly configured SSL_CERT_FILE; never disable verification.
    if sys.platform == "darwin" and not os.environ.get("SSL_CERT_FILE") and Path("/etc/ssl/cert.pem").exists():
        context.load_verify_locations("/etc/ssl/cert.pem")
    with urlopen(request, timeout=30, context=context) as response:
        if urlsplit(response.url).scheme != "https":
            raise DomainError("Refusing non-HTTPS redirect")
        result = response.read(limit + 1)
    if len(result) > limit:
        raise DomainError(f"Source exceeds {limit} byte limit")
    return result
