"""HTTP client for the conf-doc API (used by MCP server)."""

from __future__ import annotations

import json
import os
from typing import Any, cast

import httpx

DEFAULT_TIMEOUT = 60.0
ENV_API_URL = "CONF_DOC_API_URL"
ENV_CONFIGURATION = "CONF_DOC_CONFIGURATION"
ENV_API_TIMEOUT = "CONF_DOC_API_TIMEOUT"


class ConfDocApiError(Exception):
    """API request failed."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConfDocApiClient:
    """Thin wrapper over conf-doc REST endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        default_configuration: str | None = None,
        timeout: float | None = None,
    ) -> None:
        raw_url = base_url if base_url is not None else os.environ.get(ENV_API_URL, "")
        url = raw_url.strip().rstrip("/")
        if not url:
            msg = (
                f"Base URL is required. Set {ENV_API_URL} "
                "(e.g. https://conf-doc.example.com or http://localhost:8000)."
            )
            raise ValueError(msg)

        timeout_value = timeout
        if timeout_value is None:
            raw_timeout = os.environ.get(ENV_API_TIMEOUT, "")
            timeout_value = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT

        self.base_url = url
        self.default_configuration = default_configuration or os.environ.get(ENV_CONFIGURATION)
        self._client = httpx.Client(base_url=url, timeout=timeout_value)

    def close(self) -> None:
        self._client.close()

    def _resolve_configuration(self, configuration: str | None) -> str | None:
        return configuration or self.default_configuration

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        response = self._client.request(method, path, params=params, json=json_body)
        if response.is_success:
            if not response.content:
                return {}
            return response.json()

        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict) and "detail" in payload:
                detail = str(payload["detail"])
        except json.JSONDecodeError:
            pass
        raise ConfDocApiError(
            f"{method} {path} failed ({response.status_code}): {detail}",
            status_code=response.status_code,
        )

    def health(self) -> dict[str, Any]:
        result = self._request("GET", "/health")
        return cast(dict[str, Any], result)

    def list_configurations(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/configurations")
        return cast(list[dict[str, Any]], result)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        full: bool = False,
        object_type: str | None = None,
        configuration: str | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "full": full,
        }
        resolved = self._resolve_configuration(configuration)
        if resolved:
            body["configuration"] = resolved
        if object_type:
            body["object_type"] = object_type
        result = self._request("POST", "/search", json_body=body)
        return cast(list[dict[str, Any]], result)

    def list_objects(
        self,
        *,
        object_type: str | None = None,
        q: str | None = None,
        configuration: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        resolved = self._resolve_configuration(configuration)
        if resolved:
            params["configuration"] = resolved
        if object_type:
            params["object_type"] = object_type
        if q:
            params["q"] = q
        result = self._request("GET", "/objects", params=params)
        return cast(list[dict[str, Any]], result)

    def get_object(
        self,
        object_type: str,
        name: str,
        *,
        configuration: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        resolved = self._resolve_configuration(configuration)
        if resolved:
            params["configuration"] = resolved
        result = self._request("GET", f"/objects/{object_type}/{name}", params=params or None)
        return cast(dict[str, Any], result)

    def get_object_chunk(
        self,
        object_type: str,
        name: str,
        chunk_index: int,
        *,
        configuration: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        resolved = self._resolve_configuration(configuration)
        if resolved:
            params["configuration"] = resolved
        path = f"/objects/{object_type}/{name}/chunks/{chunk_index}"
        result = self._request("GET", path, params=params or None)
        return cast(dict[str, Any], result)

    def query_rag(
        self,
        question: str,
        *,
        top_k: int = 5,
        configuration: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"question": question, "top_k": top_k}
        resolved = self._resolve_configuration(configuration)
        if resolved:
            body["configuration"] = resolved
        result = self._request("POST", "/query", json_body=body)
        return cast(dict[str, Any], result)
