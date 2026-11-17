# BM Stadium DAE Exporter

Standalone Blender 5.2 add-on. It does not require the general BeamNG Collada add-on.

Install the ZIP with Preferences > Add-ons > Install from Disk, then enable it.
Use **File > Export > BeamNG Stadium (.dae)** or the **Stadium** sidebar tab.
Choose a destination inside your BeamNG level's art/assets folder. The exporter
writes DAE, matching .materials.json and baked texture files together. Keep them
together when copying the export. The destination is remembered in the scene.

Use **Stadium > Validate Full Export...** before a large export. It evaluates the
same modifiers, instances, material graphs, source images, UV maps, color
attributes and destination rules used by the real material package, but does not
write a DAE or bake textures. The proposed output path is used only to validate
the BeamNG virtual texture directory. A passing preflight is static exporter
compatibility evidence; it is not an in-game rendering certification.

All visible mesh objects are included, with evaluated modifiers/seat instances.
The default also includes eye/H-hidden objects with a real stadium placement ID.
Source prototypes, spare chair templates and engine light blockers stay excluded.
Placed objects can inherit a prototype flag from Structure repair; their placement
ID takes precedence. Render-disabled objects and excluded/disabled collections
are never silently enabled. Use **Check Stadium Visibility** to see every decision
in Text Editor > Stadium Export Visibility. An export also writes .visibility.json.

The original objects, geometry, UVs, material graphs and visibility are preserved.
Projection materials use temporary export-only UVs and texture baking. Texture
resolution controls size and cost. Large stadiums may take substantial time.
Transparency, emission and BeamNG clearcoat factors/maps are exported. Glass
approximation is labeled and enabled by default. Disable it to refuse materials
that require transmission rather than approximate them. BeamNG has no separate cloth-sheen lobe, so
the default sheen approximation retains base color and roughness and records
that limitation in the material report; linked sheen graphs remain unsupported.
Unsupported graphs produce an error before replacing the existing export.

This packages the current Blender preview. It does not reconstruct unknown
Madden/Frostbite shaders, animate source movies, create missing geometry, or certify
exact in-game appearance. Review the resulting level in BeamNG.

Export engine derived from Blenux/BM BeamNG Collada 1.4.2 under GPL-3.0-or-later.
Credits and licenses are included. This package has a separate module/operator/UI
and a self-contained export engine; the generic DAE/CDAE add-on can coexist.

## Version 1.1.1

Each exported part receives a unique static-shape name ending in the same `_a1`
detail suffix, inside `base00/start01`. Numeric source names can no longer turn
separate stadium parts into alternate distance-detail versions. Source Blender
names, placements and mesh data are unchanged. This is a static visual export;
it does not create collision meshes or an optimized multi-LOD model.

The visibility report now distinguishes selection from actual exported geometry.
Seat groups whose actual source selection mask hides every point are reported as
intentionally empty. Unexpected empty evaluated objects stop the export before
replacing files. The new `.export-report.json` maps source names to DAE names and
records omitted objects and exporter/Blender versions.

Glass approximations below 2% opacity produce an explicit warning. This update
does not increase authored opacity or guess a glass appearance. Missing/deleted
objects in an edited Blender scene must be restored from its source; no exporter
can infer that removed content. Re-export using the updated standalone add-on.

Validated on Blender 5.2.3 LTS with an actual Geometry Nodes export fixture and
the original Levi's Stadium material/geometry preflight. The corrected recipient
DAE was checked for unchanged geometry, bindings, transforms and texture bytes.
An in-game visual check is still required.

## Version 1.1.2

Approximate Glass is enabled by default in both Export and Validate. Detroit and
Rose Bowl previously refused their transmission materials with the default off.
Glass uses opacity instead of refraction; the setting remains visible and can be
disabled. Existing saved operator presets may retain the old off value.

If export or validation fails, use Stadium > Copy Last Error and paste the result
for troubleshooting. It includes the full error, Blender/exporter versions, local
source/output paths and selected settings. It is kept in memory, not saved into the
stadium file. Nothing is sent automatically.

Use File > Export > BeamNG Stadium (.dae). Choose a folder inside your BeamNG
level's art/assets folder, or enter its exact /levels/... Game Texture Directory.
Keep the DAE, .materials.json and bmtex_* folder together. A generic Collada export
does not provide this stadium material-baking workflow.
