# Preview image task panel design

## Status and decision

**Status:** approved for specification; implementation requires a separate plan.

Preview edit mode will provide one right-side **image task panel** with two
entry points:

1. **Edit source image** — make one or more annotated regions on the current
   image and describe the desired change for each region.
2. **Create from file or description** — use a project image, Markdown, HTML,
   or a text description as a reference for a new design asset.

Both entry points create the same controlled generated-asset task. They must not
be implemented as separate backends or separate asset stores.

## Goals

- Support complete-image generation and image-to-image editing from Preview.
- Produce useful design assets for the primary workflows: wireframes, interface
  illustrations, visual-effect drafts, presentation graphics, and file-derived
  images.
- Let users express several local changes in one coherent output image.
- Preserve task inputs, generation provenance, candidate assets, and adoption
  history without overwriting source material.
- Keep all filesystem access and output locations constrained to the active
  ClawMate project.

## Non-goals for the first release

- Office/PDF as direct visual-reference sources.
- A standalone full-screen professional image editor, layers, or arbitrary
  image-compositing tools.
- Automatic adoption, automatic document insertion, or overwriting any source
  image.
- Support for external paths, uploads outside the project, or model-provider
  credential management in the panel.

## Experience and layout

The panel is opened from Preview edit mode. It is a normal right-side,
push-layout panel and is mutually exclusive with the feedback, Agent, and
project panels. It uses the shared close button and 40px panel-header contract.

### Entry points

**Edit source image** preselects the image currently displayed in Preview. Its
main interaction is an annotation canvas plus a list of local instructions.

**Create from file or description** accepts a project image, Markdown, or HTML
reference, or text alone. Markdown and HTML are converted from their current
Preview rendering into a reference image before task submission. The source
file path and the rendered-reference snapshot are recorded with the task.

Both paths end in a common task summary before submission:

- source and source version/snapshot;
- artifact type and visual style;
- target use-case and its proposed canvas settings;
- optional overall improvement requirements;
- enabled local instructions, where applicable;
- candidate count and output-location choice.

### Creation controls

Creation intent is deliberately two-dimensional:

- **Artifact type:** wireframe, interface illustration, visual-effect draft,
  presentation graphic, file-derived image, or requirement illustration.
- **Visual style:** low-fidelity wireframe, conceptual UI, product visual,
  comic, sketch, realistic, or another controlled style preset.

The user also selects a use-case: phone, computer, vehicle cockpit, television,
or general. Each preset supplies recommended dimensions, aspect ratio,
readable-distance density, and safe-area guidance. The user may override the
size and add a written constraint; the requested result records both the preset
and overrides.

### Region annotations

An image-edit task can contain multiple enabled regions. Each region contains:

- a stable identifier and user-visible name;
- a rectangular or brush mask;
- one action: remove background, recolor, complete, replace locally, overlay
  risk zone, overlay functional zone, or overlay interaction instruction;
- a required local description when the selected action needs a target;
- an enabled state and explicit order.

All enabled regions are compiled into **one** generation request, which returns
the requested number of complete-image candidates. Overlapping regions are
allowed, but the panel warns about them and uses the explicit order as the
resolution order. A task with no region is valid only when it has an overall
improvement requirement, enabling whole-image revision.

### Results

Candidates display as a gallery, showing task version, generation time, result
summary, and origin. The available user actions are:

- preview the candidate;
- adopt it as a controlled project asset;
- use it as the source of a new task;
- create a variation from the same configuration;
- download it;
- insert it into the current document only through an explicit, later-supported
  document action.

Using a candidate as a next source never edits its parent candidate or original
source.

## Task contract and storage

Extend the existing generated-asset task contract rather than creating another
task service. In addition to existing source, prompt, purpose, topic,
dimensions, candidate-count, backend, and operator fields, a task version
records:

```json
{
  "mode": "edit_source_image | create_from_reference",
  "artifact_type": "wireframe",
  "visual_style": "low_fidelity_wireframe",
  "use_case": "vehicle_cockpit",
  "use_case_overrides": {
    "width": 1920,
    "height": 720,
    "constraints": "maintain safe areas for cockpit controls"
  },
  "overall_requirements": "retain the warning hierarchy",
  "reference": {
    "source_kind": "image | markdown | html | text",
    "source_path": "relative/project/path",
    "snapshot_path": "relative/project/path"
  },
  "regions": [
    {
      "id": "region_01",
      "name": "warning zone",
      "mask_path": ".clawmate/generated-tasks/<task>/masks/region_01.png",
      "action": "overlay_risk_zone",
      "description": "show the collision-risk envelope in amber",
      "enabled": true,
      "order": 1
    }
  ],
  "parent_task_id": "",
  "parent_candidate_id": ""
}
```

