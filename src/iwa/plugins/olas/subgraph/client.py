"""Low-level GraphQL client for OLAS subgraphs."""

import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from requests.exceptions import RequestException

from iwa.core.http import create_retry_session

# Cache: {key: (timestamp, data)}
_QUERY_CACHE: Dict[str, Tuple[float, Any]] = {}
DEFAULT_CACHE_TTL = 300  # 5 minutes


class SubgraphError(Exception):
    """Raised on subgraph query failures."""


class GraphQLClient:
    """Low-level GraphQL HTTP client with retry, pagination, and caching."""

    def __init__(
        self,
        endpoint: str,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ):
        """Initialize with endpoint URL and optional cache TTL."""
        self.endpoint = endpoint
        self.session = create_retry_session()
        self._cache_ttl = cache_ttl

    def query(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        cache_ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute a GraphQL query.

        Args:
            query: GraphQL query string.
            variables: Optional query variables.
            cache_ttl: Override default cache TTL (seconds). Use 0 to skip cache.

        Returns:
            The ``data`` dict from the GraphQL response.

        Raises:
            SubgraphError: On HTTP or GraphQL errors.

        """
        ttl = self._cache_ttl if cache_ttl is None else cache_ttl

        # Check cache
        if ttl > 0:
            cache_key = self._cache_key(query, variables)
            cached = _QUERY_CACHE.get(cache_key)
            if cached and (time.time() - cached[0]) < ttl:
                return cached[1]

        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = self.session.post(
                self.endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
        except RequestException as exc:
            raise SubgraphError(f"HTTP error querying {self.endpoint}: {exc}") from exc

        body = response.json()

        if "errors" in body:
            errors = body["errors"]
            msg = errors[0].get("message", str(errors)) if errors else str(errors)
            raise SubgraphError(f"GraphQL error: {msg}")

        data = body.get("data", {})

        # Store in cache
        if ttl > 0:
            _QUERY_CACHE[cache_key] = (time.time(), data)

        return data

    def query_all(
        self,
        query_template: str,
        entity_name: str,
        variables: Optional[Dict[str, Any]] = None,
        page_size: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Auto-paginate using the id_gt cursor pattern.

        The ``query_template`` must use ``$lastId: String`` and
        ``$pageSize: Int`` variables, and apply them as:
        ``(first: $pageSize, where: {id_gt: $lastId})``.

        Args:
            query_template: GraphQL query with pagination variables.
            entity_name: Top-level entity key in the response data.
            variables: Additional query variables (merged with pagination vars).
            page_size: Number of entities per page.

        Returns:
            Flat list of all entities across pages.

        """
        all_entities: List[Dict[str, Any]] = []
        last_id = ""

        while True:
            page_vars = {"lastId": last_id, "pageSize": page_size}
            if variables:
                page_vars.update(variables)

            data = self.query(query_template, variables=page_vars, cache_ttl=0)
            entities = data.get(entity_name, [])
            if not entities:
                break

            all_entities.extend(entities)
            last_id = entities[-1]["id"]

            if len(entities) < page_size:
                break

        return all_entities

    def close(self) -> None:
        """Close the HTTP session."""
        self.session.close()

    @staticmethod
    def _cache_key(query: str, variables: Optional[Dict[str, Any]]) -> str:
        raw = query + (str(sorted(variables.items())) if variables else "")
        return hashlib.md5(raw.encode()).hexdigest()  # noqa: S324


def clear_cache() -> None:
    """Clear the global query cache."""
    _QUERY_CACHE.clear()
    logger.debug("Subgraph query cache cleared")
