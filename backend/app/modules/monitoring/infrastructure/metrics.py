from typing import Any

from prometheus_client import Gauge


class PrometheusMetricsRegistry:
    def __init__(self, registry: Any = None) -> None:
        kwargs = {"registry": registry} if registry is not None else {}
        self._tps_gauge = Gauge(
            "mcs_server_tps",
            "Current TPS per server",
            labelnames=["server_id"],
            **kwargs,
        )
        self._players_gauge = Gauge(
            "mcs_server_players",
            "Current player count per server",
            labelnames=["server_id"],
            **kwargs,
        )
        self._ram_gauge = Gauge(
            "mcs_server_ram_mb",
            "Current RAM usage in MB per server",
            labelnames=["server_id"],
            **kwargs,
        )
        self._cpu_gauge = Gauge(
            "mcs_server_cpu_percent",
            "Current CPU usage per server",
            labelnames=["server_id"],
            **kwargs,
        )
        self._uptime_gauge = Gauge(
            "mcs_server_uptime_seconds",
            "Server uptime in seconds",
            labelnames=["server_id"],
            **kwargs,
        )
        self._world_size_gauge = Gauge(
            "mcs_world_size_bytes",
            "World size in bytes per server",
            labelnames=["server_id"],
            **kwargs,
        )
        self._health_gauge = Gauge(
            "mcs_health_status",
            "Health check result per component: 1=up, 2=degraded, 0=down",
            labelnames=["component"],
            **kwargs,
        )

    def update_tps(self, server_id: str, value: float) -> None:
        self._tps_gauge.labels(server_id=server_id).set(value)

    def update_players(self, server_id: str, value: int) -> None:
        self._players_gauge.labels(server_id=server_id).set(value)

    def update_ram(self, server_id: str, value_mb: float) -> None:
        self._ram_gauge.labels(server_id=server_id).set(value_mb)

    def update_cpu(self, server_id: str, value: float) -> None:
        self._cpu_gauge.labels(server_id=server_id).set(value)

    def update_uptime(self, server_id: str, seconds: float) -> None:
        self._uptime_gauge.labels(server_id=server_id).set(seconds)

    def update_world_size(self, server_id: str, bytes_size: int) -> None:
        self._world_size_gauge.labels(server_id=server_id).set(bytes_size)

    def update_health(self, component: str, status: str) -> None:
        val = {"up": 1, "degraded": 2, "down": 0}.get(status, 0)
        self._health_gauge.labels(component=component).set(val)


_global_prometheus_registry: PrometheusMetricsRegistry | None = None


def get_prometheus_metrics_registry() -> PrometheusMetricsRegistry:
    global _global_prometheus_registry
    if _global_prometheus_registry is None:
        _global_prometheus_registry = PrometheusMetricsRegistry()
    return _global_prometheus_registry
