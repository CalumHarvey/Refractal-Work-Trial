"""Placeholder Jev API client.

Jev's ingestion API is not defined yet, so the endpoint, authentication and request shape are config
values (config/deliver.yaml `api`). With `dry_run` nothing is sent and the call returns a stub reply;
otherwise each batch is POSTed as JSON with the key from the configured environment variable.
"""
import json
import os
import urllib.error
import urllib.request


class JevError(RuntimeError):
    """Raised when the Jev API rejects a request or cannot be reached."""


class JevClient:
    """Sends ingestion requests to Jev.

    Attributes:
        endpoint: The ingestion URL.
        dry_run: When true, nothing is sent.
    """

    def __init__(self, api: dict, dry_run: bool | None = None):
        """Configure the client.

        Args:
            api: The `api` section of config/deliver.yaml.
            dry_run: Override for `api.dry_run`.
        """
        self.api = api
        self.endpoint = api["endpoint"]
        self.dry_run = api.get("dry_run", True) if dry_run is None else dry_run

    def _headers(self) -> dict:
        """Request headers, with authentication when a key is set.

        Returns:
            Headers for the POST.

        Raises:
            JevError: If sending for real and the key's environment variable is not set.
        """
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(self.api["api_key_env"])
        if not key:
            raise JevError(f"environment variable {self.api['api_key_env']} is not set")
        headers[self.api["auth_header"]] = f"{self.api['auth_scheme']} {key}".strip()
        return headers

    def send(self, body: dict) -> dict:
        """Send one ingestion request.

        Args:
            body: The request body (see deliver.package.request_body).

        Returns:
            The parsed reply, or `{"status": "dry_run", "traces": n}` when dry-running.

        Raises:
            JevError: On an HTTP error or an unreachable endpoint.
        """
        if self.dry_run:
            return {"status": "dry_run", "traces": len(body["traces"])}
        request = urllib.request.Request(self.endpoint, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self.api["timeout_seconds"]) as response:
                text = response.read().decode("utf-8")
                return json.loads(text) if text.strip() else {"status": response.status}
        except urllib.error.HTTPError as exc:
            raise JevError(f"Jev answered HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise JevError(f"could not reach {self.endpoint}: {exc}") from exc
