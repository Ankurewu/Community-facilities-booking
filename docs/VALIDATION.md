# Validation record

Validation is for the development workspace, not a public deployment or an independently assessed Council service.

## Observed final run · 7 October 2026

- **35 backend tests passed**, with no failed or skipped tests.
- **24 real-browser acceptance workflows passed**, with no JavaScript runtime errors.
- Separate portal entry, role-specific dashboards, opposite-portal session routing, and wrong-portal login rejection were checked. The original customer and staff booking workflows passed through the separate portals.
- Current-instance homepage, venue API, session API, demo account metadata and sample PDF requests returned HTTP 200.
- Both homepage buttons open email/password popups with bottom signup links. Customer and demo admin signup persist; admin access is withheld until MFA succeeds. Normal mode rejects public admin signup.
- New demo databases start with sample accounts and no bookings. Repeated seeding does not invent requests and preserves submitted customer applications. Admins land directly on the request queue; Accept/Reject decisions are reflected in the customer view.
- A local sample of 40 venue-API requests with four clients measured p95 **5.95 ms**. This is a small local sample, not the report’s agreed peak-load acceptance test.
- Python/JavaScript syntax, dependency consistency and Git whitespace checks passed.

## Automated backend

Run `.venv/bin/python -m unittest discover -s tests -v` (on Windows use `.venv\Scripts\python`). The suite uses isolated temporary databases and tests actual HTTP handlers/database transactions.

- Baseline: account security, CSRF/origin, ownership/roles, capacity/date/time validation, simultaneous reservations, setup/cleanup overlap, private drafts, return/reply/approval/cancellation, password/session revocation and persistence.
- Report scenarios: configurable venues/fees, adaptive mandatory evidence, unsafe files/private encryption, assisted shared record, payment timeout/idempotency, refund authority, waivers/reconciliation, recurring atomicity/closures, amendment versions, notifications/retries, MFA/access revocation, password recovery, reports/feedback and verified snapshot restoration.
- Audit controls: append-only updates are rejected; deliberately altered event detail fails hash verification.

## Browser acceptance

`node tests/browser.cjs` starts a fresh temporary instance and exercises the actual customer/coordinator/service/finance/admin interfaces. It does not rely solely on open ports or mocked API success. Browser checks include submitted state, rendered histories, private role navigation, authenticated file/download actions, reports and mobile reflow. JavaScript runtime errors are collected and cause failure.

The pass counts above can be reproduced with these commands. A browser download of a CSV/backup/ICS is checked separately from backend correctness. The Windows batch launcher is included but has not been executed on a Windows machine in this Linux workspace.

## Manual/UAT still required

A teacher or representative user should follow `TEACHER_WALKTHROUGH.md` without developer assistance and record task success/errors. Screen-reader testing, independent WCAG 2.2 AA assessment, production penetration testing, agreed peak-load measurement, off-site/regional recovery and real payment/delivery integration testing are not completed by these local checks. The Docker image and public hosting are untested.
