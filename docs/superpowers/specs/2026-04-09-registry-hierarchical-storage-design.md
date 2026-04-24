# Registry Hierarchical Storage Design

## Problem

Registry-published models and datasets are stored flat in `/workspace/models/<asset_name>/` alongside downloaded base models. This causes:

1. **Name collisions**: The "Version Name" (folder name) must be globally unique across all groups and all downloaded models. Users get a confusing "already exists" error even when creating a brand new group.
2. **No structural relationship**: The group/version hierarchy exists only in metadata (JSON files under `/asset_groups/`), not on disk. The filesystem doesn't reflect logical ownership.
3. **Confusing UX**: Users can pick arbitrary version names that have no relation to the version sequence.

## Solution

Store registry-published models/datasets in a `<group_name>/<vN>/` hierarchy within the existing models/datasets directories. Auto-generate version folder names as `v1`, `v2`, `v3`, etc. Remove user-editable version naming from the UI.

## Storage Layout

```
~/.transformerlab/workspace/models/
  meta-llama--Llama-2-7b/          # downloaded base model (flat, unchanged)
    index.json
  MyFineTune/                       # registry group folder
    v1/                             # version 1
      index.json
      model files...
    v2/                             # version 2
      index.json
      model files...
  old_flat_trained_model/           # grandfathered old registry entry (flat)
    index.json
```

Same structure for `/workspace/datasets/`.

### Distinguishing flat models from group folders

When listing models, iterate each subdirectory in `/models/`:
- If it contains `index.json` at its root: it's a flat model (downloaded or grandfathered). Include it directly.
- If it does NOT contain `index.json` but contains subdirectories that do: it's a group folder. Include each versioned subdirectory as a separate model entry.

This requires no marker files or conventions beyond the presence/absence of `index.json`.

## Version Naming

- Folder names are always `v1`, `v2`, `v3`, etc. No user-editable version names.
- To determine the next version number: list existing subdirectories in the group folder matching `v\d+`, find the highest N, use `v(N+1)`. If the group folder doesn't exist, start at `v1`.
- The `asset_id` field in version metadata becomes a relative path: `<group_name>/v1` (relative to `/models/` or `/datasets/`).
- The `version_label` field mirrors the folder name (`v1`, `v2`, etc.).

## Save-to-Registry Flow

### Mode: "new" (create new group)

1. User provides a group name (e.g. "MyFineTune").
2. Backend creates `/models/<group_name>/v1/`.
3. Copies trained model files from job directory to that path.
4. Creates version entry via `asset_version_service.create_version()` with `asset_id = "<group_name>/v1"`.

### Mode: "existing" (add version to existing group)

1. User selects an existing group.
2. Backend inspects `/models/<group_name>/` for existing `vN` folders, computes next version.
3. Creates `/models/<group_name>/v(N+1)/`.
4. Copies files, creates version entry with `asset_id = "<group_name>/v(N+1)"`.

### Error handling

- If the group folder name collides with a flat downloaded model folder, return 409 with a clear message asking the user to pick a different group name.
- The version folder (`vN`) can never collide since it's auto-computed from existing contents.

## UI Changes (SaveToRegistryDialog)

### Remove
- "Version Name" input field (was `assetName` — no longer user-controlled)
- "Version Label" input field (was read-only, now fully auto-generated)

### Keep
- Group Name input (for mode="new")
- Group selector (for mode="existing")
- Tag selector (latest, production, draft)
- Description textarea

### Update
- "Publish as vN" button text shows the auto-computed version number
- Remove `assetNameError` state and 409 inline error handling (no longer possible)

## Backend Changes

### `save_model_to_registry` / `save_dataset_to_registry` (jobs.py)

- Remove `asset_name` query parameter entirely.
- Remove `version_label` query parameter (auto-computed).
- Compute next version: scan group folder for `vN` dirs, pick `v(N+1)`.
- Copy to `/models/<group_name>/v(N+1)/` instead of `/models/<asset_name>/`.
- Pass `asset_id = "<group_name>/v(N+1)"` to `create_version()`.

### `_save_model_to_registry` / `_save_dataset_to_registry` (jobs.py, async helpers)

- Update `dest_path` construction to use `group_name/version_label` path.
- Update `create_version()` call with new `asset_id` format.

### `Model.list_all()` (lab-sdk model.py)

- After scanning flat directories, also detect group folders (no `index.json` at root).
- For each group folder, iterate subdirectories that have `index.json` and include them as model entries.

### `model_service.list_installed_models()` (model_service.py)

- Update path construction to handle `asset_id` values containing `/` (e.g. `MyFineTune/v1`).
- Filesystem existence check: `storage.join(models_dir, asset_id)` already works for relative paths.

### `Model.get_dir()` (lab-sdk model.py)

- No change needed if `self.id` is set to the full relative path (`MyFineTune/v1`). `storage.join(models_dir, "MyFineTune/v1")` resolves correctly.

### `asset_version_service.py`

- `asset_id` values now contain `/`. No functional change needed — it's stored as a string in JSON.
- `get_all_asset_group_map()`: No change — maps `asset_id` to groups regardless of format.

### `asset_versions.py` (router)

- No structural changes. Endpoints serve metadata that already accommodates the new `asset_id` format.

## Frontend Changes

### SaveToRegistryDialog.tsx

- Remove `assetName` state, `assetNameError` state, and related input field.
- Remove `versionLabel` state and input field.
- Add display of auto-computed version (e.g. "Will be saved as v3") fetched from group metadata or computed client-side.
- Update `SaveVersionInfo` interface: remove `assetName` and `versionLabel` fields.

### ModelsSection.tsx / DatasetsSection.tsx

- Remove `assetName` from API call parameters.
- Remove `versionLabel` from API call parameters.
- Remove `assetNameError` state and 409 handling.

### API client (endpoints.ts)

- Update `saveModelToRegistry` / `saveDatasetToRegistry` URL construction to remove `assetName` and `versionLabel` params.

## Grandfathered Entries

Old flat entries (`/models/old_trained_model/`) continue to work:
- They appear in model listings as before (flat `index.json` detected).
- Their `asset_id` in version metadata is a flat name (no `/`), which resolves correctly.
- They may appear as standalone items in the registry, not grouped — this is acceptable.
- No migration is performed.

## Testing

- Update `test_job_save_to_registry.py` to verify:
  - New saves create `<group_name>/v1/` structure
  - Second save to same group creates `v2/`
  - Mode="existing" increments correctly
  - Model listing finds both flat and nested models
  - Grandfathered flat entries still appear
- Frontend: verify dialog works without version name field, button shows correct vN
