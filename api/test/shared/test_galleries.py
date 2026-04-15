from transformerlab.shared import galleries


def test_channel_manifests_reject_too_new_min_version():
    manifest = {
        "channel": "stable",
        "min_supported_app_version": "0.30.0",
    }

    assert galleries.is_manifest_version_compatible(manifest, "0.27.0") is False


def test_channel_manifests_accept_matching_version_range():
    manifest = {
        "channel": "stable",
        "min_supported_app_version": "0.20.0",
        "max_supported_app_version": "0.29.0",
    }

    assert galleries.is_manifest_version_compatible(manifest, "0.27.0") is True


def test_only_selected_galleries_use_channel_fetch():
    assert galleries.should_use_channel_bundle(galleries.TASKS_GALLERY_FILE) is True
    assert galleries.should_use_channel_bundle(galleries.INTERACTIVE_GALLERY_FILE) is True
    assert galleries.should_use_channel_bundle(galleries.ANNOUNCEMENTS_GALLERY_FILE) is True
    assert galleries.should_use_channel_bundle(galleries.MODEL_GALLERY_FILE) is False
