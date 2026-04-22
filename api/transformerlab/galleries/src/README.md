# API Gallery Sources (Subset)

This directory is the editable source of truth for API-managed galleries.

It replaces the old dependency on the external `galleries` repository for the
gallery types that the API actively consumes at runtime.

## What lives here

The API currently manages only these gallery domains:

- `tasks/`
- `interactive/`
- `announcements/`

These folders contain source JSON files (one file per contribution or grouped
entries). The combine script merges these files into channel bundles.


## What does not live here

The API no longer keeps legacy root gallery JSON files under:

- `api/transformerlab/galleries/*.json`

Only channel bundles are used now:

- `api/transformerlab/galleries/channels/<channel>/latest/`

## Channel model

Supported channels:

- `stable` - backward-compatible updates meant to be safe for older builds
- `beta` - newer or potentially incompatible updates for newer builds/testing

Each channel bundle contains:

- `task-gallery.json`
- `interactive-gallery.json`
- `announcement-gallery.json`
- `manifest.json`

The manifest carries:

- `bundle_version`
- `channel`
- `released_at`
- `files` entry counts
- `min_supported_app_version` (required in practice)
- `max_supported_app_version` (optional)

## Runtime loading behavior (API)

The loader behavior in `transformerlab/shared/galleries.py` is:

1. If `TLAB_USE_LOCAL_GALLERIES=1`:
   - For task/interactive/announcement galleries, load from local channel path:
     - `api/transformerlab/galleries/channels/<TLAB_GALLERY_CHANNEL>/latest/<file>`
   - If that file is missing, fallback to cache behavior.
2. If `TLAB_USE_LOCAL_GALLERIES` is not enabled:
   - Attempt remote channel bundle first (`stable` by default or `TLAB_GALLERY_CHANNEL`)
   - Check app-version compatibility from manifest
   - Keep current cache/local bundle if channel/manifest is unavailable or incompatible

Environment variables:

- `TLAB_USE_LOCAL_GALLERIES=1` to force local bundle usage
- `TLAB_GALLERY_CHANNEL=stable|beta` to select channel
- `TLAB_APP_VERSION=<version>` (optional override for compatibility check)
- `TLAB_CHANNEL_GALLERIES_BASE_URL=<url>` (optional remote channel base URL)

## Developer workflow

### 1. Edit source gallery files

Change files under:

- `api/transformerlab/galleries/src/tasks/`
- `api/transformerlab/galleries/src/interactive/`
- `api/transformerlab/galleries/src/announcements/`

### 2. Regenerate a local channel bundle

Default command (writes to local `stable/latest`):

`python api/transformerlab/galleries/combine_subset_galleries.py --channel stable --min-supported-app-version 0.0.0`

Another equivalent stable example:

`python api/transformerlab/galleries/combine_subset_galleries.py --min-supported-app-version 0.0.0`

For beta, just set channel and output will go to `channels/beta/latest`:

`python api/transformerlab/galleries/combine_subset_galleries.py --channel beta --min-supported-app-version 0.28.0`

### 3. Regenerate a specific channel explicitly

Stable:

`python api/transformerlab/galleries/combine_subset_galleries.py --channel stable --min-supported-app-version 0.0.0`

Beta:

`python api/transformerlab/galleries/combine_subset_galleries.py --channel beta --min-supported-app-version 0.28.0`

With max version bound:

`python api/transformerlab/galleries/combine_subset_galleries.py --channel beta --min-supported-app-version 0.28.0 --max-supported-app-version 0.29.99`

## CI enforcement

The workflow `gallery-channel-bundles.yml` enforces this rule:

- If `galleries/src` changed, the same PR/push must include bundle updates in
  either:
  - `api/transformerlab/galleries/channels/stable/latest/*`
  - `api/transformerlab/galleries/channels/beta/latest/*`

If no bundle update is committed, CI fails.

This is intentionally manual: CI checks correctness, but does not auto-publish.

## How to choose stable vs beta

Use `stable` when:

- Changes are backward compatible for older released builds
- You want immediate rollout to existing deployments that follow stable

Use `beta` when:

- Changes assume newer app behavior
- Schema or behavior could break old builds
- You want staged rollout before promoting to stable

## Safety and compatibility notes

- Do not edit `manifest.json` manually; generate it via script arguments.
- Keep `min_supported_app_version` accurate. This is the primary gate that
  protects older builds from incompatible bundles.
- The combine script checks duplicate `id`/`uniqueID` per gallery domain.
- If you switch channel (`stable`/`beta`) locally, ensure corresponding bundle
  files exist under that channel path.

## Quick examples

Use local stable bundle:

`TLAB_USE_LOCAL_GALLERIES=1 TLAB_GALLERY_CHANNEL=stable`

Use local beta bundle:

`TLAB_USE_LOCAL_GALLERIES=1 TLAB_GALLERY_CHANNEL=beta`

Use remote beta channel (non-local mode, pulled from main of the repo):

`TLAB_GALLERY_CHANNEL=beta`
