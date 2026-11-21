"""GWAY Remote-owned Watchtower enrollment service.

This module deliberately has no deployment side effects.  It is designed for a
root-owned, loopback-only systemd unit; its public surface is limited to the
health endpoint and the single enrollment POST route.
"""
from __future__ import annotations

import hashlib
import json
import re
import os
import secrets
import sqlite3
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, IPv4Network, ip_network
from pathlib import Path
from typing import Callable, Iterable

from .bootstrap_script import render_bootstrap_script
from .watchtower_enrollment_ledger import (
    SCHEMA, Enrollment, EnrollmentRejected, EnrollmentFailure, Ledger, _now, _digest,
)
from .watchtower_enrollment_provisioner import (
    MANAGED_BEGIN, MANAGED_END, occupied_addresses, render_managed_peer,
    WireGuard, SubprocessWireGuard, Provisioner,
)
from .watchtower_enrollment_http import make_handler, serve
from .wireguard_enrollment_contract import DEVICE, InvalidEnrollment, MAX_REQUEST_BYTES, parse_enrollment_json, parse_host_identity_enrollment, validate_enrollment



