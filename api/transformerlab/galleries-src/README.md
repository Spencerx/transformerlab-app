## API Gallery Sources (Subset)

This directory is the editable source of truth for API-managed galleries:

- `tasks/`
- `interactive/`
- `announcements/`

Do not edit generated files in `transformerlab/galleries/` directly.

To regenerate:

`python api/scripts/combine_subset_galleries.py`

To generate a channel bundle (for stable/beta distribution metadata):

`python api/scripts/combine_subset_galleries.py --emit-bundle-dir api/transformerlab/galleries/channels/stable/latest --channel stable --min-supported-app-version 0.0.0`
