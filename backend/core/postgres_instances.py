"""
Postgres Instance Cache Module

Manages a cache of Postgres instance information (host -> compute_family mapping)
for accurate cost calculations. The cache is populated from SHOW POSTGRES INSTANCES
on startup and can be refreshed via the API when instances are resized.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Cache for Postgres instance info (host -> compute_family mapping)
_postgres_instance_cache: dict[str, str] = {}
_postgres_instance_cache_loaded: bool = False


async def load_postgres_instances(*, force_refresh: bool = False) -> dict[str, str]:
    """
    Load Postgres instance information from Snowflake.

    Returns a mapping of host -> compute_family (instance size).
    Results are cached for the lifetime of the application unless force_refresh=True.

    Args:
        force_refresh: If True, bypass the cache and reload from Snowflake.

    Returns:
        Dictionary mapping host (lowercase) to compute_family (uppercase).
    """
    global _postgres_instance_cache, _postgres_instance_cache_loaded

    if _postgres_instance_cache_loaded and not force_refresh:
        return _postgres_instance_cache

    try:
        from backend.connectors.snowflake_pool import get_default_pool

        pool = get_default_pool()
        result = await pool.execute_query("SHOW POSTGRES INSTANCES")

        # Clear cache before reloading
        if force_refresh:
            _postgres_instance_cache.clear()

        # Get column names from the cursor description
        # SHOW commands return: name,owner,owner_role_type,created_on,updated_on,type,origin,host,
        #                       privatelink_service_identifier,compute_family,authentication_authority,
        #                       storage_size,postgres_version,postgres_settings,is_ha,retention_time,state,comment
        # Indices: name=0, host=7, compute_family=9
        for row in result:
            if len(row) > 9:
                instance_name = row[0] or ""
                host = row[7] or ""
                compute_family = row[9] or ""

                if host and compute_family:
                    # Store by full host
                    _postgres_instance_cache[host.lower()] = compute_family.upper()
                    # Also store by instance name for convenience
                    if instance_name:
                        _postgres_instance_cache[f"instance:{instance_name.lower()}"] = compute_family.upper()

        _postgres_instance_cache_loaded = True
        action = "Refreshed" if force_refresh else "Loaded"
        logger.info(f"{action} {len(result)} Postgres instances")

    except Exception as e:
        logger.warning(f"Failed to load Postgres instances: {e}")
        # Don't mark as loaded so we can retry

    return _postgres_instance_cache


async def refresh_postgres_instances() -> dict[str, str]:
    """
    Force refresh the Postgres instance cache.

    Use this when instances have been resized and the cached sizes are stale.

    Returns:
        Dictionary mapping host (lowercase) to compute_family (uppercase).
    """
    return await load_postgres_instances(force_refresh=True)


def get_postgres_instance_size_by_host(host: Optional[str]) -> Optional[str]:
    """
    Get the Postgres instance size (compute_family) for a given host.

    Args:
        host: The Postgres host URL

    Returns:
        Instance size (e.g., "STANDARD_M", "STANDARD_24XLARGE") or None if not found
    """
    if not host:
        return None

    # Normalize host for lookup
    host_lower = host.lower().strip()

    # Try exact match first
    if host_lower in _postgres_instance_cache:
        return _postgres_instance_cache[host_lower]

    # Try partial match (in case we have just the hostname without full URL)
    for cached_host, size in _postgres_instance_cache.items():
        if not cached_host.startswith("instance:"):
            if host_lower in cached_host or cached_host in host_lower:
                return size

    return None


def get_postgres_instance_size_by_name(instance_name: Optional[str]) -> Optional[str]:
    """
    Get the Postgres instance size (compute_family) for a given instance name.

    Args:
        instance_name: The Postgres instance name (e.g., "Postgres18_Std_1Core")

    Returns:
        Instance size (e.g., "STANDARD_M") or None if not found
    """
    if not instance_name:
        return None

    key = f"instance:{instance_name.lower().strip()}"
    return _postgres_instance_cache.get(key)


def get_cached_instances() -> list[dict[str, str]]:
    """
    Get all cached Postgres instances.

    Returns:
        List of dicts with 'host' and 'instance_size' keys.
        Only includes host-based entries (excludes instance: prefixed keys).
    """
    return [
        {"host": host, "instance_size": size}
        for host, size in _postgres_instance_cache.items()
        if not host.startswith("instance:")
    ]
