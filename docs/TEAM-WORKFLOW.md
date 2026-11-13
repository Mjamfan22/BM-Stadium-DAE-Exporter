# Team update workflow

The `main` branch should always contain the current verified source and
documentation. Installable ZIPs belong in formal GitHub Releases. Use a
short-lived branch and pull request for each update.

## Making an update

1. Create a branch such as `feature/material-validation` or `fix/windows-paths`.
2. Change the files under `bm_stadium_dae/`.
3. Update both version declarations:
   - `bm_stadium_dae/__init__.py` → `bl_info["version"]`
   - `bm_stadium_dae/blender_manifest.toml` → `version`
4. Update `CHANGELOG.md` and the current version/download in `README.md`.
5. Run the focused Blender test and relevant exporter regression fixtures.
6. Run `tools/build_release.ps1` from PowerShell.
7. Verify the locally printed SHA-256 and install the ZIP in Blender 5.2.x.
8. Commit the source and documentation, then open a pull request. Do not commit
   the generated ZIP from `dist/`.
9. Merge only after another team member reviews the validation evidence.
10. Create and push the version tag, such as `v1.1.1`, from the verified `main`
    commit.
11. Create a GitHub Release from that tag, attach the versioned ZIP from `dist/`,
    add concise release notes, and mark it as the latest release.

## Versioning

- Patch release (`1.1.1`): compatible bug fix.
- Minor release (`1.2.0`): new exporter behavior or validation feature.
- Major release (`2.0.0`): incompatible package or workflow change.

Do not overwrite an older release asset. Publish a new version tag and GitHub
Release so the Releases history preserves exactly what was installed.

## Recommended branch protection

For a team repository, require a pull request and one approval before merging to
`main`. Keep direct pushes restricted to repository administrators.
