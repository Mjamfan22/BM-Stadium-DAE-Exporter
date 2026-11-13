# Changelog

## 1.1.0 — 2026-11-12

- Added **Validate Full Export…** to the Stadium sidebar.
- Added non-writing material-aware preflight shared with the real package writer.
- Preflight now evaluates modifiers and instances.
- Added checks for material graphs, images, UVs, color attributes, object-atlas
  requirements and the proposed BeamNG texture destination.
- Verified the release in Blender 5.2.3 using representative Madden 27, College
  Football 27 and NBA 2K27 venues.
- Passed eight existing exporter regression fixtures.

## 1.0.3 — 2026-11-09

- Replaced long basename-derived atomic temporary and backup paths with short,
  unique same-directory names safe under legacy Windows path limits.

## 1.0.2 — 2026-11-09

- Added BeamNG clearcoat factor, map and roughness translation.
- Added an explicit recorded approximation for constant Blender cloth sheen.
- Linked sheen and linked coat roughness continue to fail safely.

## 1.0.0 — 2026-11-04

- Initial standalone stadium exporter separated from the general BeamNG COLLADA
  importer/exporter.
- Added conservative stadium visibility classification, material packaging,
  texture baking and source-scene preservation.
