# Registry Hierarchical Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store registry-published models/datasets under `<group_name>/<vN>/` hierarchical folders instead of flat, and auto-generate version names as v1, v2, v3.

**Architecture:** Backend save-to-registry endpoints compute the next `vN` folder automatically and copy files to `<registry_dir>/<group_name>/<vN>/`. The SDK `Model.list_all()` detects group folders (no `index.json` at root) and walks one level deeper. Frontend dialog removes version name/label inputs.

**Tech Stack:** Python (FastAPI, lab-sdk), TypeScript (React, MUI Joy)

---

### Task 1: Update backend save_model_to_registry endpoint

**Files:**
- Modify: `api/transformerlab/routers/experiment/jobs.py:1656-1748`

The endpoint currently stores models flat at `<models_dir>/<asset_name>/`. Change it to compute the next `vN` folder inside `<models_dir>/<group_name>/` and remove the `asset_name` and `version_label` query parameters.

- [ ] **Step 1: Rewrite `save_model_to_registry` endpoint**

Replace the endpoint signature and body. Remove `asset_name` and `version_label` parameters. Both `mode="new"` and `mode="existing"` now use the same logic: resolve group name, compute next vN, copy to `<models_dir>/<group_name>/<vN>/`.

In `api/transformerlab/routers/experiment/jobs.py`, replace the entire `save_model_to_registry` function (lines 1656-1748) with:

```python
@router.post("/{job_id}/models/{model_name}/save_to_registry")
async def save_model_to_registry(
    job_id: str,
    model_name: str,
    experimentId: str,
    target_name: Optional[str] = Query(None, description="Group name for the model in the registry"),
    mode: str = Query(
        "new", description="'new' to create a new entry, 'existing' to add version to existing group"
    ),
    tag: str = Query("latest", description="Tag to assign to the new version"),
    description: Optional[str] = Query(None, description="Human-readable description for the version"),
):
    """Copy a model from job's models directory to the global models registry."""

    try:
        model_name_secure = secure_filename(model_name)

        # Get source path (job's models directory)
        job_models_dir = await get_job_models_dir(job_id, experimentId)
        source_path = storage.join(job_models_dir, model_name_secure)

        if not await storage.exists(source_path):
            raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found in job directory")

        models_registry_dir = await get_models_dir()

        # Resolve the group name
        group_name = secure_filename(target_name) if target_name else model_name_secure

        if mode == "existing":
            if not target_name:
                raise HTTPException(status_code=400, detail="target_name is required when mode is 'existing'")
            # Verify the group exists in the asset versioning system or on disk
            existing_groups = await asset_version_service.list_groups("model")
            group_in_versions = any(g["group_name"] == group_name for g in existing_groups)
            group_on_disk = await storage.exists(storage.join(models_registry_dir, group_name))
            if not group_in_versions and not group_on_disk:
                raise HTTPException(status_code=404, detail=f"Model group '{target_name}' not found in registry")
        else:
            # For mode='new', check that group name doesn't collide with a flat downloaded model
            group_dir = storage.join(models_registry_dir, group_name)
            if await storage.exists(group_dir):
                index_path = storage.join(group_dir, "index.json")
                if await storage.exists(index_path):
                    raise HTTPException(
                        status_code=409,
                        detail=f"A downloaded model named '{group_name}' already exists. Please choose a different group name.",
                    )

        # Compute next version number by scanning existing vN folders
        group_dir = storage.join(models_registry_dir, group_name)
        version_label = await _compute_next_version(group_dir)

        # Destination is <models_dir>/<group_name>/<vN>/
        dest_path = storage.join(group_dir, version_label)

        asyncio.create_task(
            _save_model_to_registry(
                job_id=job_id,
                model_name_secure=model_name_secure,
                source_path=source_path,
                dest_path=dest_path,
                group_name=group_name,
                asset_id=f"{group_name}/{version_label}",
                version_label=version_label,
                tag=tag,
                description=description,
            )
        )

        return {"status": "started", "message": "Model save to registry started"}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting model save to registry for job {job_id}: {str(e)}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to start model save to registry: {str(e)}")
```

- [ ] **Step 2: Add `_compute_next_version` helper**

Add this helper function above the save endpoints (around line 1520, after the model listing helper):

```python
async def _compute_next_version(group_dir: str) -> str:
    """Scan a group directory for existing vN folders and return the next version label."""
    import re

    highest = 0
    if await storage.exists(group_dir):
        try:
            entries = await storage.ls(group_dir, detail=False)
            for entry in entries:
                name = entry.rstrip("/").split("/")[-1]
                match = re.match(r"^v(\d+)$", name)
                if match:
                    highest = max(highest, int(match.group(1)))
        except Exception:
            pass
    return f"v{highest + 1}"
```

- [ ] **Step 3: Rewrite `_save_model_to_registry` async helper**

Replace the existing helper (lines 1751-1781) with:

