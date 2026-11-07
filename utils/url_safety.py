"""Public-network URL validation and redirect-safe HTTP helpers.

These checks reduce SSRF exposure for user-selected publication sources. They
must be paired with network egress controls in production: DNS is resolved
again by the HTTP/browser networking stack after validation, so an environment
that permits access to private infrastructure should enforce egress rules too.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import requests


logger = logging.getLogger("newstrace.network")

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_LOCAL_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".test",
    ".invalid",
    ".example",
)


def _public_ip(value: str) -> bool:
    """Return True only for globally routable IPv4 or IPv6 addresses."""
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return bool(address.is_global)


def validate_public_http_url(value: str, *, resolve_dns: bool = True) -> str:
    """Validate an HTTP(S) URL and optionally verify every resolved address.

    Any private, loopback, link-local, multicast, reserved, unspecified or
    otherwise non-global DNS answer rejects the entire hostname. Rejecting a
    mixed public/private answer avoids choosing a safe answer while another
    answer could route the request into a private network.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Use a valid public http:// or https:// publication URL.")

    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The publication URL contains an invalid host or port.") from exc

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if scheme not in {"http", "https"} or not hostname:
        raise ValueError("Use a valid public http:// or https:// publication URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Publication URLs must not contain embedded usernames or passwords.")
    if port not in (None, 80, 443):
        raise ValueError("Publication URLs may use only the standard HTTP or HTTPS ports.")
    if (
        hostname == "localhost"
        or hostname.endswith(_LOCAL_HOST_SUFFIXES)
    ):
        raise ValueError("Local and internal network addresses cannot be used as publication sources.")

    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None

    if literal_address is not None:
        if not literal_address.is_global:
            raise ValueError("Private, loopback, reserved and link-local IP addresses are not public sources.")
        return value

    if not resolve_dns:
        return value

    service = port or (443 if scheme == "https" else 80)
    try:
        answers = socket.getaddrinfo(hostname, service, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"The publication hostname could not be resolved: {hostname}.") from exc

    addresses = {
        str(answer[4][0]).split("%", 1)[0]
        for answer in answers
        if answer and len(answer) >= 5 and answer[4]
    }
    if not addresses:
        raise ValueError(f"The publication hostname returned no usable network addresses: {hostname}.")
    unsafe = sorted(address for address in addresses if not _public_ip(address))
    if unsafe:
        raise ValueError(
            "The publication hostname resolves to a private, reserved or non-public network address."
        )
    return value


def safe_get(
    url: str,
    *,
    session: requests.Session | None = None,
    max_redirects: int = 5,
    **request_kwargs,
) -> requests.Response:
    """GET a URL while validating each redirect before issuing its request.

    Requests' automatic redirects are disabled. Each Location header is
    resolved relative to the preceding URL and validated before another
    network call can be made.
    """
    client = session or requests.Session()
    owns_session = session is None
    current_url = url
    kwargs = dict(request_kwargs)
    kwargs.pop("allow_redirects", None)
    redirects_followed = 0
    response = None

    try:
        validate_public_http_url(current_url)
        while True:
            response = client.get(
                current_url,
                allow_redirects=False,
                **kwargs,
            )
            # Request parameters belong to the original URL. A redirect
            # Location is already authoritative for its own query string.
            kwargs.pop("params", None)

            location = response.headers.get("Location") if response.status_code in _REDIRECT_STATUSES else None
            if not location:
                return response

            if redirects_followed >= max(0, int(max_redirects)):
                response.close()
                response = None
                raise RuntimeError(
                    f"The publication source exceeded the maximum of {max_redirects} HTTP redirects."
                )

            next_url = urljoin(current_url, location)
            try:
                validate_public_http_url(next_url)
            except Exception:
                response.close()
                response = None
                raise

            response.close()
            response = None
            current_url = next_url
            redirects_followed += 1
    finally:
        if owns_session:
            client.close()


async def install_public_network_guard(context) -> None:
    """Abort unsafe HTTP(S) browser requests, including redirects/subresources.

    This route is installed at the BrowserContext level so pages created from
    that context inherit the policy. Local data/blob/about resources are
    allowed; other non-HTTP schemes are denied.
    """
    async def guard(route) -> None:
        target = route.request.url
        scheme = urlparse(target).scheme.lower()
        if scheme in {"data", "blob", "about"}:
            await route.continue_()
            return
        if scheme not in {"http", "https"}:
            await route.abort()
            return
        try:
            await asyncio.to_thread(validate_public_http_url, target)
        except Exception as exc:
            logger.warning(
                "Blocked browser request to a non-public destination (%s): %s",
                type(exc).__name__,
                target[:180],
            )
            await route.abort()
            return
        await route.continue_()

    await context.route("**/*", guard)
