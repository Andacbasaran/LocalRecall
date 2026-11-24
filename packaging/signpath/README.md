# SignPath.io Free Open-Source Code Signing Guide

**LocalRecall** builds deterministic Windows x64 binaries (`LocalRecall-Setup-vX.Y.Z-Windows-x64.exe` and `LocalRecall-Portable-vX.Y.Z-Windows-x64.zip`) inside public GitHub Actions runners (`.github/workflows/release.yml`) and publishes unified `SHA256SUMS.txt` checksums for every release.

Because newly released unsigned executables may trigger a Windows SmartScreen "Unknown Publisher" prompt until reputation builds, [SignPath Foundation](https://signpath.org/) provides **free, trusted EV/OV code signing** for eligible open-source projects via GitHub Actions.

## Steps to Activate SignPath.io for LocalRecall

1. **Apply for the SignPath Open Source Program:**
   - Visit [https://signpath.org/terms](https://signpath.org/terms) and submit the repository `https://github.com/Andacbasaran/LocalRecall`.
   - Confirm that `LICENSE` (MIT), `SECURITY.md`, and public CI release workflows (`.github/workflows/release.yml`) are active (all already included).
2. **Create SignPath Project & Artifact Configuration:**
   - Organization slug: `localrecall`
   - Project slug: `localrecall`
   - Artifact configuration slug: `windows-release`
   - Signing policy: `release-signing` (requires maintainer approval for release tags).
3. **Add GitHub Repository Secrets:**
   - `SIGNPATH_API_TOKEN`
   - `SIGNPATH_ORGANIZATION_ID`
4. **Add the SignPath GitHub Action Step to `.github/workflows/release.yml`:**
   ```yaml
   - name: Submit Windows release artifacts to SignPath.io
     if: startsWith(github.ref, 'refs/tags/v') && secrets.SIGNPATH_API_TOKEN != ''
     uses: signpath/github-action-submit-signing-request@v1
     with:
       api-token: ${{ secrets.SIGNPATH_API_TOKEN }}
       organization-id: ${{ secrets.SIGNPATH_ORGANIZATION_ID }}
       project-slug: localrecall
       artifact-configuration-slug: windows-release
       signing-policy-slug: release-signing
       github-artifact-id: ${{ steps.upload-win.outputs.artifact-id }}
       wait-for-completion: true
       output-artifact-directory: signed_out
   ```
5. **Publish Signed Binaries:** Replace the unsigned Windows installers in `release_assets/` with `signed_out/*` before generating `SHA256SUMS.txt` and publishing the GitHub Release.
