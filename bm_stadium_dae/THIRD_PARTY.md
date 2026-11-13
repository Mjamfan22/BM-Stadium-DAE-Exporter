# Credits and source provenance

This package retains the **BeamNG Collada Importer/Exporter** name and
`io_beamng_dae` module from **Blenux**. The Blender mesh construction/extraction
layer and bundled native geometry reader originate from that project.

- Source: https://github.com/Blenux/io_beamng_dae_dev
- Source revision: `6d4c9ebeac664ac3f62303cc04e22722b3c22a6e`
- License: GPL-3.0-or-later; complete text in `LICENSE.txt`.
- Native binary: unmodified `cdae_native.cp313-win_amd64.pyd` from the upstream
  `cdae_native-2.0.0-cp313-cp313-win_amd64.whl`.
- Upstream release:
  https://blenux.github.io/blender-extensions/io_beamng_dae_v1.0.0.zip
- Upstream ZIP SHA-256:
  `7697fdc3938f2be6071b7c31cfd5829cd684870c62bf4dedad3e00eeecd1fae1`.

The native component uses pugixml (MIT), Zstandard (BSD, with GPL alternative)
and pybind11 (BSD). Their license texts are included in `LICENSES`. Buildable
native source is available in the upstream repository's `native` directory;
no native binary modification was made for this adaptation.

The version-26 binary reader in `legacy_cache` is adapted from **Dummiesman's
DynamixThreeSpaceBlenderAddon**, MIT license:

- Source: https://github.com/Dummiesman/DynamixThreeSpaceBlenderAddon
- Revision: `2687f7e3f3e20065ce7ce2d3242d506d223a6d83`
- Original decoder modules retain their names. Imports are made package-relative
  so the decoder works without installing the original add-on.
- Complete copyright and permission text: `legacy_cache/LICENSE.txt`.

Local version 1.1.0 changes include Blender 5.2.3 packaging, scene/axis/unit and
instance handling, exact-source normal retention, removal of proximity welding,
concave polygon tessellation, a standards-based Python DAE writer, a published-
format v31 cache reader/writer, legacy-cache integration and transactional IO.
These changes are marked as a local BM adaptation and are GPL-3.0-or-later.

Format reference: https://docs.beamng.com/modding/file_formats/cdae/

Blender supplies NumPy and the Python Zstandard binding. Their code is not
copied into this installer. The add-on performs no runtime dependency download.

Version 1.2.0 adds stable UV channel export, float DAE colors, unassigned-face
preservation, scene unit scaling, static cache layout preservation, local material
previews, evaluated-mesh cleanup and stricter primitive validation.

The 256-entry encoded normal lookup table in `core/normal_table.py` is from
**Paul Hirch / Grille's Blender_BeamNG_CDAE**, MIT license:

- Source: https://github.com/Grille/Blender_BeamNG_CDAE
- Revision: `a438d35c01acef6e05a820e5373b828e02bd1de5`
- Original file: `src/grille_cdae/beamng/u8_normal_table.py`
- Complete copyright and permission text: `LICENSES/Grille_CDAE_MIT.txt`.

BeamNG normal-map preview convention and texture naming reference:
https://docs.beamng.com/modding/materials/texture_cooker/

Version 1.3.0 adds local workflow code for collection profiles, transactional
batch exports, explicit UV roles, reversible UV/skin previews, export checks and
optional edge-mark metadata. The native Blenux binary remains unmodified. The
labeled UV checker is Blender's built-in COLOR_GRID image, generated at runtime;
no third-party skin or texture assets are shipped.
