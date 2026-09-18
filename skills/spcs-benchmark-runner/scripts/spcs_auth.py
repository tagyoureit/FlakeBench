"""Mint a Snowflake OAuth token scoped to an SPCS ingress endpoint.

Uses key-pair JWT authentication and the Snowflake token-exchange endpoint, per
the Snowflake documentation "Access the public endpoint programmatically"
(Snowpark Container Services tutorial 8, option 2).

The resulting token is passed to the service as::

    Authorization: Snowflake Token="<token>"

Credentials are resolved from a named entry in ``~/.snowflake/connections.toml``
or from environment variables. Nothing is hard-coded.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)

CONNECTIONS_TOML = Path.home() / ".snowflake" / "connections.toml"
JWT_LIFETIME = timedelta(minutes=59)
DEFAULT_TIMEOUT_SECONDS = 60


class AuthConfigError(ValueError):
    """Raised when credentials cannot be resolved into a usable configuration."""


def load_connection(name: str, path: Path = CONNECTIONS_TOML) -> dict[str, Any]:
    """Read a named connection from a Snowflake ``connections.toml`` file.

    Args:
        name: Connection name, e.g. ``default``.
        path: Location of the connections file.

    Returns:
        The connection's key/value parameters.

    Raises:
        FileNotFoundError: If the connections file does not exist.
        AuthConfigError: If the named connection is absent.
    """
    if not path.exists():
        raise FileNotFoundError(f"Connections file not found: {path}")

    with path.open("rb") as handle:
        data = tomllib.load(handle)

    if name not in data:
        available = ", ".join(sorted(data)) or "(none)"
        raise AuthConfigError(f"Connection {name!r} not found. Available: {available}")

    return dict(data[name])


def account_for_jwt(raw_account: str) -> str:
    """Normalise an account identifier for use in the JWT ``iss``/``sub`` claims.

    Region and cloud suffixes are stripped. Underscores are preserved, unlike in
    the URL form.

    Args:
        raw_account: Account identifier, possibly including a region suffix.

    Returns:
        Upper-cased account identifier suitable for JWT claims.
    """
    account = raw_account
    if ".global" not in account:
        idx = account.find(".")
        if idx > 0:
            account = account[:idx]
    else:
        idx = account.find("-")
        if idx > 0:
            account = account[:idx]
    return account.upper()


def account_for_url(raw_account: str) -> str:
    """Normalise an account identifier for use as a hostname.

    Underscores are not valid in hostnames, so they become hyphens. An account
    such as ``myorg-myacct_aws1`` resolves to ``myorg-myacct-aws1``.

    Args:
        raw_account: Account identifier.

    Returns:
        Hostname-safe account identifier.
    """
    return raw_account.replace("_", "-")


def make_jwt(account: str, user: str, key_file: Path) -> str:
    """Build a signed JWT asserting the caller's identity.

    Args:
        account: Snowflake account identifier.
        user: Snowflake user name.
        key_file: Path to an unencrypted PKCS#8 private key.

    Returns:
        The encoded JWT.

    Raises:
        FileNotFoundError: If the private key file does not exist.
    """
    if not key_file.exists():
        raise FileNotFoundError(f"Private key not found: {key_file}")

    private_key = load_pem_private_key(key_file.read_bytes(), None, default_backend())
    public_der = private_key.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    )
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(public_der).digest()
    ).decode("utf-8")

    qualified = f"{account_for_jwt(account)}.{user.upper()}"
    now = datetime.now(UTC)
    payload = {
        "iss": f"{qualified}.{fingerprint}",
        "sub": qualified,
        "iat": now,
        "exp": now + JWT_LIFETIME,
    }
    return jwt.encode(payload, key=private_key, algorithm="RS256")


def exchange_for_oauth_token(
    assertion: str,
    account: str,
    endpoint: str,
    role: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Exchange a key-pair JWT for an OAuth token scoped to an SPCS endpoint.

    Args:
        assertion: The signed JWT from :func:`make_jwt`.
        account: Snowflake account identifier.
        endpoint: SPCS ingress hostname, without scheme.
        role: Role to scope the session to. Omit to use the user's default.
        timeout: Request timeout in seconds.

    Returns:
        The OAuth token to place in the ``Authorization`` header.

    Raises:
        requests.HTTPError: If the token exchange is rejected.
    """
    scope = f"session:role:{role} {endpoint}" if role else endpoint
    response = requests.post(
        f"https://{account_for_url(account)}.snowflakecomputing.com/oauth/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "scope": scope,
            "assertion": assertion,
        },
        timeout=timeout,
    )
    if response.status_code != 200:
        raise requests.HTTPError(
            f"Token exchange failed ({response.status_code}): {response.text}"
        )
    return response.text.strip()


