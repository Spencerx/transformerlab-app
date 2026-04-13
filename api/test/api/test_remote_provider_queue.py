import json


from transformerlab.services.remote_provider_queue import _reconstruct_work_item, RemoteLaunchWorkItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CLUSTER_CONFIG = {
    "instance_type": "g4dn.xlarge",
    "cloud": "aws",
    "region": "us-east-1",
    "num_nodes": 1,
}


def _make_job(
    job_id: str = "job-42",
    experiment_id: str = "exp-1",
    provider_id: str = "prov-1",
    team_id: str = "team-abc",
    user_id: str = "user-xyz",
    cluster_name: str = "my-cluster",
    cluster_config: dict | None | str = None,
    quota_hold_id: str | None = None,
    subtype: str | None = None,
    serialize_job_data: bool = False,
) -> dict:
    """Build a minimal job dict as returned by job_service.job_get."""
    if cluster_config is None:
        cluster_config = _VALID_CLUSTER_CONFIG.copy()

    job_data: dict = {
        "provider_id": provider_id,
        "team_id": team_id,
        "created_by_user_id": user_id,
        "cluster_name": cluster_name,
        "cluster_config": cluster_config,
    }
    if quota_hold_id is not None:
        job_data["quota_hold_id"] = quota_hold_id
    if subtype is not None:
        job_data["subtype"] = subtype

    raw_job_data = json.dumps(job_data) if serialize_job_data else job_data

    return {
        "id": job_id,
        "experiment_id": experiment_id,
        "job_data": raw_job_data,
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_reconstruct_work_item_happy_path():
    job = _make_job(quota_hold_id="hold-1", subtype="interactive")
    item = _reconstruct_work_item(job)

    assert isinstance(item, RemoteLaunchWorkItem)
    assert item.job_id == "job-42"
    assert item.experiment_id == "exp-1"
    assert item.provider_id == "prov-1"
    assert item.team_id == "team-abc"
    assert item.user_id == "user-xyz"
    assert item.cluster_name == "my-cluster"
    assert item.cluster_config.cloud == "aws"
    assert item.cluster_config.region == "us-east-1"
    assert item.quota_hold_id == "hold-1"
    assert item.subtype == "interactive"


def test_reconstruct_work_item_optional_fields_default_to_none():
    """quota_hold_id and subtype should be None when absent."""
    job = _make_job()
    item = _reconstruct_work_item(job)

    assert item is not None
    assert item.quota_hold_id is None
    assert item.subtype is None


def test_reconstruct_work_item_job_data_as_json_string():
    """job_data stored as a JSON string should be parsed and yield the same result."""
    job = _make_job(serialize_job_data=True)
    item = _reconstruct_work_item(job)

    assert isinstance(item, RemoteLaunchWorkItem)
    assert item.provider_id == "prov-1"
    assert item.cluster_name == "my-cluster"


def test_reconstruct_work_item_empty_job_data_string():
    """A completely unparseable job_data string should fall back to {} and return None."""
    job = {"id": "job-bad", "experiment_id": "exp-1", "job_data": "not-valid-json!!!"}
    item = _reconstruct_work_item(job)
    assert item is None


def test_reconstruct_work_item_none_job_data():
    """None job_data should be treated as empty dict and return None."""
    job = {"id": "job-bad", "experiment_id": "exp-1", "job_data": None}
    item = _reconstruct_work_item(job)
    assert item is None


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


def test_reconstruct_work_item_missing_provider_id():
    job = _make_job()
    del job["job_data"]["provider_id"]
    assert _reconstruct_work_item(job) is None


def test_reconstruct_work_item_missing_team_id():
    job = _make_job()
    del job["job_data"]["team_id"]
    assert _reconstruct_work_item(job) is None


def test_reconstruct_work_item_missing_cluster_name():
    job = _make_job()
    del job["job_data"]["cluster_name"]
    assert _reconstruct_work_item(job) is None


def test_reconstruct_work_item_missing_cluster_config():
    job = _make_job()
    del job["job_data"]["cluster_config"]
    assert _reconstruct_work_item(job) is None


# ---------------------------------------------------------------------------
# Invalid cluster_config
# ---------------------------------------------------------------------------


def test_reconstruct_work_item_cluster_config_not_a_dict():
    """cluster_config must be a dict; a string or list should cause None."""
    job = _make_job(cluster_config="not-a-dict")
    assert _reconstruct_work_item(job) is None


def test_reconstruct_work_item_cluster_config_list():
    job = _make_job(cluster_config=["a", "b"])
    assert _reconstruct_work_item(job) is None


def test_reconstruct_work_item_cluster_config_none():
    job = _make_job(cluster_config=None)
    # We set cluster_config explicitly to None via job_data
    job["job_data"]["cluster_config"] = None
    assert _reconstruct_work_item(job) is None


def test_reconstruct_work_item_cluster_config_empty_dict():
    """An empty dict is falsy, so the guard `if not cluster_config_raw` treats it as missing."""
    job = _make_job(cluster_config={})
    item = _reconstruct_work_item(job)
    assert item is None
