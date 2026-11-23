# Security Policy

## Supported Versions

Only the latest `0.1.x` release series receives security updates.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

Please do not report security vulnerabilities through public GitHub issues.

Instead, report them privately using [GitHub Private Vulnerability Reporting](https://github.com/mohamed-hisham-swidan/onx-manager/security/advisories/new) (via the Security → Advisories → Report a vulnerability tab in this repository).

### What to Expect (Triage SLA)

- Acknowledgment: Within 3–5 business days (best-effort; this is a solo-maintained open-source project).
- Updates & Remediation: Confirmed vulnerabilities are prioritized based on severity. You will receive status updates through the private advisory thread until a fix is released and coordinated disclosure is agreed upon.

## Security Architecture Reference

For details on ONX Manager's authentication (RS256 JWT, Argon2id, SHA-256 API keys), authorization (global permissions and server-scoped RBAC via `contracts/permissions.yaml`), path-traversal sandboxing (`allowlist.py`), AES-256-GCM vaults, container hardening, and Docker-outside-of-Docker (DooD) considerations, see [docs/architecture/SECURITY.md](docs/architecture/SECURITY.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
