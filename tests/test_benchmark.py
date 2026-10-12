"""Benchmark contract and HTTP integration tests."""
import json
import pytest

from gway_remote.benchmark import echo, summarize
from gway_remote.mobile import execute
from tests.test_mobile_api import ApiTests


def test_echo_round_trip():
    result = execute("benchmark-echo", {"payload": "hello"})
    assert result["payload"] == "hello"
    assert result["payload_bytes"] == 5
    assert result["processing_ns"] >= 0


@pytest.mark.parametrize("arguments", [{}, {"payload": 4}, {"payload": "x" * 4097},
                                         {"payload": "", "extra": 1}, {"payload": "é" * 2049}])
def test_invalid_echo(arguments):
    with pytest.raises(ValueError):
        echo(arguments)


def test_statistics_nearest_rank_p95():
    values = list(range(1, 101))
    assert summarize(values, 2) == {"samples": 100, "failures": 2, "median_ns": 50.5,
                                      "p95_ns": 95, "min_ns": 1, "max_ns": 100}
    assert summarize([9])["p95_ns"] == 9
    assert summarize([], 3)["median_ns"] is None


@pytest.mark.parametrize("samples,failures", [([-1], 0), ([1.2], 0), ([True], 0),
                                              ([1], -1), ([1], True), ("bad", 0)])
def test_invalid_statistics(samples, failures):
    with pytest.raises(ValueError):
        summarize(samples, failures)


def test_authenticated_http_echo():
    case = ApiTests(methodName="test_health_and_catalog")
    case.setUp()
    try:
        payload = json.dumps({"command": "benchmark-echo", "arguments": {"payload": "ping"}}).encode()
        status, body = case.request("POST", "/api/v1/execute", payload)
        assert status == 200
        assert body["result"]["payload"] == "ping"
        assert case.request("POST", "/api/v1/execute", payload, token="bad")[0] == 401
        invalid = json.dumps({"command": "benchmark-echo", "arguments": {"payload": 1}}).encode()
        assert case.request("POST", "/api/v1/execute", invalid)[0] == 400
    finally:
        case.doCleanups()
