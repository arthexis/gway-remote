"""Read-only probe contract for GWay Remote deployment targets.

Adding a deployment target requires no health logic changes: missing probes
produce UNKNOWN. Paths are relative to the appliance operator's home.
"""
from dataclasses import dataclass

from .reconcile import TARGETS


@dataclass(frozen=True)
class Probe:
    kind: str = "unknown"  # unknown, csms, executable, lcd, systemd
    executable: str | None = None
    service: str | None = None
    release: str | None = None
    revision_pattern: str | None = None
    revision_from_executable: bool = False
    revision_file: str | None = None


PROBES = {
    "ocpp-csms": Probe("csms", release=".local/share/ocpp-csms/current",
                        revision_pattern=r"[0-9a-f]{12}(?:-dev)?"),
    "ocpp-simulator": Probe("executable", executable=".local/bin/ocpp-simulator",
                            release=".local/share/ocpp-simulator/current",
                            revision_pattern=r"[0-9a-f]{12}"),
    "gway-lcd-sound": Probe("lcd", executable=".local/bin/gway-app-observer",
                            release=".local/share/gway-lcd-sound/current",
                            revision_pattern=r"[0-9a-f]{12}(?:-dev)?"),
    "ocpp-reports": Probe("executable", executable="/usr/local/bin/ocpp-reports",
                          revision_from_executable=True),
    "gway-agent-ops": Probe("executable", executable=".local/bin/agent",
                           revision_from_executable=True),
    "gway-ap-kiosk": Probe("systemd", service="gway-kiosk-status.service",
                           revision_file="/var/lib/gway-ap-kiosk/installed-revision"),
    "gway-rfid": Probe("systemd", service="gway-rfid.service",
                       release=".local/share/gway-rfid/current",
                       revision_pattern=r"[0-9a-f]{40}"),
}


def probe_for(name):
    if name not in dict(TARGETS):
        return Probe()
    return PROBES.get(name, Probe())