The server owns all paths. A reference snapshot and masks are saved under the
task metadata directory; agents receive only the original/reference path,
approved masks, candidate directory, and metadata directory. Candidate files
remain isolated until the user adopts one. Adoption uses the existing controlled
asset location and appends the full task lineage to its manifest.

Each edit creates a new task version. Existing request metadata, candidates,
and adopted files are immutable.

## Validation and state model

Before dispatch:

- edit mode requires a valid in-project source image and either an enabled
  region or an overall requirement;
- create mode requires a text description or valid image/Markdown/HTML source;
- every enabled region has a valid mask and action; replacement requires a
  target description;
- dimensions must remain within the existing service bounds;
- candidate count defaults to 1 and is limited to 4;
- output selection may resolve only to the project-controlled destination or an
  explicitly permitted source-directory destination inside the project;
- paths are resolved server-side and rejected if they escape the project.

Task states are `draft`, `validating`, `queued`, `generating`, `completed`,
`partially_completed`, `failed`, and `cancelled`. Failed and partially completed
tasks retain their inputs and valid candidates. The UI presents a failure reason
and offers retry from the retained configuration. An unavailable backend is
reported plainly and never represented as a successful empty result.

## Compilation and execution

A task compiler produces a human-readable generation instruction containing
source/reference facts, artifact type, style, use-case constraints, overall
requirements, and ordered local instructions. The executor uses that compiled
instruction and may only create candidates and the prescribed result metadata.
It may not overwrite the source, move candidates into permanent assets, or
access paths outside the dispatch allowance.

Old simple requests (source image, prompt, purpose, topic, dimensions, and
candidate count) remain readable and dispatchable. They map to an edit task
with no regions and an overall text requirement. New fields are optional in the
transport contract but are normalized before dispatch.

## Accessibility and responsive behavior

- Canvas operations have a keyboard alternative through the region list:
  select, rename, change action, edit description, enable/disable, delete, and
  reorder.
- Status, validation, selection, and task progress use text in addition to
  color. Candidate images have editable alternative descriptions.
- At narrow widths, the panel presents source preview, region list, and a
  full-screen annotation sheet rather than a dense split canvas. A user can
  always complete a full-image text-only task without using the canvas.

## Security, provenance, and operational rules

- Do not store credentials, tokens, or raw provider secrets in task metadata,
  logs, prompts, or manifests.
- Preserve source path/snapshot, compiled request, masks, state transitions,
  candidate identifiers, and adoption lineage for every task version.
- Do not conflate a successful HTTP dispatch or mock executor response with a
  verified real-image result. Provider-backed validation is a separate
  acceptance layer.

## Acceptance evidence

1. **Unit and contract tests:** schema normalization, path boundaries, source
   adaptation, mask/region validation, compilation order, version lineage,
   candidate limits, old-request compatibility, and manifest provenance.
2. **Route tests:** task creation, task lookup, dispatch failure, partial
   result, retry, adoption, and forbidden-path behavior.
3. **Browser tests:** entry-mode switching, multiple regions, overlap warning,
   keyboard alternatives, task progress/failure/completion, gallery actions,
   panel mutual exclusion, and mobile fallback.
4. **Real-provider acceptance:** on a configured image backend, separately
   verify an image-local edit, Markdown reference generation, HTML reference
   generation, and representative use-case presets. Capture browser behavior,
   network results, and console evidence; do not substitute fixture tests for
   this layer.

## Implementation sequencing

1. Define and test the extended task schema, metadata migration/normalization,
   path rules, and compiler.
2. Extend the generated-asset routes and executor instruction while preserving
   the existing simple contract.
3. Build the shared panel state and create-from-reference path.
4. Add the image annotation canvas and region-mask storage.
5. Add gallery lineage actions, accessibility alternatives, and responsive
   annotation fallback.
6. Run the four acceptance layers, including real-provider validation only when
   an approved configured backend is available.
