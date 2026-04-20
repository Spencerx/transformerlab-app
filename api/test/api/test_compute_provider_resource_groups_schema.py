"""Tests for compute provider resource group schema support."""

import pytest
from pydantic import ValidationError

from transformerlab.schemas.compute_providers import ProviderConfigBase


def test_provider_config_accepts_populated_resource_groups() -> None:
    config = ProviderConfigBase(
        resource_groups=[
            {
                "id": "gpu-large",
                "name": "Large GPU",
                "cpus": "16+",
                "memory": "64GB",
                "disk_space": "500GB",
                "accelerators": "A100:1",
                "num_nodes": 2,
            }
        ]
    )

    assert config.resource_groups is not None
    assert len(config.resource_groups) == 1

    resource_group = config.resource_groups[0]
    assert resource_group.id == "gpu-large"
    assert resource_group.name == "Large GPU"
    assert resource_group.cpus == "16+"
    assert resource_group.memory == "64GB"
    assert resource_group.disk_space == "500GB"
    assert resource_group.accelerators == "A100:1"
    assert resource_group.num_nodes == 2


def test_provider_config_accepts_missing_resource_groups() -> None:
    config = ProviderConfigBase()

    assert config.resource_groups is None


@pytest.mark.parametrize("field_name", ["id", "name"])
def test_provider_config_rejects_empty_required_resource_group_strings(field_name: str) -> None:
    with pytest.raises(ValidationError):
        ProviderConfigBase(
            resource_groups=[
                {
                    "id": "gpu-large",
                    "name": "Large GPU",
                    field_name: "",
                }
            ]
        )
