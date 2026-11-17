# Version 1.1.2 validation

Tested on Windows with Blender **5.2.3 LTS**, 17 November 2026.

## Reproduced default-setting issue

With Approximate Glass disabled, Detroit refused 28 transmission materials and
Rose Bowl refused two. Enabling the option passed the complete material plans:

| Venue | Prepared meshes | Materials | Planned bake jobs |
|---|---:|---:|---:|
| Detroit | 3,791 | 448 | 559 |
| Rose Bowl | 2,960 | 273 | 431 |

This reproduces a real setup failure. The recipient reports did not include their
exact errors, so it does not establish that every reported failure had this cause.

## Actual texture exports

Three representative real objects per venue covered glass, object-atlas baking,
and a textured material with a normal map. All six exports passed, writing 25
textures. PNG decoding, chunk CRCs and recorded texture hashes passed. These tests
used 64-pixel maps to exercise baking and writing efficiently; they were not full
venue exports. Source scene state and held input files remained unchanged.

The unchanged material/geometry engine was tested before the 1.1.2 UI changes.
An actual 1.1.2 operator fixture then exported linked glass at 512 pixels with the
new default, captured an intentional unsupported-material failure, preserved the
previous export, and cleared stale error state after successful validation.
The copy action was tested against a fake clipboard without touching the OS
clipboard. Unsupported materials still fail instead of being silently dropped.

The first Detroit test helper missed object-level material overrides while choosing
sample objects. Its corrected selector uses actual prepared primitive assignments.
That helper failure was preserved and was not an exporter failure.

## Geometry and reporting changes included from 1.1.1

An actual Geometry Nodes fixture exported visible seat instances, retained an
all-false source seat mask as intentionally empty, rejected unexpected empty
geometry, and checked source preservation, parent/world transforms, static names
and final visibility counts. Original Levi's material/geometry preflight passed
with 4,578 prepared meshes and 477 materials.

A separate recipient DAE format repair preserved 4,035 mesh payloads, material
bindings, transforms and all 979 texture files while applying unique static part
names and the documented hierarchy. That was not an in-game visual test.

## Limits

- No complete new Detroit or Rose Bowl export was performed in these tests.
- No BeamNG runtime or visual certification is claimed.
- Glass remains an opacity approximation, not refraction.
- The exporter cannot recreate deleted geometry or unknown proprietary shaders.
- Older saved presets can override the new glass default.
- The release contains exporter source only; no game assets or private logs.
