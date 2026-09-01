# Public distribution boundary

The public candidate is built from an explicit allowlist. Never initialize a repository in the development workspace and run `git add .`.

## Included when reviewed

- v6.12 source files required to run the application
- architecture, contract, security, contribution and release documentation
- dependency metadata and lock artifacts whose licenses are approved
- unit/targeted tests that contain no proprietary data
- small synthetic fixtures with documented provenance and redistribution permission
- build manifest and SHA-256 source inventory

## Excluded by default

- v6.11 frozen internal rollback snapshot and other historical release folders
- real insurer annual reports or excerpts, even when publicly downloadable
- Golden corpora, bounding boxes, OCR outputs or expected values derived from real reports unless redistribution is explicitly authorized
- any user or production DATA_HOME, including `metadata.db`
- Capture/Merge outputs, caches, logs, screenshots, research workbooks and task artifacts
- credentials, `.env`, local pointers, absolute personal paths and editor settings
- proprietary datasets, model weights, fonts, binaries or third-party examples without verified rights

## Required review before publication

1. Compare the staged file list with the allowlist and inspect every exception.
2. Scan the staged content and Git history for secrets and personal/machine-specific paths.
3. Confirm license and provenance for every dependency and non-source asset.
4. Resolve the PyMuPDF AGPL-3.0/commercial-license gate for the chosen distribution model.
5. Verify installation with locked dependencies in a clean environment.
6. Reproduce the documented minimal workflow using an empty DATA_HOME and synthetic data only.
7. Generate final SHA-256, SBOM/NOTICE and a signed release decision.

For v6.12.1, the P0 records are delivered by the source tree plus the required
Windows corresponding-source/provenance companion. After the fresh staging and
artifact scan passes, the permitted label is `PUBLIC_PRERELEASE_UPLOAD_READY /`
`NOT_PRODUCTION_RELEASE_CERTIFIED`.
