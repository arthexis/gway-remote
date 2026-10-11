import pytest

from gway_remote.benchmark import echo
from gway_remote.mobile import execute


def test_echo():
    result = execute("benchmark-echo", {"payload": "hello"})
    assert result["payload"] == "hello"
    assert result["payload_bytes"] == 5
    assert result["processing_ns"] >= 0


@pytest.mark.parametrize("arguments", [{}, {"payload": 4}, {"payload": "x" * 4097}, {"payload": "", "extra": 1}])
def test_invalid_echo(arguments):
    with pytest.raises(ValueError):
        echo(arguments)
