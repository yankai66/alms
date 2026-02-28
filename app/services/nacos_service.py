"""Nacos integration utilities for configuration management and service discovery."""
from __future__ import annotations

import json
import socket
import threading
from typing import Any, Callable, Dict, List, Optional

from app.core.config import settings
from app.core.logging_config import get_logger

try:  # pragma: no cover - optional dependency in some environments
    from nacos import NacosClient
except ImportError:  # pragma: no cover
    NacosClient = None  # type: ignore[assignment]

ConfigCallback = Callable[[str | None, Optional[Dict[str, Any]]], None]


class NacosManager:
    """Centralized helper to interact with Nacos config and naming services."""

    def __init__(self, app_settings):
        self.settings = app_settings
        self.logger = get_logger(__name__)
        self.client: Optional[NacosClient] = None
        self._config_cache: Optional[str] = None
        self._config_dict: Optional[Dict[str, Any]] = None
        self._config_callbacks: List[ConfigCallback] = []
        self._config_thread: Optional[threading.Thread] = None
        self._config_thread_stop: Optional[threading.Event] = None
        self._is_registered = False
        self._registered_ip: Optional[str] = None
        self._registered_port: Optional[int] = None
        self._registered_metadata: Optional[Dict[str, Any]] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_thread_stop: Optional[threading.Event] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public lifecycle helpers
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Initialize client, start config polling, and register service."""
        if not self._ensure_client():
            return

        if self.settings.NACOS_CONFIG_ENABLED:
            self._sync_config(initial=True)
            self._start_config_poller()

        if self.settings.NACOS_SERVICE_ENABLED:
            self.register_instance()

    def stop(self) -> None:
        """Stop background tasks and unregister service."""
        self._stop_config_poller()
        self._stop_heartbeat()
        if self.settings.NACOS_SERVICE_ENABLED and self._is_registered:
            self.deregister_instance()

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------
    def get_config_text(self) -> Optional[str]:
        return self._config_cache

    def get_config_dict(self) -> Optional[Dict[str, Any]]:
        return self._config_dict

    def add_config_callback(self, callback: ConfigCallback) -> None:
        self._config_callbacks.append(callback)

    def _start_config_poller(self) -> None:
        if self._config_thread and self._config_thread.is_alive():
            return
        self._config_thread_stop = threading.Event()
        self._config_thread = threading.Thread(
            target=self._config_poll_loop,
            name="nacos-config-poller",
            daemon=True,
        )
        self._config_thread.start()
        self.logger.info(
            "Started Nacos config poller (interval=%ss)",
            self.settings.NACOS_CONFIG_POLL_INTERVAL,
        )

    def _stop_config_poller(self) -> None:
        if not self._config_thread_stop:
            return
        self._config_thread_stop.set()
        if self._config_thread:
            self._config_thread.join(timeout=5)
        self._config_thread = None
        self._config_thread_stop = None

    def _config_poll_loop(self) -> None:
        interval = max(5, self.settings.NACOS_CONFIG_POLL_INTERVAL)
        while self._config_thread_stop and not self._config_thread_stop.wait(interval):
            self._sync_config()

    def _sync_config(self, initial: bool = False) -> None:
        if not self.client:
            return
        try:
            content = self.client.get_config(
                self.settings.NACOS_CONFIG_DATA_ID,
                self.settings.NACOS_CONFIG_GROUP,
            )
            if content is None:
                if initial:
                    self.logger.warning(
                        "Nacos config %s/%s not found",
                        self.settings.NACOS_CONFIG_GROUP,
                        self.settings.NACOS_CONFIG_DATA_ID,
                    )
                return
            self._update_config_cache(content)
        except Exception as exc:  # pragma: no cover - network failure
            self.logger.error("Failed to fetch config from Nacos: %s", exc)

    def _update_config_cache(self, content: str) -> None:
        with self._lock:
            if content == self._config_cache:
                return
            self._config_cache = content
            self._config_dict = self._parse_config(content)
        self.logger.info(
            "Loaded config from Nacos dataId=%s group=%s",
            self.settings.NACOS_CONFIG_DATA_ID,
            self.settings.NACOS_CONFIG_GROUP,
        )
        for callback in self._config_callbacks:
            try:
                callback(self._config_cache, self._config_dict)
            except Exception as exc:  # pragma: no cover - user callback
                self.logger.error("Config callback raised error: %s", exc)

    @staticmethod
    def _parse_config(content: str) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            # Support simple key=value lines
            result: Dict[str, Any] = {}
            for line in content.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip()
            return result or None

    # ------------------------------------------------------------------
    # Service registration & discovery
    # ------------------------------------------------------------------
    def register_instance(self) -> None:
        if not self.client:
            return
        ip = self._determine_ip()
        port = self.settings.NACOS_SERVICE_PORT or self.settings.PORT
        if not port:
            self.logger.warning("Cannot register service without port")
            return
        metadata = dict(self.settings.NACOS_METADATA or {})
        metadata.setdefault("version", self.settings.VERSION)
        try:
            self.client.add_naming_instance(
                self.settings.NACOS_SERVICE_NAME,
                ip,
                port,
                cluster_name=self.settings.NACOS_SERVICE_CLUSTER,
                group_name=self.settings.NACOS_SERVICE_GROUP,
                metadata=metadata,
                healthy=True,
                ephemeral=True,
            )
            self._is_registered = True
            self._registered_ip = ip
            self._registered_port = port
            self._registered_metadata = metadata
            self.logger.info(
                "Registered service '%s' to Nacos (%s:%s)",
                self.settings.NACOS_SERVICE_NAME,
                ip,
                port,
            )
            self._start_heartbeat()
        except Exception as exc:  # pragma: no cover
            self.logger.error("Failed to register service in Nacos: %s", exc)

    def deregister_instance(self) -> None:
        if not self.client or not self._is_registered:
            return
        self._stop_heartbeat()
        ip = self._registered_ip or self._determine_ip()
        port = self._registered_port or self.settings.NACOS_SERVICE_PORT or self.settings.PORT
        try:
            self.client.remove_naming_instance(
                self.settings.NACOS_SERVICE_NAME,
                ip,
                port,
                cluster_name=self.settings.NACOS_SERVICE_CLUSTER,
                group_name=self.settings.NACOS_SERVICE_GROUP,
            )
            self.logger.info("Deregistered service '%s' from Nacos", self.settings.NACOS_SERVICE_NAME)
        except Exception as exc:  # pragma: no cover
            self.logger.error("Failed to deregister service from Nacos: %s", exc)
        finally:
            self._is_registered = False
            self._registered_ip = None
            self._registered_port = None
            self._registered_metadata = None

    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        if not self.client or not self._registered_ip or not self._registered_port:
            return
        self._heartbeat_thread_stop = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="nacos-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        self.logger.info(
            "Started Nacos heartbeat thread (interval=%ss)",
            self.settings.NACOS_HEARTBEAT_INTERVAL,
        )

    def _stop_heartbeat(self) -> None:
        if not self._heartbeat_thread_stop:
            return
        self._heartbeat_thread_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
        self._heartbeat_thread = None
        self._heartbeat_thread_stop = None

    def _heartbeat_loop(self) -> None:
        interval = max(2, self.settings.NACOS_HEARTBEAT_INTERVAL)
        # send immediately before waiting to avoid early expiration
        self._send_heartbeat()
        while self._heartbeat_thread_stop and not self._heartbeat_thread_stop.wait(interval):
            self._send_heartbeat()

    def _send_heartbeat(self) -> None:
        if not self.client or not self._registered_ip or not self._registered_port:
            return
        try:
            self.client.send_heartbeat(
                self.settings.NACOS_SERVICE_NAME,
                self._registered_ip,
                self._registered_port,
                cluster_name=self.settings.NACOS_SERVICE_CLUSTER,
                group_name=self.settings.NACOS_SERVICE_GROUP,
                metadata=self._registered_metadata,
                ephemeral=True,
            )
        except Exception as exc:  # pragma: no cover
            self.logger.warning("Failed to send Nacos heartbeat: %s", exc)

    def discover_instances(
        self,
        service_name: str,
        *,
        group_name: Optional[str] = None,
        clusters: Optional[List[str]] = None,
        healthy_only: bool = True,
    ) -> List[Dict[str, Any]]:
        if not self.client:
            return []
        try:
            result = self.client.list_naming_instance(
                service_name,
                group_name=group_name or self.settings.NACOS_SERVICE_GROUP,
                clusters=",".join(clusters) if clusters else None,
                healthy_only=healthy_only,
            )
            return result.get("hosts", []) if isinstance(result, dict) else []
        except Exception as exc:  # pragma: no cover
            self.logger.error("Failed to discover service '%s': %s", service_name, exc)
            return []

    def choose_instance(
        self,
        service_name: str,
        *,
        group_name: Optional[str] = None,
        clusters: Optional[List[str]] = None,
        healthy_only: bool = True,
    ) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None
        try:
            return self.client.select_naming_instance(
                service_name,
                group_name=group_name or self.settings.NACOS_SERVICE_GROUP,
                clusters=",".join(clusters) if clusters else None,
                healthy_only=healthy_only,
            )
        except Exception as exc:  # pragma: no cover
            self.logger.error("Failed to select service '%s': %s", service_name, exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_client(self) -> bool:
        if not self.settings.NACOS_ENABLED:
            self.logger.debug("Nacos integration disabled via settings")
            return False
        if self.client:
            return True
        if NacosClient is None:
            self.logger.warning(
                "nacos-sdk-python is not installed. Run `pip install nacos-sdk-python` to enable Nacos integration."
            )
            return False

        server_addresses = ",".join(self.settings.NACOS_SERVER_ADDRESSES)
        kwargs: Dict[str, Any] = {}
        if self.settings.NACOS_USERNAME:
            kwargs["username"] = self.settings.NACOS_USERNAME
            kwargs["password"] = self.settings.NACOS_PASSWORD
        if self.settings.NACOS_ACCESS_KEY:
            kwargs["ak"] = self.settings.NACOS_ACCESS_KEY
            kwargs["sk"] = self.settings.NACOS_SECRET_KEY

        try:
            self.client = NacosClient(
                server_addresses,
                namespace=self.settings.NACOS_NAMESPACE,
                **kwargs,
            )
            self.logger.info(
                "Initialized Nacos client (namespace=%s, servers=%s)",
                self.settings.NACOS_NAMESPACE,
                server_addresses,
            )
        except Exception as exc:  # pragma: no cover
            self.logger.error("Failed to initialize Nacos client: %s", exc)
            self.client = None
            return False
        return True

    def _determine_ip(self) -> str:
        if self.settings.NACOS_SERVICE_IP:
            return self.settings.NACOS_SERVICE_IP
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:  # pragma: no cover
            return "127.0.0.1"


_nacos_manager: Optional[NacosManager] = None


def get_nacos_manager() -> NacosManager:
    global _nacos_manager
    if _nacos_manager is None:
        _nacos_manager = NacosManager(settings)
    return _nacos_manager
