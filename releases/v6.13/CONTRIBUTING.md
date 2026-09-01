# Contributing

Thank you for helping improve AXA Research. This snapshot is still a public source candidate. Contribution acceptance may remain paused until the project license and third-party license obligations are approved.

## Before contributing

1. Read `README.md`, `docs/release_policy.md`, `docs/public_distribution_boundary.md` and the applicable architecture/data contracts.
2. Use a separate, empty DATA_HOME for development and tests.
3. Use only synthetic or explicitly redistributable PDFs, fixtures and expected outputs.
4. Never include credentials, user paths, real business data, Golden assets or generated caches.
5. Keep changes on the formal Capture-to-Merge path; do not create parallel OCR, Capture, Review, Canonical, Merge or export pipelines.

## Change expectations

- Explain the problem, contract impact and acceptance boundary.
- Add the smallest relevant regression test and document what was not run.
- Preserve immutable machine evidence and audit human decisions separately.
- Update the relevant architecture, contract, ADR or incident when behavior changes.
- Keep business feature changes separate from release-engineering changes.

## Pull requests

Pull requests should list modified files, validation evidence, data/license provenance for every new asset, and known limitations. A passing generated report alone is not release certification. Maintainers may reject any contribution whose data origin or redistribution permission cannot be verified.

By submitting a contribution you confirm that you have the right to submit it. The final inbound-contribution terms must be aligned with the project license after that license is selected.
