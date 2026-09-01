# Security policy

## Supported status

This repository snapshot is `DEVELOPMENT_CANDIDATE / NOT_PRODUCTION_RELEASE_CERTIFIED`.
It is an isolated development candidate, not a production-certified release. No production deployment or
security-support lifetime is promised until a formal release policy is approved.

## Reporting a vulnerability

Do not publish secrets, personal data, proprietary annual reports, DATA_HOME contents, database extracts, or exploit details in a public issue. When a GitHub repository is established, use its private vulnerability-reporting or Security Advisory channel. Until then, contact the repository owner through a private channel identified by the owner.

A useful report contains the affected version, minimal reproduction using synthetic data, expected and observed behavior, impact, and proposed mitigation. Remove tokens, credentials, absolute personal paths and real financial documents before submission.

## Sensitive-data boundary

- `FIN_METRIC_DATA_HOME` must point outside the source tree.
- Never commit `.env`, API keys, SQLite databases, caches, logs, uploads, Capture evidence, Golden corpora or real PDFs.
- Treat generated research workbooks as potentially confidential even if they contain only derived values.
- Rotate any credential immediately if it was committed or exposed; deleting the current file does not remove it from Git history.

Security acceptance does not grant permission to redistribute third-party PDFs, datasets, models or binaries.
