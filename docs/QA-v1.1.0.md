# Version 1.1.0 validation

Validated with Blender 5.2.3 LTS on 2026-11-12.

## Focused behavior

- Supported material passed the new non-writing preflight.
- Unsupported procedural Noise material was rejected before export.
- Evaluated Solidify modifier geometry was inspected.
- Preflight created no DAE, material JSON or baked texture files.
- Live scene state remained unchanged.
- A real small DAE/material package completed after the refactor.

## Regression coverage

Eight existing fixtures passed:

1. Material package and transactional rollback
2. Object-specific material baking
3. Planar shader mapping
4. Material color attributes
5. Planar atlas generation
6. Geometry Nodes instances
7. Hidden evaluated geometry
8. Detroit seat materials

## Representative current venues

| Source | Venue | Prepared meshes | Materials | Material jobs | Result |
|---|---|---:|---:|---:|---|
| Madden NFL 27 | Detroit | 3,791 | 448 | 559 | Passed |
| College Football 27 | Alabama | 4,111 | 201 | 1,680 | Passed |
| NBA 2K27 | Atlanta | 3,310 | 468 | 4,732 | Passed |

All three source Blend hashes and live scene states remained unchanged.

## Release identity

- File: `bm_stadium_dae_v1.1.0_Blender_5.2.zip`
- Files in archive: 21

Static validation does not establish BeamNG loading, performance or exact
source-game rendering fidelity.
