"""Who is sending: the OpenTelemetry resource every metric and span of a process carries.

- `service.name` = the service (`agent`); Prometheus turns it into the `job` label.
- `service.instance.id` = the pod: `instance` if given, else POD_NAME (set it from the Kubernetes
  downward API, `metadata.name`), else the hostname (in Kubernetes the hostname is the pod name).
  Prometheus turns it into the `instance` label.

Both labels land on every series the process exports, ours and the instrumentation libraries'
alike, without any call site passing them. OTEL_RESOURCE_ATTRIBUTES adds more attributes (they
reach Prometheus only in `target_info`, not on every series).
"""

import os
import socket

from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID, SERVICE_NAME, Resource


def instance_id(instance: str | None = None) -> str:
    """The pod this process runs in: `instance`, else POD_NAME, else the hostname."""
    return instance or os.environ.get("POD_NAME") or socket.gethostname()


def service_resource(service: str, instance: str | None = None) -> Resource:
    return Resource.create({SERVICE_NAME: service, SERVICE_INSTANCE_ID: instance_id(instance)})
