"""Helpers for handling dynamic configuration fetched from Nacos."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field


class FeatureFlags(BaseModel):
    """Common feature toggles with sensible defaults."""

    model_config = ConfigDict(extra="allow")

    enable_full_scan: bool = False
    enable_auto_lifecycle: bool = False


class ExternalAPIConfig(BaseModel):
    """Configuration for downstream HTTP APIs."""

    model_config = ConfigDict(extra="allow")

    base_url: Optional[str] = None
    token: Optional[str] = None


class NacosRuntimeConfig(BaseModel):
    """Normalized structure for runtime configuration."""

    model_config = ConfigDict(extra="allow")

    version: Optional[str] = None
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)
    external_api: ExternalAPIConfig = Field(default_factory=ExternalAPIConfig)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    raw: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "NacosRuntimeConfig":
        payload: Dict[str, Any] = data.copy() if isinstance(data, dict) else {}
        instance = cls(**payload)
        instance.raw = payload
        return instance

    def get(self, path: str, default: Any = None) -> Any:
        """Retrieve nested values using dot-notation (e.g., "feature_flags.enable_full_scan")."""
        if not path:
            return default
        parts = path.split(".")
        value: Any = self.raw
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value


def get_runtime_config(request: Request) -> NacosRuntimeConfig:
    """FastAPI dependency to access the latest runtime config."""
    runtime_cfg = getattr(request.app.state, "runtime_config", None)
    if runtime_cfg is None:
        runtime_cfg = NacosRuntimeConfig()
        request.app.state.runtime_config = runtime_cfg
    return runtime_cfg
