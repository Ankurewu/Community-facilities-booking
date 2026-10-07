# Traceability to PRT631 Group 5 report

Source: *Darwin Community Facilities Booking and Access System*, supplied draft dated 3 September 2026. Requirements are taken from Appendix C (FR), Appendix D (quality/security) and Appendix F (TC). The PDF is a requirements source, not an instruction to deploy or a production certification.

| Report ID | Implemented demonstration | Verification |
| --- | --- | --- |
| FR-01 | Search/compare active centres, capacity, equipment, access, rules and indicative fees | `test_tc01_configurable_discovery_and_fees`; browser discovery/configuration |
| FR-02 | Authoritative reservations, full access-period conflicts and recurring atomic submission | `test_concurrent_reservations`, `test_overlap_includes_setup_and_cleanup`, `test_recurring_conflict_atomic_and_closure_controls` |
| FR-03 | Customer accounts, persistent drafts, assisted selection/creation and shared applicant record | `test_private_drafts`, `test_tc05_assisted_draft_submission_same_record`; browser assisted draft/application |
| FR-04 | Insurance requirements vary by venue rules, event type/attendance; alcohol requires permit; adulthood/privacy checks | `test_tc02_adaptive_evidence_and_server_validation`; browser adaptive form |
| FR-05 | Required fields, date/capacity/time/recurrence checks; private constrained document upload | `test_validation`, `test_tc03_unsafe_upload_private_encryption` |
| FR-06 | Under-review/return/approval/rejection, mandatory reasons, conditions, evidence verification | `test_full_review_reply_and_cancel`, `test_tc02_adaptive_evidence_and_server_validation`; browser assessment |
| FR-07 | Authoritative inbox, per-application updates, durable email/SMS queue with simulated delivery/failure/retry | `test_notifications_outbox_retry_and_deep_link_data`; browser queue retry. **External delivery is simulated.** |
| FR-08 | Separate demo checkout, unique requests, signed provider references, success/decline/timeout/reconciliation, receipts | `test_tc07_gateway_timeout_and_idempotent_retry`, `test_finance_reconciliation_decline_and_waiver`; browser checkout. **No accredited gateway or real charge.** |
| FR-09 | Versioned amendments, cancellation, reasoned finance waivers/refunds, duplicate prevention | `test_amendment_versioning_and_calendar_release`, `test_tc08_unauthorised_refund_and_finance_authorisation`; browser amendment/refund |
| FR-10 | Closures/reopening, versioned rates/rules/equipment/accessibility, additional venues and weekly bookings | `test_tc01_configurable_discovery_and_fees`, `test_recurring_conflict_atomic_and_closure_controls`; browser calendar/admin |
| FR-11 | Role-gated operational counts, utilisation, elapsed cycle time, channels, returns, feedback and CSV export | `test_tc09_reports_reconcile_with_occurrences_and_closures`, `test_feedback_and_completion`; browser reporting |
| FR-12 | Actor/time/reason history, application versions, append-only HMAC-linked audit events; denied sensitive actions logged | `test_audit_append_only_and_tamper_detection`, `test_tc08_unauthorised_refund_and_finance_authorisation`; browser integrity |

## Representative acceptance cases

- TC-01: the three centres and configurable details are exposed; responsive/keyboard controls have local checks, not independent accessibility certification.
- TC-02: mandatory setup validation rejects an incomplete submission.
- TC-03: disallowed/mismatched/active-content/EICAR/oversized uploads are rejected and logged; production malware scanning is not implemented.
- TC-04: concurrent identical reservations yield one success and one conflict.
- TC-05: an officer saves/resumes/submits the applicant's same record.
- TC-06: return/reply/approval retain reasons, actor/time and version/history.
- TC-07: simulated authorisation timeout is reconciled idempotently without a second ledger charge.
- TC-08: coordinator refund attempt is denied/logged; finance can authorise exactly once.
- TC-09: unique application counts and occurrence access-hours reconcile to the source records.
- TC-10: a snapshot is restored to a new database; evidence decryption/digests, calendar conflicts, foreign keys and audit integrity are checked. Local evidence does not prove regional-outage RTO/RPO.

## Quality/security distinction

| Report target | Local implementation/evidence | Still needed for the proposed real service |
| --- | --- | --- |
| NFR-01 WCAG 2.2 AA | Semantic labels/headings, native modal focus, keyboard controls, text statuses, reduced-motion styling, mobile reflow checks | Independent WCAG audit, screen-reader and representative-user evaluation |
| NFR-02 p95 <2 seconds | Lightweight local API; tests exercise real service responses | Agreed load model, measured peak-load acceptance |
| NFR-03 99.5% availability | Health endpoint and recoverable persistent data | Hosting/monitoring SLA and observed service availability |
| NFR-04 RTO 4h/RPO 1h | Backup export, verified restore and recovery test | Off-site schedule, regional rehearsal and measured targets |
| NFR-05 85% independent task completion | Teacher walkthrough and automated user journeys | Moderated UAT with representative people |
| TR-01 modular responsive service | Core identity/CLI, workflow helpers, portal/checkout, role-gated APIs, configuration-driven venues | Formal API versioning and production architecture review |
| TR-02 transactional/encrypted/tamper-evident data | SQLite transactions, encrypted document/MFA contents, append-only HMAC-linked events | Encrypted object storage, managed keys, externally anchored logs |
| TR-03 identity/payment/delivery adapters | Password+TOTP identity, simulated provider ledger and durable delivery queue | Standard SSO and contracted real gateway/email/SMS integration |
| SR-01 MFA/least privilege | Staff TOTP, separate service/coordinator/finance/admin/auditor permissions and session revocation | Organisational access reviews and role minimisation validation |
| SR-02 protection/monitoring | CSRF, scrypt, opaque hashed sessions, constrained uploads, signed ledger, audit integrity, HTTPS-host instructions | Deployment encryption, managed secrets, scanning, central monitoring and penetration test |
| SR-03 privacy | Purpose/declarations, applicant ownership, profile correction, private evidence and finance/auditor redaction | Approved PIA, records/retention/disposal procedures and lawful access requests |

Pending reservations do not automatically expire; they remain held until a decision/cancellation. Time-limited temporary holds with warning/extension are an explicit remaining refinement from UC-02/UX discussion. Fee/rule changes are reasoned and versioned; an effective-date scheduler is not implemented. These are documented differences, not hidden claims of report-wide production acceptance.
