# Changelog

## 1.1.2 — 2026-11-17

Changes since the published 1.1.0 release:

- Enabled **Approximate Glass** by default in Export and Validate, with an explicit
  opacity/refraction explanation. This avoids the reproduced default-setting
  refusal on Detroit and Rose Bowl transmission materials.
- Added **Copy Last Error** for complete errors, versions, paths and settings.
- Gave every visual part a unique static name and common detail suffix beneath
  `base00/start01`, preserving source names and placements.
- Corrected visibility reports to distinguish selection from exported geometry.
- Added a geometry export report with source-to-exported name mappings.
- Reject unexpected empty evaluated objects while preserving verified all-hidden
  seat masks as intentionally empty.
- Warn when approximated glass is below 2% opacity.
- Passed native Blender 5.2.3 geometry/operator fixtures, complete Detroit/Rose Bowl
  material-plan checks, and six representative actual material exports. Full-venue
  export and in-game visual checks remain separate; see `docs/QA-v1.1.2.md`.

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
