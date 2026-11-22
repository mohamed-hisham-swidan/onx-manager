# Security Policy

## Supported Versions

Only the latest `0.1.x` release series receives security updates.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Instead, please report vulnerabilities privately through [GitHub Private Vulnerability Reporting](https://github.com/mohamed-hisham-swidan/onx-manager/security/advisories/new) on this repository.

<!-- TODO(HUMAN): Add security contact email / verify GitHub Security Advisories link and optional PGP fingerprint -->

When reporting a vulnerability, please include:

- A clear description of the issue and the affected component (backend API, WebSocket, file manager, provider execution, authentication/RBAC, encrypted vaults, or frontend).
- Step-by-step instructions or a minimal proof-of-concept to reproduce the issue.
- The potential impact and any preconditions required (e.g., unauthenticated vs. authenticated role).
- Any suggested mitigations or fixes, if available.

### What to Expect

<!-- TODO(HUMAN): Specify target acknowledgement / triage response SLA (e.g., within 72 hours) -->

- **Acknowledgement**: Reports are reviewed promptly upon submission.
- **Coordinate & Fix**: Once verified, a fix and regression test will be prepared before public disclosure.
- **Credit**: Reporters are credited in the security advisory and release notes unless anonymity is requested.

## Security Architecture Reference

For details on ONX Manager's authentication (RS256 JWT, Argon2id, SHA-256 API keys), authorization (global permissions and server-scoped RBAC via `contracts/permissions.yaml`), path-traversal sandboxing (`allowlist.py`), AES-256-GCM vaults, container hardening, and Docker-outside-of-Docker (DooD) considerations, see [docs/architecture/SECURITY.md](docs/architecture/SECURITY.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
