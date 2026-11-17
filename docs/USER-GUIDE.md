# BM Stadium DAE Exporter User Guide

This guide covers installation, scene review, validation, export, every user-facing
setting, and the most common errors in BM Stadium DAE Exporter v1.1.2.

## Requirements

- Blender 5.2.x; the current release was verified with Blender 5.2.3.
- A saved Blender scene in Object Mode.
- A destination in a BeamNG `/levels/`, `/vehicles/`, or `/art/` content tree, or
  a valid virtual path entered in **Game Texture Directory**.
- Enough free memory and storage for baked venue textures.

## Install or Update

1. Download `bm_stadium_dae_v1.1.2_Blender_5.2.zip` from the repository's
   **GitHub Releases** page.
2. In Blender, open **Edit → Preferences → Add-ons**.
3. Open the Add-ons menu and select **Install from Disk…**.
4. Select the ZIP without extracting it.
5. Enable **BM Stadium DAE Exporter**.
6. Close Preferences.

To update, install the newer versioned ZIP the same way. Confirm that only the
intended version is enabled, then restart Blender before an important production
export.

## The Stadium Sidebar

Press `N` while the mouse is over the 3D View and open the **Stadium** tab.

The panel contains four actions:

1. **Check Stadium Visibility** classifies the venue meshes without changing the
   scene. It creates or refreshes a Blender text block named
   `Stadium Export Visibility`.
2. **Validate Full Export…** performs a non-writing preflight using the intended
   output path and export settings.
3. **Export Stadium…** writes the complete DAE and material package.
4. **Copy Last Error** copies the complete failure, versions and settings after
   an export or validation error. It sends nothing automatically. The copied text
   includes local paths, so redact personal details before posting publicly.

The real export is also available at **File → Export → BeamNG Stadium (.dae)**.

## Step 1: Review Visibility

Choose **Check Stadium Visibility** before validation. Open Blender's Text Editor
and select `Stadium Export Visibility` to inspect every decision.

The exporter normally includes:

- visible mesh objects;
- evaluated modifier results;
- placed instances and generated seat geometry; and
- eye/H-hidden objects carrying a real stadium placement ID when
  **Include Eye-hidden Placed Geometry** is enabled.

It does not silently enable:

- source prototypes and spare templates without real placement IDs;
- engine light blockers;
- render-disabled objects;
- viewport-disabled objects; or
- objects inside excluded or disabled collections.

Fix unexpected scene flags or placement metadata before continuing. The exporter
does not modify the scene to force an object into the package.

## Step 2: Validate the Planned Export

Choose **Validate Full Export…** and select the exact destination intended for the
real DAE. Configure all options exactly as they will be used for export.

Validation checks:

- visibility classification;
- evaluated meshes, modifiers, and instances;
- material-node support;
- source image existence and decoding;
- UV and color-attribute requirements;
- projection and object-atlas requirements;
- glass and sheen approximation choices; and
- the BeamNG virtual texture destination.

Validation does not create export files or bake textures. A pass means the static
scene is compatible with the export pipeline; it does not certify final in-game
appearance.

## Step 3: Export

Choose **Export Stadium…**, select the `.dae` destination, confirm the options,
and start the export. Large venues may take substantial time. Do not close Blender
or change the scene until Blender reports that the export completed.

The exporter remembers the last destination in the scene. A successful export
creates a DAE, material definitions, material and visibility reports, a geometry
export report, and a content-addressed texture folder. Keep the complete set together.

The DAE uses unique names with a common static detail suffix under `base00/start01`.
Blender object names and placements remain unchanged. This does not create collision
meshes or an optimized multi-LOD asset.

## Complete Option Reference

### Include Eye-hidden Placed Geometry

- **Type:** Checkbox
- **Default:** Enabled
- **Purpose:** Includes placed venue geometry hidden with Blender's eye icon or
  `H` command when it carries a real placement ID.
- **Still excluded:** Prototypes, light blockers, render-disabled objects,
  viewport-disabled objects, and disabled collections.
- **Use it when:** A completed package intentionally keeps placed seating or venue
  sections hidden in the working viewport.
- **Disable it when:** The export should contain only currently visible placements.

Always review **Check Stadium Visibility** after changing this option.

### Texture Resolution

- **Type:** Dropdown: 512, 1024, 2048, or 4096 pixels
- **Default:** 2048
- **Purpose:** Sets the dimensions of each baked texture.
- **512:** Fast review exports and distant, low-detail surfaces.
- **1024:** Lightweight packages and secondary venue elements.
- **2048:** Recommended general-purpose balance.
- **4096:** Detail-critical surfaces when memory, time, and package size permit.

This applies per baked texture, so increasing the value can multiply total cost
across a material-heavy venue.

### Transparency

- **Type:** Dropdown: Blended or Cutout
- **Default:** Blended
- **Blended:** Preserves smooth or partial alpha for glass-like fades and soft
  transparency.
- **Cutout:** Uses an alpha test for hard boundaries such as chain-link fencing,
  foliage, perforated signs, and similar materials.

Choose the mode that matches the majority of transparent surfaces in the export,
then verify the result in BeamNG.

### Game Texture Directory

