"""Tests for parsing interactive tunnel/local URLs from provider logs."""

from transformerlab.shared.tunnel_parser import (
    get_tunnel_info,
    get_jupyter_tunnel_info,
    get_ollama_tunnel_info,
    get_vllm_tunnel_info,
)


def test_get_jupyter_tunnel_info_parses_local_server_output() -> None:
    logs = """
    [I 2026-04-14 10:00:00.000 ServerApp] Jupyter Server 2.14.0 is running at:
    [I 2026-04-14 10:00:00.000 ServerApp] http://localhost:8888/lab?token=abc123xyz987
    """
    info = get_jupyter_tunnel_info(logs)

    assert info["is_ready"] is True
    assert info["token"] == "abc123xyz987"
    assert info["tunnel_url"] == "http://localhost:8888/lab?token=abc123xyz987"
    assert info["jupyter_url"] == "http://localhost:8888/lab?token=abc123xyz987"


def test_get_vllm_tunnel_info_parses_local_port_urls() -> None:
    logs = """
    INFO vLLM API ready at http://0.0.0.0:8000
    INFO Open WebUI ready at http://localhost:8080
    """
    info = get_vllm_tunnel_info(logs)

    assert info["is_ready"] is True
    assert info["tunnel_url"] == "http://0.0.0.0:8000"
    assert info["vllm_url"] == "http://0.0.0.0:8000"
    assert info["openwebui_url"] == "http://localhost:8080"


def test_get_ollama_tunnel_info_parses_local_port_urls() -> None:
    logs = """
    INFO Ollama API listening on http://127.0.0.1:11434
    INFO Open WebUI listening on http://localhost:8080
    """
    info = get_ollama_tunnel_info(logs)

    assert info["is_ready"] is True
    assert info["tunnel_url"] == "http://127.0.0.1:11434"
    assert info["ollama_url"] == "http://127.0.0.1:11434"
    assert info["openwebui_url"] == "http://localhost:8080"


def test_get_tunnel_info_prefers_gallery_url_patterns_for_known_type() -> None:
    logs = "INFO service ready at http://localhost:8000"
    patterns = [
        {
            "value_key": "vllm_url",
            "regex": r"(https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):8000[^\s]*)",
            "group": 1,
        }
    ]

    info = get_tunnel_info(logs, "vllm", url_patterns=patterns)

    assert info["is_ready"] is True
    assert info["status"] == "ready"
    assert info["vllm_url"] == "http://localhost:8000"
