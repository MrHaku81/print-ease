# Security Policy

Thank you for taking the time to help keep PrintEase and its users safe.

This document explains **what counts as a security issue in PrintEase**, **how to report one**, and **what to expect after reporting**. It is inspired by the Linux kernel's revised security-bugs documentation (Tarreau, Linux 7.1, May 2026), adapted to the realities of a solo-maintained hobby project.

---

## Supported Versions

Only the **latest released version** of PrintEase is supported with security fixes. Older versions will not receive backports.

| Version | Supported |
|---|---|
| The most recent minor release | ✅ Yes |
| Older versions | ❌ No — please update first |

If you cannot update, please mention this when reporting; we may be able to advise on a workaround, but no patch will be issued for unsupported versions.

---

## Threat Model — What Counts as a Security Issue

PrintEase is a desktop application that manages **local printers and scanners** on a Linux system. It interacts with:

- The local CUPS daemon (via `pycups`)
- Network printers/scanners on the **local network** (via IPP, eSCL, mDNS/Avahi)
- The user's filesystem (for scan output)

Bugs are treated as security issues **only if they cross a trust boundary** on a correctly configured system. Specifically:

### In Scope ✅

We consider the following to be security issues:

- **Command injection** — Any way to inject shell commands via printer names, file paths, or other user/device-controlled input.
- **Path traversal** — Writing or reading files outside the intended directories (e.g. via scan output, config files, or import paths).
- **Privilege escalation** — Any way for PrintEase to obtain or grant privileges beyond the invoking user.
- **Sensitive data leaks** — Print job content, credentials, or user data written to world-readable logs or accessible to other local users.
- **Vulnerabilities in dependency surface** — If PrintEase passes attacker-controlled data to a dependency in a way that triggers a known CVE.

### Out of Scope — Trust Assumptions

PrintEase assumes the **local network is trusted** for the purpose of printer/scanner discovery and communication. This is consistent with how Apple AirPrint, Mopria, `sane-airscan`, and other industry implementations operate.

Concretely, this means the following are **known, accepted limitations** and not treated as security bugs:

- **eSCL/AirScan TLS without certificate verification.** Home and SOHO printers/scanners ship with self-signed certificates and no stable DNS names. PrintEase, like sane-airscan and AirPrint, does not verify these certificates. A man-in-the-middle attacker who controls the local network could intercept scan traffic. Users on hostile networks (public Wi-Fi, untrusted guest networks) should not rely on eSCL confidentiality.
- **mDNS/Avahi-based device discovery.** A malicious device on the same network can advertise itself as a printer or scanner. PrintEase will display it to the user; the user remains responsible for adding only trusted devices.

If you have a constructive proposal for improving these areas (e.g. TOFU-style certificate pinning), we welcome it as a **feature request**, not a security report.

### Out of Scope — Not Security Issues

The following are normal bugs and should be reported via the standard [Bug Report](https://github.com/MrHaku81/print-ease/issues/new?template=bug_report.yml) template, not as security issues:

- Application crashes (unless triggered by attacker-controlled input in a security-relevant way)
- Printer or scanner not detected / not working
- Incorrect or missing translations
- UI glitches, layout issues
- Wrong print margins, wrong paper size
- App fails to start on a specific distribution

If you are unsure whether something is a security issue, err on the side of reporting it privately — we'd rather triage a borderline report than miss a real vulnerability.

---

## How to Report a Vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

Please use **GitHub Security Advisories** to report privately:

👉 [Open a private security advisory](https://github.com/MrHaku81/print-ease/security/advisories/new)

This is an authenticated, private channel directly tied to the repository. It provides a structured form for the report and a clear audit trail for both reporter and maintainer.

If you cannot use GitHub Security Advisories for some reason, please open a normal issue saying *"I have a security concern, please advise on a private channel"* — without disclosing details — and we will arrange another way to receive the report.

### What to Include

To help us triage quickly, please provide:

- **Affected version** of PrintEase
- **Affected component** (printer setup, scan, settings, etc.)
- **A concise description** of the issue and its impact (what can an attacker actually achieve?)
- **A verified reproducer** — concrete steps, ideally with a minimal test case
- **Your assessment** of severity and exploitability
- **Optional:** a proposed fix or mitigation

### If You Used AI Assistance

PrintEase follows the same principle as the Linux kernel's updated policy (Tarreau, Linux 7.1):

> If you used AI tools (LLMs, automated scanners, etc.) to identify the bug, **you must treat it as public** and submit it via the regular [Bug Report](https://github.com/MrHaku81/print-ease/issues/new?template=bug_report.yml) template, **not** through the private channel.

The reason is practical: AI-discovered findings are systematically surfaced by multiple researchers using the same tools, often on the same day. Routing them through a private channel only causes duplication without adding confidentiality.

**Exception:** If you used AI to *analyze* a bug you discovered manually (e.g. to understand its impact), private reporting is fine. The question is who/what found it, not what helped you understand it afterwards.

**In all cases:** the human submitter is responsible for the report. AI-generated reports without manual verification (no tested reproducer, speculative impact, copy-pasted Markdown formatting) will be closed without detailed response.

---

## What to Expect After Reporting

PrintEase is maintained by a single hobbyist developer (@MrHaku81). Response times reflect that reality:

| Stage | Target |
|---|---|
| **Initial acknowledgement** | Within 7 days |
| **Severity assessment** | Within 14 days |
| **Fix timeline** | Case-by-case, depending on complexity |
| **Public disclosure** | 90 days after initial report (industry standard) |

If 90 days pass without a fix, the report may be disclosed publicly — either by the reporter or by us — to inform users. We will coordinate timing where possible.

### Severity Levels

We use a simple four-level scheme:

- **Critical** — Remote code execution, unauthenticated privilege escalation, or significant data loss affecting many users.
- **High** — Local privilege escalation, sensitive data leak, or exploitation requiring only local network access.
- **Medium** — Issues requiring specific conditions or significant user interaction.
- **Low** — Defense-in-depth improvements, hardening, minor information disclosure.

---

## Acknowledgements

Researchers who report valid security issues will be credited in:

- The security advisory itself (GitHub Security Advisories)
- The `CHANGELOG.md` entry for the fix
- A dedicated section of this document (added once we have any 🙂)

If you prefer to remain anonymous, please say so in your report.

---

## Known Security-Sensitive Dependencies

The following dependencies process attacker-influenced data (e.g. images from network scanners) and are kept up to date:

- **Pillow (PIL)** — Used to handle JPEG/TIFF data returned from eSCL scanners. Historically a source of image-parser CVEs.
- **pycups** — Used to communicate with the local CUPS daemon.

Users running outdated versions of these libraries (via old distribution packages) may be exposed to dependency-level vulnerabilities even if PrintEase itself is up to date. We recommend keeping system packages current.

---

*This policy was first published with PrintEase v0.2.x. It may evolve as the project grows.*