```python
async def _save_model_to_registry(
    job_id: str,
    model_name_secure: str,
    source_path: str,
    dest_path: str,
    group_name: str,
    asset_id: str,
    version_label: str,
    tag: str,
    description: Optional[str],
):
    """Coroutine that performs the copy and creates the version entry."""
    await storage.copy_dir(source_path, dest_path)

    version_description = description if description else f"Created from job {job_id}"
    await asset_version_service.create_version(
        asset_type="model",
        group_name=group_name,
        asset_id=asset_id,
        version_label=version_label,
        job_id=job_id,
        description=version_description,
        tag=tag,
    )

    return asset_id
```

- [ ] **Step 4: Run linting**

Run: `cd api && ruff check transformerlab/routers/experiment/jobs.py --select E,W,F && ruff format transformerlab/routers/experiment/jobs.py`

- [ ] **Step 5: Commit**

```bash
git add api/transformerlab/routers/experiment/jobs.py
git commit -m "feat: store registry models under group/vN hierarchy"
```

---

### Task 2: Update backend save_dataset_to_registry endpoint

**Files:**
- Modify: `api/transformerlab/routers/experiment/jobs.py:1526-1653`

Same changes as Task 1 but for datasets.

- [ ] **Step 1: Rewrite `save_dataset_to_registry` endpoint**

Replace the entire `save_dataset_to_registry` function (lines 1526-1620) with:

```python
@router.post("/{job_id}/datasets/{dataset_name}/save_to_registry")
async def save_dataset_to_registry(
    job_id: str,
    dataset_name: str,
    experimentId: str,
    target_name: Optional[str] = Query(None, description="Group name for the dataset in the registry"),
    mode: str = Query(
        "new", description="'new' to create a new entry, 'existing' to add version to existing group"
    ),
    tag: str = Query("latest", description="Tag to assign to the new version"),
    description: Optional[str] = Query(None, description="Human-readable description for the version"),
    user_and_team=Depends(get_user_and_team),
    session: AsyncSession = Depends(get_async_session),
):
    """Copy a dataset from job's datasets directory to the global datasets registry."""

    try:
        dataset_name_secure = secure_filename(dataset_name)

        # Get source path (job's datasets directory)
        job_datasets_dir = await get_job_datasets_dir(job_id, experimentId)
        source_path = storage.join(job_datasets_dir, dataset_name_secure)

        if not await storage.exists(source_path):
            raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found in job directory")

        datasets_registry_dir = await get_datasets_dir()

        # Resolve the group name
        group_name = secure_filename(target_name) if target_name else dataset_name_secure

        if mode == "existing":
            if not target_name:
                raise HTTPException(status_code=400, detail="target_name is required when mode is 'existing'")
            existing_groups = await asset_version_service.list_groups("dataset")
            group_in_versions = any(g["group_name"] == group_name for g in existing_groups)
            group_on_disk = await storage.exists(storage.join(datasets_registry_dir, group_name))
            if not group_in_versions and not group_on_disk:
                raise HTTPException(status_code=404, detail=f"Dataset group '{target_name}' not found in registry")
        else:
            # For mode='new', check that group name doesn't collide with a flat downloaded dataset
            group_dir = storage.join(datasets_registry_dir, group_name)
            if await storage.exists(group_dir):
                index_path = storage.join(group_dir, "index.json")
                if await storage.exists(index_path):
                    raise HTTPException(
                        status_code=409,
                        detail=f"A dataset named '{group_name}' already exists. Please choose a different group name.",
                    )

        # Compute next version number
        group_dir = storage.join(datasets_registry_dir, group_name)
        version_label = await _compute_next_version(group_dir)

        dest_path = storage.join(group_dir, version_label)

        asyncio.create_task(
            _save_dataset_to_registry(
                job_id=job_id,
                dataset_name_secure=dataset_name_secure,
                source_path=source_path,
                dest_path=dest_path,
                group_name=group_name,
                asset_id=f"{group_name}/{version_label}",
                version_label=version_label,
                tag=tag,
                description=description,
            )
        )

        return {"status": "started", "message": "Dataset save to registry started"}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error starting dataset save to registry for job {job_id}: {str(e)}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to start dataset save to registry: {str(e)}")
```

- [ ] **Step 2: Rewrite `_save_dataset_to_registry` async helper**

Replace the existing helper (lines 1623-1653) with:

```python
async def _save_dataset_to_registry(
    job_id: str,
    dataset_name_secure: str,
    source_path: str,
    dest_path: str,
    group_name: str,
    asset_id: str,
    version_label: str,
    tag: str,
    description: Optional[str],
):
    """Coroutine that performs the copy and creates the version entry."""
    await storage.copy_dir(source_path, dest_path)

    version_description = description if description else f"Created from job {job_id}"
    await asset_version_service.create_version(
        asset_type="dataset",
        group_name=group_name,
        asset_id=asset_id,
        version_label=version_label,
        job_id=job_id,
        description=version_description,
        tag=tag,
    )

    return asset_id
```

- [ ] **Step 3: Run linting**

Run: `cd api && ruff check transformerlab/routers/experiment/jobs.py --select E,W,F && ruff format transformerlab/routers/experiment/jobs.py`

