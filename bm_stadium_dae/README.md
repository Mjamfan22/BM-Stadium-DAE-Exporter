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
approximation is explicit opt-in. BeamNG has no separate cloth-sheen lobe, so
the default sheen approximation retains base color and roughness and records
that limitation in the material report; linked sheen graphs remain unsupported.
Unsupported graphs produce an error before replacing the existing export.

This packages the current Blender preview. It does not reconstruct unknown
Madden/Frostbite shaders, animate source movies, create missing geometry, or certify
exact in-game appearance. Review the resulting level in BeamNG.

Export engine derived from Blenux/BM BeamNG Collada 1.4.2 under GPL-3.0-or-later.
Credits and licenses are included. This package has a separate module/operator/UI
and a self-contained export engine; the generic DAE/CDAE add-on can coexist.
