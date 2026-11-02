# Security

Do not file public issues containing credentials, session cookies, unredacted execution data, database dumps, or exploit details. Report a vulnerability privately to the deployment/repository owner. No public disclosure address or response SLA has been configured for this local project.

The application uses opaque hashed session tokens, Argon2 password hashes, workspace roles, CSRF checks, hashed one-time tokens, AES-GCM encrypted integration credentials, redacted event storage, signed cursors, and destination validation for outbound requests. These controls require correct deployment configuration; they are not a security certification.

Use HTTPS and secure cookies, protect the encryption key separately from database backups, restrict database and API network exposure, configure SMTP for resets, and review audit and notification failures. Keep `ALLOW_PRIVATE_NETWORK` disabled unless internal monitoring requires it. When enabled, enforce destination restrictions with network/firewall policy.

The built-in rate limiter is process-local. Use one API process or a shared proxy limiter when scaling. Raw source error messages may contain unusual secrets that pattern redaction cannot recognize; avoid putting secrets into node names or errors. Workflow map node names are operational metadata visible to workspace viewers. Never expose this local development configuration directly to the internet.

Dependency and regression checks are part of development; an independent production security review and load validation remain release responsibilities.
