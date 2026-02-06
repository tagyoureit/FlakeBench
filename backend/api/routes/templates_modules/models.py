"""
Pydantic models for template API requests and responses.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TemplateConfig(BaseModel):
    """Template configuration structure."""

    model_config = {"populate_by_name": True}

    table_type: str
    database: str
    schema_name: str = Field(..., alias="schema")
    table_name: str
    workload_type: str
    duration: int
    concurrent_connections: int
    warehouse_size: str


class TemplateCreate(BaseModel):
    """Request model for creating a template."""

    template_name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    config: Dict[str, Any]
    tags: Optional[Dict[str, str]] = None


class TemplateUpdate(BaseModel):
    """Request model for updating a template."""

    template_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    config: Optional[Dict[str, Any]] = None
    tags: Optional[Dict[str, str]] = None


class TemplateResponse(BaseModel):
    """Response model for template data."""

    template_id: str
    template_name: str
    description: Optional[str]
    config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    tags: Optional[Dict[str, str]]
    usage_count: int
    last_used_at: Optional[datetime]


class AiPrepareResponse(BaseModel):
    template_id: str
    ai_available: bool
    ai_error: Optional[str] = None
    pool_id: Optional[str] = None
    key_column: Optional[str] = None
    time_column: Optional[str] = None
    insert_columns: List[str] = Field(default_factory=list)
    update_columns: List[str] = Field(default_factory=list)
    projection_columns: List[str] = Field(default_factory=list)
    domain_label: Optional[str] = None
    pools: Dict[str, int] = Field(default_factory=dict)
    message: str
    # Interactive Table specific fields
    cluster_by: Optional[List[str]] = None  # Cluster key columns for Interactive Tables
    warnings: List[str] = Field(default_factory=list)  # Validation warnings


class AiAdjustSqlRequest(BaseModel):
    config: Dict[str, Any]


class AiAdjustSqlResponse(BaseModel):
    # Echo back adjusted config fields (client applies these locally; nothing is persisted until save).
    workload_type: str = "CUSTOM"
    custom_point_lookup_query: str
    custom_range_scan_query: str
    custom_insert_query: str
    custom_update_query: str
    custom_point_lookup_pct: int
    custom_range_scan_pct: int
    custom_insert_pct: int
    custom_update_pct: int
    columns: Dict[str, str] = Field(default_factory=dict)
    ai_workload: Dict[str, Any] = Field(default_factory=dict)
    toast_level: str
    summary: str
    # Interactive Table specific fields
    cluster_by: Optional[List[str]] = None  # Cluster key columns for Interactive Tables
    warnings: List[str] = Field(default_factory=list)  # Validation warnings
