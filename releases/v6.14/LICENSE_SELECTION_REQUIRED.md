# Project license decision and distribution record

The project owner selected `AGPL-3.0-only` on 2026-08-11. The repository-level declaration is [LICENSE](LICENSE). This decision applies to the v6.12.1 public-source candidate only and does not rewrite the frozen v6.11 baseline or the original v6.12 release directory.

## Owner records to retain

- Confirm each contributor's copyright ownership and whether employer, client or collaborator approval is required.
- OCR/PDF dependencies are bundled only in the Windows full portable pre-release;
  the source distribution retains optional installation profiles.
- Inbound contributions use the terms documented in `CONTRIBUTING.md`; add a DCO
  or CLA later only if the maintainer chooses that governance model.
- The top-level `LICENSE` contains the unmodified complete AGPL-3.0 text.

## PyMuPDF gate

Current dependency metadata identifies PyMuPDF as dual-licensed under AGPL-3.0
or an Artifex commercial license. This distribution selects the AGPL path:

- PyMuPDF is imported and distributed in the core and Windows full-package profiles;
- the project and network-use source are published under AGPL-3.0-only;
- the PyMuPDF 1.27.2.3 sdist and MuPDF 1.27.2 source archive (including its
  complete `thirdparty/` tree), with SHA-256 values, are included in the
  corresponding-source companion asset.

No Artifex commercial authorization is claimed or required for the selected path.

## Publication rule

The v6.12.1 source and Windows full package may be uploaded as a GitHub
**pre-release** only after the fresh boundary scan and published asset hashes
pass. This does not certify production behavior or the user-skipped E2E/real-data
gates.