- **Type:** Text field
- **Default:** Blank
- **Purpose:** Defines the BeamNG virtual path stored in material references.
- **Recommended:** Leave blank when the output already sits inside a recognizable
  `levels`, `vehicles`, or `art` tree; the exporter infers the path.
- **Manual examples:** `/levels/my_level/art/stadium` or `/art/shapes/stadium`.

Do not enter a Windows path such as `D:\Games\...`. The value must start with
`/levels/`, `/vehicles/`, or `/art/`, and it cannot contain `..` traversal.

### Scale

- **Type:** Number
- **Default:** 1.0
- **Purpose:** Multiplies exported geometry dimensions.
- **Recommended:** Keep 1.0 when the prepared Blender scene already uses the
  intended game scale.

Use a different value only after confirming the scene-to-game unit conversion.
Scaling can affect placement and should be verified in BeamNG.

### Approximate Glass

- **Type:** Checkbox
- **Default:** Enabled
- **Purpose:** Converts unsupported glass refraction to an opacity-based BeamNG
  approximation.
- **Disabled behavior:** Unsupported glass fails validation instead of being
  silently altered.
- **Enabled behavior:** **Glass Opacity** becomes available and the approximation
  is recorded in the material report.

Keep it checked for stadium previews when an opacity approximation is acceptable.
It does not recreate physical refraction. Old saved presets may retain the previous
off setting; check this box after an update if transmission materials are rejected.

### Glass Opacity

- **Type:** Number from 0 to 1
- **Default:** 0.15
- **Visible when:** **Approximate Glass** is enabled
- **Purpose:** Sets the opacity of approximated glass. `0` is invisible and `1`
  is fully opaque.

Start with 0.15 and adjust only after an in-game review.

### Approximate Sheen

- **Type:** Checkbox
- **Default:** Enabled
- **Purpose:** Preserves the base PBR color and roughness of cloth-like materials
  while recording that BeamNG has no separate Blender sheen lobe.
- **Disable it when:** You want validation to reject any material that requires the
  supported constant-sheen approximation.

Linked or texture-driven sheen graphs remain unsupported and fail safely.

### Nits per Emission Strength

- **Type:** Positive number
- **Default:** 100
- **Purpose:** Converts Blender emission strength to BeamNG brightness for lighted
  signs, scoreboards, ribbons, and similar materials.

Raise or lower the value only after comparing emissive surfaces in BeamNG under the
level's actual lighting and exposure.

## Output Package

An export named `MyVenue.dae` writes:

```text
MyVenue.dae                    Geometry and material assignments
MyVenue.materials.json         BeamNG material definitions
MyVenue.material-report.json   Material mappings, textures, and approximations
MyVenue.visibility.json        Selected versus actually exported object audit
MyVenue.export-report.json     Source-to-static-part names and evaluated omissions
bmtex_<package-id>/            Content-addressed PNG authoring textures
```

The generated material paths use the BeamNG virtual file system, never an absolute
Windows drive path. Let BeamNG cook authoring PNGs to DDS before distributing a
final mod.

## Common Validation Errors

Use **Stadium → Copy Last Error** for the complete error rather than a truncated
notification. Diagnostics are kept in memory and are not saved into the venue.

### Transmission Weight: enable Approximate Glass

Check **Approximate Glass** in both Validate and Export. It defaults on in 1.1.2.
Saved older presets can override that default. This uses opacity, not refraction.

### Required stadium objects evaluated empty

Inspect the named object's modifiers, Geometry Nodes and instance sources. The
export stops before replacing files if a required object unexpectedly has no
geometry. Verified seat masks that intentionally hide every point are reported
as empty without fabricating seats.

### Export inside a levels/vehicles/art folder, or set Game Texture Directory

The destination is outside a path the exporter can translate to BeamNG's virtual
file system. Move the destination into the mod's content tree or enter a valid
virtual path manually.

### Texture file is missing or could not be decoded

Reconnect, unpack, or replace the source image in Blender. Save the scene and run
validation again.

### Textured faces have no UV coordinates

Create a valid UV map for the affected mesh or correct the material's intended UV
source.

### Used texture UV must be exported as UV0

Make the intended texture UV the active/exported first UV map, or repair the
material/mesh UV assignment.

### Unsupported glass, sheen, or coat graph

Simplify the graph to supported values, use the documented approximation when one
is available, or replace the material. The exporter fails before replacing an
existing verified package.

### Disabled placed meshes excluded

Review the visibility text block. Re-enable only the objects and collections that
are genuinely part of the final venue; do not indiscriminately unhide prototypes
or light blockers.

## In-game Review Checklist

After every production export, check:

- venue position, orientation, and scale;
- missing or duplicated geometry;
- seating and repeated-instance coverage;
- material and texture assignments;
- transparent fences, signs, and glass;
- emissive scoreboards and lighted surfaces;
- collision and any game-specific integration performed outside this exporter;
- frame rate, draw calls, memory use, and texture size; and
- BeamNG logs for missing assets or material warnings.

Static validation cannot replace this live review.

## Getting Help

Open a GitHub Issue with the Blender version, exporter version, option values,
exact error, and the smallest legally shareable reproduction. Attach the generated
material or visibility report when relevant.

Never post copyrighted venue assets, proprietary game files, credentials, or
personal data in a public issue.