- [ ] **Step 4: Commit**

```bash
git add api/transformerlab/routers/experiment/jobs.py
git commit -m "feat: store registry datasets under group/vN hierarchy"
```

---

### Task 3: Update Model.list_all() to detect group folders

**Files:**
- Modify: `lab-sdk/src/lab/model.py:90-111`

The `list_all()` static method iterates `/models/` and assumes every subdirectory is a flat model. Now it must also handle group folders (directories that don't contain `index.json` but have `vN/` subdirectories that do).

- [ ] **Step 1: Rewrite `list_all()` method**

In `lab-sdk/src/lab/model.py`, replace the `list_all` method (lines 90-111) with:

```python
    @staticmethod
    async def list_all():
        """List all models in the filesystem.

        Handles two layouts:
        - Flat: /models/<model_id>/index.json  (downloaded or grandfathered)
        - Grouped: /models/<group>/<vN>/index.json  (registry-published)
        """
        results = []
        models_dir = await get_models_dir()
        if not await storage.isdir(models_dir):
            return results
        try:
            entries = await storage.ls(models_dir, detail=False)
        except Exception:
            entries = []
        for full in entries:
            if not await storage.isdir(full):
                continue
            entry = full.rstrip("/").split("/")[-1]
            # Check if this is a flat model (has index.json at root)
            index_path = storage.join(full, "index.json")
            if await storage.exists(index_path):
                try:
                    model = Model(entry)
                    results.append(await model.get_metadata())
                except Exception:
                    continue
            else:
                # Might be a group folder — check subdirectories for index.json
                try:
                    sub_entries = await storage.ls(full, detail=False)
                except Exception:
                    continue
                for sub_full in sub_entries:
                    if not await storage.isdir(sub_full):
                        continue
                    sub_index = storage.join(sub_full, "index.json")
                    if await storage.exists(sub_index):
                        try:
                            version_name = sub_full.rstrip("/").split("/")[-1]
                            # Use relative path as model id: group/vN
                            model_id = f"{entry}/{version_name}"
                            model = Model(model_id)
                            results.append(await model.get_metadata())
                        except Exception:
                            continue
        return results
```

- [ ] **Step 2: Update `get_dir()` to handle paths with `/`**

The `get_dir()` method at line 46 uses `secure_filename()` which strips `/`. For grouped models with ids like `MyFineTune/v1`, we need to handle the path segments separately.

In `lab-sdk/src/lab/model.py`, replace `get_dir` (lines 46-54) with:

```python
    async def get_dir(self):
        """Return the directory for this model.

        Handles both flat ids ('my-model') and grouped ids ('MyFineTune/v1').
        """
        if self.job_id:
            models_dir = await get_job_models_dir(self.job_id)
            model_id_safe = secure_filename(str(self.id))
            return storage.join(models_dir, model_id_safe)
        else:
            models_dir = await get_models_dir()
            # Handle grouped ids like "MyFineTune/v1"
            parts = str(self.id).split("/")
            safe_parts = [secure_filename(p) for p in parts]
            return storage.join(models_dir, *safe_parts)
```

- [ ] **Step 3: Run linting**

Run: `cd api && ruff check ../lab-sdk/src/lab/model.py --select E,W,F && ruff format ../lab-sdk/src/lab/model.py`

- [ ] **Step 4: Commit**

```bash
git add lab-sdk/src/lab/model.py
git commit -m "feat: Model.list_all() and get_dir() support group/vN layout"
```

---

### Task 4: Update frontend SaveToRegistryDialog

**Files:**
- Modify: `src/renderer/components/Experiment/Tasks/SaveToRegistryDialog.tsx`

Remove the "Version Name" and "Version Label" input fields. The dialog now only collects: group name, tag, and description. Show the auto-computed version ("Will be saved as vN") based on group metadata.

- [ ] **Step 1: Update SaveVersionInfo interface and remove unused state**

In `src/renderer/components/Experiment/Tasks/SaveToRegistryDialog.tsx`, replace the `SaveVersionInfo` interface (lines 40-55) with:

```typescript
export interface SaveVersionInfo {
  /** The display name for the group (new name or existing display name) */
  groupName: string;
  /** The UUID group_id when adding to an existing group */
  groupId?: string;
  /** 'new' = create a new group, 'existing' = add version to existing group */
  mode: 'new' | 'existing';
  /** Tag to assign to the new version */
  tag: string;
  /** Human-readable description for the version */
  description: string;
}
```

- [ ] **Step 2: Update the component props interface**

Remove the `assetNameError` prop. In the `SaveToRegistryDialogProps` interface (lines 57-74), replace it with:

```typescript
interface SaveToRegistryDialogProps {
  open: boolean;
  onClose: () => void;
  /** The original name from the job (used as default for "Save as new") */
  sourceName: string;
  /** 'dataset' or 'model' — used for labels */
  type: 'dataset' | 'model';
  /** List of existing registry entry names for the "Add to existing" option */
  existingNames: string[];
  /** Whether the save is in progress */
  saving: boolean;
  /** Called when the user confirms the save */
  onSave: (info: SaveVersionInfo) => void;
  /** Job ID that produced this asset (optional, for display) */
  jobId?: string | number;
}
```

- [ ] **Step 3: Simplify component state and reset logic**

Replace lines 91-175 (component function opening through the `useEffect` hooks) with:

```typescript
export default function SaveToRegistryDialog({
  open,
  onClose,
  sourceName,
  type,
  existingNames,
  saving,
  onSave,
  jobId,
}: SaveToRegistryDialogProps) {
  const [mode, setMode] = useState<'new' | 'existing'>('new');
  const [newName, setNewName] = useState(sourceName);
  const [existingTarget, setExistingTarget] = useState<string | null>(null);
  const [tag, setTag] = useState<string>('latest');
  const [description, setDescription] = useState('');

  // Fetch existing groups from asset_versions API
  const { data: groupsData } = useSWR(
    open ? chatAPI.Endpoints.AssetVersions.ListGroups(type) : null,
    fetcher,
  );
  const groups: GroupSummary[] = Array.isArray(groupsData) ? groupsData : [];
  const groupNames = groups.map((g) => g.group_name);

  // Find selected group info for "next version" display
  const selectedGroup =
    mode === 'existing' && existingTarget
      ? groups.find((g) => g.group_id === existingTarget)
      : null;

  // Compute what version label will be used
  const nextVersionLabel =
    mode === 'new'
      ? 'v1'
      : selectedGroup
        ? `v${(selectedGroup.version_count ?? 0) + 1}`
        : 'v1';

  // Reset state when opening
  useEffect(() => {
    if (open) {
      setMode('new');
      setNewName(sourceName);
      setExistingTarget(null);
      setTag('latest');
      setDescription('');
    }
  }, [open, sourceName]);

  const typeLabel = type === 'dataset' ? 'Dataset' : 'Model';

  const canSave =
    (mode === 'new'
      ? newName.trim().length > 0
      : existingTarget !== null && existingTarget.trim().length > 0);

  const handleSubmit = () => {
    if (!canSave) return;
    const groupName =
      mode === 'new'
        ? newName.trim()
        : (selectedGroup?.group_name ?? existingTarget!);
    onSave({
      groupName,
      groupId: mode === 'existing' ? existingTarget! : undefined,
      mode,
      tag,
      description:
        description.trim() || `Created from job ${jobId ?? 'unknown'}`,
    });
  };
```

- [ ] **Step 4: Simplify the dialog body — remove version name and version label fields**

Replace the entire `<DialogContent>` section (from `<DialogContent sx={{ overflow: 'auto' }}>` through its closing tag) with:

```tsx
        <DialogContent sx={{ overflow: 'auto' }}>
          {/* ── Group selection ── */}
          <RadioGroup
            value={mode}
            onChange={(e) => setMode(e.target.value as 'new' | 'existing')}
            sx={{ gap: 2 }}
          >
            {/* Option 1: Create new group */}
            <Box>
              <Radio value="new" label={`Create new ${typeLabel}`} />
              {mode === 'new' && (
                <FormControl sx={{ ml: 4, mt: 1 }}>
                  <FormLabel>Name</FormLabel>
                  <Input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder={`e.g. my-${typeLabel.toLowerCase()}`}
                    autoFocus
                  />
                </FormControl>
              )}
            </Box>

            {/* Option 2: Add version to existing group */}
            <Box>
              <Radio
                value="existing"
                label={`Add as version to existing ${typeLabel}`}
                disabled={groupNames.length === 0}
              />
              {mode === 'existing' && (
                <FormControl sx={{ ml: 4, mt: 1 }}>
                  <Autocomplete
                    options={groups}
                    getOptionLabel={(option) =>
                      typeof option === 'string' ? option : option.group_name
                    }
                    isOptionEqualToValue={(option, value) =>
                      option.group_id === value.group_id
                    }
                    value={selectedGroup ?? null}
                    onChange={(_e, value) =>
                      setExistingTarget(value ? value.group_id : null)
                    }
                    placeholder={`Search ${typeLabel.toLowerCase()}s…`}
                    autoFocus
                  />
                  {selectedGroup && (
                    <Typography
                      level="body-xs"
                      color="neutral"
                      sx={{ mt: 0.5 }}
                    >
                      Currently has {selectedGroup.version_count} version
                      {selectedGroup.version_count !== 1 ? 's' : ''}
                      . Next version will be <strong>{nextVersionLabel}</strong>.
                    </Typography>
                  )}
                </FormControl>
              )}
            </Box>
          </RadioGroup>

          <Divider sx={{ my: 2 }} />

          {/* ── Version metadata ── */}
          <Typography
            level="body-xs"
            textTransform="uppercase"
            fontWeight="lg"
            sx={{ mb: 1 }}
          >
            Version Details
          </Typography>

          <Stack spacing={2}>
            {/* Tag selector */}
            <FormControl>
              <FormLabel>
                <Stack direction="row" alignItems="center" gap={0.5}>
                  <TagIcon size={14} />
                  Tag
                </Stack>
              </FormLabel>
              <Select
                size="sm"
                value={tag}
                onChange={(_e, val) => {
                  if (val) setTag(val);
                }}
                renderValue={(selected) => (
                  <Chip
                    size="sm"
                    variant="soft"
                    color={TAG_COLORS[selected?.value ?? ''] || 'neutral'}
                  >
                    {selected?.label}
                  </Chip>
                )}
              >
                {TAG_OPTIONS.map((t) => (
                  <Option key={t} value={t}>
                    <Chip
                      size="sm"
                      variant="soft"
                      color={TAG_COLORS[t] || 'neutral'}
                    >
                      {t}
                    </Chip>
                  </Option>
                ))}
              </Select>
              <Typography level="body-xs" color="neutral" sx={{ mt: 0.5 }}>
                Selecting this tag will move it from any version that currently
                has it.
              </Typography>
            </FormControl>

            {/* Description */}
            <FormControl>
              <FormLabel>Description</FormLabel>
              <Textarea
                size="sm"
                minRows={2}
                maxRows={4}
                placeholder="What changed in this version?"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </FormControl>
          </Stack>
        </DialogContent>
```

- [ ] **Step 5: Update the button text to show version label**

Replace the `<DialogActions>` section with:

```tsx
        <DialogActions>
          <Button
            startDecorator={<Save size={16} />}
            onClick={handleSubmit}
            loading={saving}
            disabled={!canSave}
          >
            Publish as {nextVersionLabel}
          </Button>
          <Button
            variant="plain"
            color="neutral"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </Button>
        </DialogActions>
```

- [ ] **Step 6: Clean up unused imports**

Remove `Input` from the `@mui/joy` import if no longer used (it IS still used for group name). Remove the unused `LayersIcon` import if `Save` is sufficient. Check that all imported components are still used.

Actually `Input` is still used for the Name field. Remove only truly unused imports. The `LayersIcon` is used in the `DialogTitle`. Keep all current imports except remove the ones that are no longer referenced after removing the version name/label fields.

- [ ] **Step 7: Run formatting**

Run: `npm run format -- --write src/renderer/components/Experiment/Tasks/SaveToRegistryDialog.tsx`

- [ ] **Step 8: Commit**

```bash
git add src/renderer/components/Experiment/Tasks/SaveToRegistryDialog.tsx
git commit -m "feat: simplify publish dialog — remove version name/label inputs"
```

---

### Task 5: Update ModelsSection and DatasetsSection to remove unused params

**Files:**
- Modify: `src/renderer/components/Experiment/Tasks/JobArtifacts/ModelsSection.tsx`
- Modify: `src/renderer/components/Experiment/Tasks/JobArtifacts/DatasetsSection.tsx`

These components send `assetName` and `versionLabel` to the API. Remove those params and the 409 error handling.

- [ ] **Step 1: Update ModelsSection.tsx**

In `src/renderer/components/Experiment/Tasks/JobArtifacts/ModelsSection.tsx`:

Remove the `assetNameError` state (line 61) and `setAssetNameError` calls throughout.

Replace the `handleSaveToRegistry` function (lines 119-187) with:

```typescript
  const handleSaveToRegistry = async (
    modelName: string,
    info: SaveVersionInfo,
  ) => {
    setSavingModel(modelName);
    setSaveError(null);
    setSaveSuccess(null);

    try {
      const url = getAPIFullPath('jobs', ['saveModelToRegistry'], {
        experimentId: experimentInfo?.id,
        jobId: jobId.toString(),
        modelName,
        targetName: info.groupId || info.groupName,
        mode: info.mode,
        tag: info.tag,
        description: info.description,
      });

      const response = await fetchWithAuth(url, {
        method: 'POST',
      });

      if (!response.ok) {
        let errorMessage = 'Failed to save model to registry';
        try {
          const errorData = await response.json();
          errorMessage = errorData.detail || errorMessage;
        } catch (e) {
          errorMessage = `${response.status}: ${response.statusText}`;
        }
        throw new Error(errorMessage);
      }

      const result = await response.json();

      if (result.status === 'started' && result.task_job_id) {
        setSaveTaskJobId(String(result.task_job_id));
        setSaveDialogModel(null);
      } else {
        setSaveSuccess(
          result.message || `Successfully saved ${modelName} to registry`,
        );
        setSaveDialogModel(null);
        setSavingModel(null);
        mutate();
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : 'Unknown error occurred';
      console.error('Failed to save model:', error);
      setSaveError(errorMessage);
      setSavingModel(null);
    }
  };
```

Also update the `SaveToRegistryDialog` usage — remove the `assetNameError` prop:

```tsx
    <SaveToRegistryDialog
      open={saveDialogModel !== null}
      onClose={() => {
        setSaveDialogModel(null);
      }}
      sourceName={saveDialogModel || ''}
      type="model"
      existingNames={existingModelNames}
      saving={savingModel !== null}
      jobId={jobId ?? undefined}
      onSave={(info) => {
        if (saveDialogModel) {
          handleSaveToRegistry(saveDialogModel, info);
        }
      }}
    />
```

- [ ] **Step 2: Update DatasetsSection.tsx**

Apply the same changes to `src/renderer/components/Experiment/Tasks/JobArtifacts/DatasetsSection.tsx`:

Remove `assetNameError` state and `setAssetNameError` calls.

Replace `handleSaveToRegistry` with the same pattern (using `saveDatasetToRegistry` endpoint, `datasetName` param, etc.):

```typescript
  const handleSaveToRegistry = async (
    datasetName: string,
    info: SaveVersionInfo,
  ) => {
    setSavingDataset(datasetName);
    setSaveError(null);
    setSaveSuccess(null);

    try {
      const url = getAPIFullPath('jobs', ['saveDatasetToRegistry'], {
        experimentId: experimentInfo?.id,
        jobId: jobId.toString(),
        datasetName,
        targetName: info.groupId || info.groupName,
        mode: info.mode,
        tag: info.tag,
        description: info.description,
      });

      const response = await fetchWithAuth(url, {
        method: 'POST',
      });

      if (!response.ok) {
        let errorMessage = 'Failed to save dataset to registry';
        try {
          const errorData = await response.json();
          errorMessage = errorData.detail || errorMessage;
        } catch (e) {
          errorMessage = `${response.status}: ${response.statusText}`;
        }
        throw new Error(errorMessage);
      }

      const result = await response.json();

      if (result.status === 'started' && result.task_job_id) {
        setSaveTaskJobId(String(result.task_job_id));
        setSaveDialogDataset(null);
      } else {
        setSaveSuccess(
          result.message || `Successfully saved ${datasetName} to registry`,
        );
        setSaveDialogDataset(null);
        setSavingDataset(null);
        mutate();
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : 'Unknown error occurred';
      console.error('Failed to save dataset:', error);
      setSaveError(errorMessage);
      setSavingDataset(null);
    }
  };
```

Remove `assetNameError` prop from the `SaveToRegistryDialog` usage.

- [ ] **Step 3: Run formatting**

Run: `npm run format`

- [ ] **Step 4: Commit**

```bash
git add src/renderer/components/Experiment/Tasks/JobArtifacts/ModelsSection.tsx src/renderer/components/Experiment/Tasks/JobArtifacts/DatasetsSection.tsx
git commit -m "feat: remove assetName/versionLabel from save-to-registry calls"
```

---

### Task 6: Update API endpoint URL definitions

**Files:**
- Modify: `src/renderer/lib/api-client/allEndpoints.json:193-200`

Remove `asset_name` and `version_label` query parameters from the URL templates.

- [ ] **Step 1: Update endpoint URLs**

In `src/renderer/lib/api-client/allEndpoints.json`, replace the two endpoint entries:

Replace:
```json
    "saveDatasetToRegistry": {
      "method": "POST",
      "path": "experiment/{experimentId}/jobs/{jobId}/datasets/{datasetName}/save_to_registry?target_name={targetName}&asset_name={assetName}&mode={mode}&tag={tag}&version_label={versionLabel}&description={description}"
    },
    "saveModelToRegistry": {
      "method": "POST",
      "path": "experiment/{experimentId}/jobs/{jobId}/models/{modelName}/save_to_registry?target_name={targetName}&asset_name={assetName}&mode={mode}&tag={tag}&version_label={versionLabel}&description={description}"
    },
```

With:
```json
    "saveDatasetToRegistry": {
      "method": "POST",
      "path": "experiment/{experimentId}/jobs/{jobId}/datasets/{datasetName}/save_to_registry?target_name={targetName}&mode={mode}&tag={tag}&description={description}"
    },
    "saveModelToRegistry": {
      "method": "POST",
      "path": "experiment/{experimentId}/jobs/{jobId}/models/{modelName}/save_to_registry?target_name={targetName}&mode={mode}&tag={tag}&description={description}"
    },
```

- [ ] **Step 2: Commit**

```bash
git add src/renderer/lib/api-client/allEndpoints.json
git commit -m "feat: remove assetName/versionLabel from API endpoint URLs"
```

---

### Task 7: Update tests

**Files:**
- Modify: `api/test/api/test_job_save_to_registry.py`

Update existing tests to verify the new hierarchical storage behavior. Tests that passed `asset_name` or `version_label` params need updating. Add new tests for `vN` auto-increment.

- [ ] **Step 1: Rewrite the test file**

Replace the entire contents of `api/test/api/test_job_save_to_registry.py` with:

```python
import pytest

import lab.dirs as lab_dirs


@pytest.fixture()
def tmp_workspace(monkeypatch, tmp_path):
    """Point workspace dirs to a temporary directory for isolation."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    jobs_dir = workspace / "jobs"
    jobs_dir.mkdir()
    datasets_dir = workspace / "datasets"
    datasets_dir.mkdir()
    models_dir = workspace / "models"
    models_dir.mkdir()

    async def mock_get_workspace_dir():
        return str(workspace)

    async def mock_get_jobs_dir(experiment_id: str):
        return str(jobs_dir)

    async def mock_get_datasets_dir():
        return str(datasets_dir)

    async def mock_get_models_dir():
        return str(models_dir)

    monkeypatch.setattr(lab_dirs, "get_workspace_dir", mock_get_workspace_dir)
    monkeypatch.setattr(lab_dirs, "get_jobs_dir", mock_get_jobs_dir)
    monkeypatch.setattr(lab_dirs, "get_datasets_dir", mock_get_datasets_dir)
    monkeypatch.setattr(lab_dirs, "get_models_dir", mock_get_models_dir)

    return {
        "workspace": workspace,
        "jobs_dir": jobs_dir,
        "datasets_dir": datasets_dir,
        "models_dir": models_dir,
    }


def _seed_job_dataset(tmp_workspace, job_id: str, dataset_name: str, content: str = '{"text":"hello"}'):
    """Create a dataset directory inside a job's datasets folder with a sample file."""
    dataset_dir = tmp_workspace["jobs_dir"] / job_id / "datasets" / dataset_name
    dataset_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "data.jsonl").write_text(content)
    return dataset_dir


def _seed_job_model(tmp_workspace, job_id: str, model_name: str, content: str = "fake-model-weights"):
    """Create a model directory inside a job's models folder with a sample file."""
    model_dir = tmp_workspace["jobs_dir"] / job_id / "models" / model_name
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.safetensors").write_text(content)
    return model_dir


# ---------------------------------------------------------------------------
# Dataset listing
# ---------------------------------------------------------------------------


def test_list_job_datasets_returns_dataset(client, tmp_workspace):
    """After seeding a dataset in a job dir, the list endpoint returns it."""
    job_id = "42"
    _seed_job_dataset(tmp_workspace, job_id, "my-dataset")

    resp = client.get(f"/experiment/alpha/jobs/{job_id}/datasets")
    assert resp.status_code == 200

    data = resp.json()
    assert "datasets" in data
    names = [d["name"] for d in data["datasets"]]
    assert "my-dataset" in names


def test_list_job_datasets_empty_when_no_datasets(client, tmp_workspace):
    """When the job has no datasets directory the endpoint returns an empty list."""
    resp = client.get("/experiment/alpha/jobs/99/datasets")
    assert resp.status_code == 200
    assert resp.json()["datasets"] == []


# ---------------------------------------------------------------------------
# Save dataset to registry — hierarchical storage
# ---------------------------------------------------------------------------


def test_save_dataset_to_registry_starts(client, tmp_workspace):
    """Saving a dataset triggers the background copy."""
    job_id = "42"
    dataset_name = "my-dataset"
    _seed_job_dataset(tmp_workspace, job_id, dataset_name, content='{"row":1}')

    resp = client.post(
        f"/experiment/alpha/jobs/{job_id}/datasets/{dataset_name}/save_to_registry",
        params={"target_name": "my-group", "mode": "new"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"


def test_save_nonexistent_dataset_returns_404(client, tmp_workspace):
    """Saving a dataset that doesn't exist in the job returns 404."""
    job_id = "42"
    (tmp_workspace["jobs_dir"] / job_id / "datasets").mkdir(parents=True, exist_ok=True)

    resp = client.post(f"/experiment/alpha/jobs/{job_id}/datasets/ghost-dataset/save_to_registry")
    assert resp.status_code == 404


def test_save_dataset_to_existing_requires_target_name(client, tmp_workspace):
    """mode='existing' without target_name returns 400."""
    job_id = "42"
    _seed_job_dataset(tmp_workspace, job_id, "my-dataset")

    resp = client.post(
        f"/experiment/alpha/jobs/{job_id}/datasets/my-dataset/save_to_registry",
        params={"mode": "existing"},
    )
    assert resp.status_code == 400


def test_save_dataset_to_nonexistent_existing_returns_404(client, tmp_workspace):
    """mode='existing' with a target that doesn't exist returns 404."""
    job_id = "42"
    _seed_job_dataset(tmp_workspace, job_id, "my-dataset")

    resp = client.post(
        f"/experiment/alpha/jobs/{job_id}/datasets/my-dataset/save_to_registry",
        params={"target_name": "nonexistent", "mode": "existing"},
    )
    assert resp.status_code == 404


def test_save_dataset_rejects_group_name_collision_with_flat(client, tmp_workspace):
    """mode='new' returns 409 if group name collides with a flat dataset that has index.json."""
    job_id = "42"
    _seed_job_dataset(tmp_workspace, job_id, "my-dataset")

    # Pre-create a flat dataset with index.json
    flat = tmp_workspace["datasets_dir"] / "my-group"
    flat.mkdir()
    (flat / "index.json").write_text("{}")

    resp = client.post(
        f"/experiment/alpha/jobs/{job_id}/datasets/my-dataset/save_to_registry",
        params={"target_name": "my-group", "mode": "new"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Model listing
# ---------------------------------------------------------------------------


def test_list_job_models_returns_model(client, tmp_workspace):
    """After seeding a model in a job dir, the list endpoint returns it."""
    job_id = "42"
    _seed_job_model(tmp_workspace, job_id, "my-model")

    resp = client.get(f"/experiment/alpha/jobs/{job_id}/models")
    assert resp.status_code == 200

    data = resp.json()
    assert "models" in data
    names = [m["name"] for m in data["models"]]
    assert "my-model" in names


def test_list_job_models_empty_when_no_models(client, tmp_workspace):
    """When the job has no models directory the endpoint returns an empty list."""
    resp = client.get("/experiment/alpha/jobs/99/models")
    assert resp.status_code == 200
    assert resp.json()["models"] == []


# ---------------------------------------------------------------------------
# Save model to registry — hierarchical storage
# ---------------------------------------------------------------------------


def test_save_model_to_registry_starts(client, tmp_workspace):
    """Saving a model triggers the background copy."""
    job_id = "42"
    model_name = "my-model"
    _seed_job_model(tmp_workspace, job_id, model_name, content="weights-v1")

    resp = client.post(
        f"/experiment/alpha/jobs/{job_id}/models/{model_name}/save_to_registry",
        params={"target_name": "my-group", "mode": "new"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"


def test_save_nonexistent_model_returns_404(client, tmp_workspace):
    """Saving a model that doesn't exist in the job returns 404."""
    job_id = "42"
    (tmp_workspace["jobs_dir"] / job_id / "models").mkdir(parents=True, exist_ok=True)

    resp = client.post(f"/experiment/alpha/jobs/{job_id}/models/ghost-model/save_to_registry")
    assert resp.status_code == 404


def test_save_model_to_existing_requires_target_name(client, tmp_workspace):
    """mode='existing' without target_name returns 400."""
    job_id = "42"
    _seed_job_model(tmp_workspace, job_id, "my-model")

    resp = client.post(
        f"/experiment/alpha/jobs/{job_id}/models/my-model/save_to_registry",
        params={"mode": "existing"},
    )
    assert resp.status_code == 400


def test_save_model_to_nonexistent_existing_returns_404(client, tmp_workspace):
    """mode='existing' with a target that doesn't exist returns 404."""
    job_id = "42"
    _seed_job_model(tmp_workspace, job_id, "my-model")

    resp = client.post(
        f"/experiment/alpha/jobs/{job_id}/models/my-model/save_to_registry",
        params={"target_name": "nonexistent", "mode": "existing"},
    )
    assert resp.status_code == 404


def test_save_model_rejects_group_name_collision_with_flat(client, tmp_workspace):
    """mode='new' returns 409 if group name collides with a flat model that has index.json."""
    job_id = "42"
    _seed_job_model(tmp_workspace, job_id, "my-model")

    # Pre-create a flat model with index.json (simulating a downloaded base model)
    flat = tmp_workspace["models_dir"] / "my-group"
    flat.mkdir()
    (flat / "index.json").write_text("{}")

    resp = client.post(
        f"/experiment/alpha/jobs/{job_id}/models/my-model/save_to_registry",
        params={"target_name": "my-group", "mode": "new"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# End-to-end: both artifacts
# ---------------------------------------------------------------------------


def test_save_dataset_and_model_from_same_job(client, tmp_workspace):
    """A job with both a dataset and model can trigger saves to the registry."""
    job_id = "100"

    _seed_job_dataset(tmp_workspace, job_id, "gen-ds", content='{"prompt":"hi"}')
    _seed_job_model(tmp_workspace, job_id, "ft-model", content="trained-weights")

    ds_save = client.post(
        f"/experiment/alpha/jobs/{job_id}/datasets/gen-ds/save_to_registry",
        params={"target_name": "my-ds-group", "mode": "new"},
    )
    assert ds_save.status_code == 200
    assert ds_save.json()["status"] == "started"

    model_save = client.post(
        f"/experiment/alpha/jobs/{job_id}/models/ft-model/save_to_registry",
        params={"target_name": "my-model-group", "mode": "new"},
    )
    assert model_save.status_code == 200
    assert model_save.json()["status"] == "started"
```

- [ ] **Step 2: Run the tests**

Run: `cd api && pytest test/api/test_job_save_to_registry.py -v`

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add api/test/api/test_job_save_to_registry.py
git commit -m "test: update save-to-registry tests for hierarchical storage"
```

---

### Task 8: Run full test suite and lint

**Files:** None (verification only)

- [ ] **Step 1: Run backend tests**

Run: `cd api && pytest test/ -v`

Expected: All tests pass.

- [ ] **Step 2: Run backend linting**

Run: `cd api && ruff check && ruff format --check`

Expected: No errors.

- [ ] **Step 3: Run frontend formatting**

Run: `npm run format`

- [ ] **Step 4: Run frontend tests**

Run: `npm test`

Expected: All tests pass.

- [ ] **Step 5: Commit any formatting fixes**

If formatting produced changes:
```bash
git add -A && git commit -m "style: formatting fixes"
```