def get_token(
    endpoint: str,
    connection: str | None = None,
    account: str | None = None,
    user: str | None = None,
    key_file: str | None = None,
    role: str | None = None,
) -> str:
    """Resolve credentials and return an OAuth token for an SPCS endpoint.

    Resolution order for each field: explicit argument, then the named
    connection, then the matching ``SNOWFLAKE_*`` environment variable.

    Args:
        endpoint: SPCS ingress hostname, without scheme.
        connection: Name of a ``connections.toml`` entry to read defaults from.
        account: Overrides the account identifier.
        user: Overrides the user name.
        key_file: Overrides the private key path.
        role: Overrides the session role.

    Returns:
        The OAuth token to place in the ``Authorization`` header.

    Raises:
        AuthConfigError: If account, user, or private key cannot be resolved.
    """
    conn: dict[str, Any] = load_connection(connection) if connection else {}

    resolved_account = (
        account or conn.get("account") or os.environ.get("SNOWFLAKE_ACCOUNT")
    )
    resolved_user = user or conn.get("user") or os.environ.get("SNOWFLAKE_USER")
    resolved_key = (
        key_file
        or conn.get("private_key_file")
        or os.environ.get("SNOWFLAKE_PRIVATE_KEY_FILE")
    )
    resolved_role = role or conn.get("role") or os.environ.get("SNOWFLAKE_ROLE")

    missing = [
        field
        for field, value in (
            ("account", resolved_account),
            ("user", resolved_user),
            ("private_key_file", resolved_key),
        )
        if not value
    ]
    if missing:
        raise AuthConfigError(
            "Could not resolve: "
            + ", ".join(missing)
            + ". Pass --connection, explicit flags, or set SNOWFLAKE_* env vars."
        )

    assertion = make_jwt(resolved_account, resolved_user, Path(resolved_key))
    return exchange_for_oauth_token(
        assertion, resolved_account, endpoint, resolved_role
    )


def auth_header(token: str) -> dict[str, str]:
    """Build the SPCS ingress authorization header.

    Args:
        token: OAuth token from :func:`get_token`.

    Returns:
        Header mapping suitable for ``requests``.
    """
    return {"Authorization": f'Snowflake Token="{token}"'}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mint a Snowflake OAuth token for an SPCS ingress endpoint."
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        help="SPCS ingress hostname without scheme, e.g. abc-org-acct.snowflakecomputing.app",
    )
    parser.add_argument(
        "--connection",
        default="default",
        help="connections.toml entry to read credentials from (default: default)",
    )
    parser.add_argument("--account", help="Override the account identifier")
    parser.add_argument("--user", help="Override the user name")
    parser.add_argument("--key-file", help="Override the private key path")
    parser.add_argument("--role", help="Override the session role")
    return parser.parse_args()


def main() -> None:
    """Print an OAuth token for the requested endpoint."""
    args = _parse_args()
    print(
        get_token(
            endpoint=args.endpoint,
            connection=args.connection,
            account=args.account,
            user=args.user,
            key_file=args.key_file,
            role=args.role,
        )
    )


if __name__ == "__main__":
    main()
