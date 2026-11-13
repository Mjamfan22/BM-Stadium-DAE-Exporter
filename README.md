# BM Stadium DAE Exporter

**A Blender 5.2 exporter for organized BeamNG stadium, arena, and venue packages.**

[![Blender 5.2](https://img.shields.io/badge/Blender-5.2.x-F5792A?logo=blender&logoColor=white)](https://www.blender.org/)
[![Version 1.1.0](https://img.shields.io/badge/version-1.1.0-2ea44f)](CHANGELOG.md)
[![License GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE.txt)

BM Stadium DAE Exporter packages large, static venue scenes as BeamNG-ready
COLLADA exports. One export writes the `.dae`, BeamNG `.materials.json`, baked
textures, a material report, and a visibility report while leaving the original
Blender scene unchanged.

Current release: **v1.1.0**, verified with **Blender 5.2.3**.

## Highlights

- Exports evaluated modifiers, placed instances, UVs, vertex colors, and materials.
- Bakes Blender PBR materials into organized, content-addressed texture folders.
- Creates BeamNG material definitions with transparency, emission, and clearcoat.
- Includes a non-writing full-export validator for large scenes.
- Reports exactly which placed meshes are included or excluded.
- Preserves the source scene; temporary UVs and baking data are export-only.
- Has representative validation coverage from Madden NFL 27, College Football 27,
  and NBA 2K27 venue packages.

## Download

### [Download BM Stadium DAE Exporter v1.1.0 for Blender 5.2](releases/bm_stadium_dae_v1.1.0_Blender_5.2.zip)

SHA-256:
`A14A82B1D94B1A0C6E4655D6649DC075FBF39579858A6EC580713DBEA810463D`

Do not extract the ZIP before installing it in Blender.

## Installation

1. Download the versioned ZIP above.
2. Open **Blender 5.2.x**.
3. Open **Edit → Preferences → Add-ons**.
4. Open the Add-ons menu and choose **Install from Disk…**.
5. Select `bm_stadium_dae_v1.1.0_Blender_5.2.zip`.
6. Enable **BM Stadium DAE Exporter**.
7. Confirm that **Stadium** appears in the 3D View sidebar (`N` key).

The exporter is also available through **File → Export → BeamNG Stadium (.dae)**.

## Recommended First Export

1. Save the `.blend` file and switch to **Object Mode**.
2. Open **3D View → Stadium → Check Stadium Visibility**.
3. Review the generated **Stadium Export Visibility** text block for unexpected
   inclusions or exclusions.
4. Choose **Validate Full Export…**, select the intended `.dae` destination, and
   use the same settings planned for the real export.
5. Resolve any reported missing image, UV, material, or destination error.
6. Choose **Export Stadium…** and wait for Blender to report completion.
7. Keep the generated DAE, JSON files, and `bmtex_*` texture folder together.
8. Load the venue in BeamNG and perform a visual and performance review.

For the complete walkthrough, see the **[User Guide](docs/USER-GUIDE.md)**.

## Export Options

### Checkboxes

| Checkbox | Default | What It Does | When to Change It |
|---|---:|---|---|
| **Include Eye-hidden Placed Geometry** | On | Includes real venue placements hidden with Blender's eye/H controls. Source prototypes, light blockers, render-disabled objects, and disabled collections remain excluded. | Turn it off only when intentionally exporting visible placements alone. Run **Check Stadium Visibility** either way. |
| **Approximate Glass** | Off | Replaces unsupported refraction with a BeamNG opacity approximation. Enabling it reveals **Glass Opacity**. | Enable only after accepting that the result is an approximation, then inspect it in BeamNG. Leave it off to make unsupported glass fail validation instead of silently changing appearance. |
| **Approximate Sheen** | On | Keeps the base PBR color and roughness for cloth materials and records that BeamNG has no separate Blender cloth-sheen lobe. | Keep it on for normal venue fabrics. Turn it off when you prefer validation to reject materials that need a sheen approximation. Linked sheen graphs remain unsupported. |

### Other Controls

| Control | Default | What It Does |
|---|---:|---|
| **Texture Resolution** | 2048 | Sets each baked texture to 512, 1024, 2048, or 4096 pixels. Higher values improve detail but increase export time, memory use, and package size. |
| **Transparency** | Blended | **Blended** preserves smooth alpha. **Cutout** uses an alpha test for hard-edged fences, signs, foliage, and similar materials. |
| **Game Texture Directory** | Blank | Sets the BeamNG virtual texture path. Leave it blank when exporting inside a valid `/levels/`, `/vehicles/`, or `/art/` folder so the exporter can infer it. This is a game path, not a Windows drive path. |
| **Glass Opacity** | 0.15 | Controls the opacity used when **Approximate Glass** is enabled. `0` is invisible and `1` is opaque. |
| **Nits per Emission Strength** | 100 | Converts Blender emission strength to BeamNG brightness for scoreboards, signs, and lighted surfaces. |
| **Scale** | 1.0 | Multiplies exported geometry size. Keep `1.0` when the source scene already uses the intended scale. |

The validator and exporter present the same options. Validate with the exact
destination and values you intend to export.

## Files Created

For an export named `MyVenue.dae`, the package contains:

```text
MyVenue.dae
MyVenue.materials.json
MyVenue.material-report.json
MyVenue.visibility.json
bmtex_<package-id>/
  <content-addressed PNG textures>
```

Old content-addressed textures are retained during re-export so existing references
are not broken. BeamNG should cook the authoring PNG textures to DDS before final
mod distribution.

## Validation and Compatibility

**Validate Full Export…** evaluates the same objects, modifiers, instances,
material graphs, images, UV maps, color attributes, object-atlas requirements,
and BeamNG destination rules used by the real export. It does not write a DAE or
bake textures.

A successful validation confirms static exporter compatibility. It does not prove
exact in-game lighting, placement, performance, or visual fidelity. Always inspect
the resulting venue in BeamNG.

## Supported Scope and Limitations

- The output target is BeamNG DAE/material packaging, not Madden, College Football,
  or NBA 2K proprietary game formats.
- Proprietary source shaders are represented by their current Blender preview.
- Animated scoreboards, source movies, runtime effects, and missing geometry are
  not reconstructed.
- Glass refraction is not preserved; the optional glass mode is an opacity
  approximation.
- BeamNG has no separate Blender cloth-sheen lobe.
- Linked sheen and linked coat-roughness graphs fail safely instead of producing
  an unverified package.
- Large 4096-pixel venue exports can require substantial time, memory, and storage.

## Repository Layout

```text
bm_stadium_dae/   Current clean add-on source
docs/             User guide, QA evidence, and team workflow
releases/         Versioned, installable Blender ZIP files
tools/            Release-building helper
```

The `main` branch is the current verified version. Team updates should use a short
branch and pull request; see **[Team Update Workflow](docs/TEAM-WORKFLOW.md)** and
the **[Changelog](CHANGELOG.md)**.

## Support

Use GitHub Issues for reproducible exporter problems. Include:

- Blender and exporter versions;
- the option values used;
- the exact validation or export error;
- the relevant `.material-report.json` or `.visibility.json`; and
- a minimal test scene when its content can be shared legally.

Do not upload copyrighted venue assets, proprietary game files, credentials, or
personal information to a public issue.

## License and Credits

Licensed under **GPL-3.0-or-later**. The export engine is adapted from
Blenux/BM BeamNG Collada 1.4.2. Third-party credits and license notices are included
under `bm_stadium_dae/LICENSES/` and in `bm_stadium_dae/THIRD_PARTY.md`.

This is an independent community tool and is not affiliated with or endorsed by
Electronic Arts, EA Sports, 2K, the NFL, the NCAA, or BeamNG GmbH. Game and league
names are used only to identify tested source-scene categories.
