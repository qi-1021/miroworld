import json

from app.services.model_registry import ModelRegistryService
from scripts.mirofish_models import main


def test_cli_lists_connections_as_stable_json(tmp_path, capsys):
    registry = ModelRegistryService(tmp_path / "model-config")

    exit_code = main(["--json", "connections", "list"], registry=registry)

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "success": True,
        "data": {"revision": 0, "connections": []},
    }


def test_cli_add_never_prints_full_key(tmp_path, capsys):
    registry = ModelRegistryService(tmp_path / "model-config")

    exit_code = main(
        [
            "--json",
            "connections",
            "add",
            "--endpoint",
            "https://models.example.com/v1",
            "--name",
            "Cloud",
            "--api-key",
            "top-secret",
        ],
        registry=registry,
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "top-secret" not in output
    assert json.loads(output)["data"]["connection"]["secret_suffix"] == "cret"
