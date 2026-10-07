# DCF-BAS · Final-year booking demonstration

A working demonstration of the **Darwin Community Facilities Booking and Access System** described in the supplied PRT631 Group 5 report. The same connected application moves from discovery to evidence, assessment, demonstration payment, confirmation, amendments/cancellation and refunds. Data is saved in SQLite and survives restarts.

## Start on Windows — easiest way

1. Stop the previous website: press **Ctrl+C** in its command window.
2. Download the newest ZIP from GitHub and **Extract All**. Open the folder containing `server.py`, `features.py` and `START_DEMO.bat`.
3. Double-click **`START_DEMO.bat`**. Keep its window open. It creates the Python environment, installs dependencies and opens the website once the server responds.
4. The opening page has **Customer** and **Admin** buttons. Clicking either opens an email-and-password popup on the same page.
5. Click **Customer**, then **Use sample account** and **Sign in**. To create your own account instead, click **Sign up** at the bottom of the popup. Your dashboard links to Find a facility, My bookings and your inbox.
6. In another browser profile, click **Admin** and sign in using the sample administrator or create a demo admin account with **Sign up**. Complete the prefilled verification step. Admins immediately see **Customer booking requests**, with **Accept** and **Reject** controls on eligible requests. New installations start with an empty request list until a customer submits a booking. Previously saved requests remain intact.

If a command window reports that port 8000 is busy, stop your previous server first. If needed, open Command Prompt **inside this extracted project folder** and run:

```bat
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python server.py demo --open-browser
```

Open **http://localhost:8000** if your browser does not open automatically. Do not open `index.html` directly or use a static web server: the API is required. Python 3.12+ is recommended. A missing `requirements.txt`/`server.py` error means your command window is in the wrong folder.

For a different port:

```bat
.venv\Scripts\python server.py demo --port 8001 --open-browser
```

## Mac/Linux

```bash
bash start_demo.sh
```

Or manually:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py demo --open-browser
```

## Sample roles

**Customer portal (`/customer`)** has its own login, registration, dashboard, facility search, bookings and inbox. **Admin portal (`/admin`)** has a separate staff login, booking request queue and dashboard for assessment, calendar, finance, assisted booking, reports and administration. Only tasks allowed by the signed-in staff role appear. Customer credentials are rejected by the admin login, and staff credentials are rejected by the customer login. Existing server-side permissions protect the APIs.

Both opening-page login popups have **Sign up** at the bottom, and signup forms have **Sign in** for existing accounts. In explicit teacher-demo mode, Admin signup creates a demo administrator and requires staff MFA before granting access. Normal mode permits public customer signup only; staff accounts are created by the CLI or an authorised operator.

The root page (`/`) lets you choose an account type and sign in using its popup. **Choose portal** in either header returns there. One authenticated session is shared within a browser profile: opening the opposite portal while signed in sends you back to your account's portal. Use separate browser profiles to demonstrate both accounts simultaneously.

The password for the **explicit local demo mode only** is `DemoBooking2026!`. Clicking a role in the demo panel prefills the email and password; it does not bypass authentication.

| Role | Email | What to demonstrate |
| --- | --- | --- |
| Customer | customer@demo.example | Apply, upload evidence, save/resume, reply, amend, pay, cancel, request refund, give feedback |
| Coordinator | coordinator@demo.example | Verify evidence, start assessment, request information, approve/reject, add closures, complete events, view reports |
| Customer Service | service@demo.example | Create/select an applicant, enter/resume the same application on their behalf, handle delivery queue |
| Finance | finance@demo.example | Waivers, refund decisions, provider references and timeout reconciliation |
| Administrator | admin@demo.example | Configure facilities/equipment/rates/rules, manage roles/MFA, export a private backup, audit/reports |
| Auditor | auditor@demo.example | Read audit integrity and role-based reports; cannot assess or refund |

Staff always complete a TOTP verification step. Demo mode exposes a test code after valid password authentication so no phone setup is needed for your presentation. Normal mode instead requires an authenticator app, and shows a setup secret only after the correct password on first enrolment. A code cannot be reused: if you sign out and immediately sign back into the same staff account, wait for the next 30-second code window if verification reports an already-used code.

Use **different browser profiles/incognito windows** for customer and staff so the teacher sees both views together. Otherwise sign out before switching roles. Use fictitious names, phone numbers and documents.

## Working functions

- Search/compare active venues, attendance, accessibility, equipment, conditions and indicative hourly fees.
- Live availability and atomic conflict prevention for the entire setup-to-cleanup period.
- Weekly recurring reservations (up to 12); a conflict on any occurrence blocks the entire submission.
- Customer accounts, sign-in/out, profile correction, password changes and single-use password recovery.
- Role-separated staff access, MFA, session expiry, CSRF, password hashing and authentication rate limiting.
- Shared account drafts and staff-assisted applications on the applicant's own record.
- Adaptive insurance/permit requirements, adulthood and privacy declarations, private evidence uploads and human verification.
- Submitted/under-review/returned/approved/rejected workflow, decision reasons and approval conditions.
- Customer replies, versioned amendments, cancellation and calendar release.
- Hosted **demo** checkout with success, decline and authorisation-timeout paths; retries use the same provider reference.
- Confirmation, printable receipt/PDF, calendar `.ics` download, completion and feedback.
- In-app status inbox and persistent simulated email/SMS delivery queue, failure and retry controls.
- Finance-approved waivers/refunds, unique refund references and reconciliation.
- Facility closures/reopening; versioned rates, rules, equipment, accessibility and additional venues.
- Demand/utilisation/cycle-time/channel/returns/feedback reports and CSV export.
- Append-only, HMAC-linked audit events, authenticated backups and verified CLI restoration.

Dates and event hours use **Australia/Darwin**. Bookings are allowed from tomorrow through the following 365 days; each recurrence must remain inside that window. The sample opening range is 06:00–23:59. Pending, returned and approved applications reserve their full period until cancelled/rejected. There is no automatic timed-hold expiry in this demo. Amendments retain the original reservation until approved and are rechecked transactionally. Changed applications return to assessment. A paid amendment must keep the same charge; use cancellation/refund/new application for a differently priced change.

## Evidence and payments

Use `samples/insurance-demo.pdf` and `samples/permit-demo.pdf`, also downloadable from the demo panel. They are explicitly fictitious documents.

PDF, PNG and JPEG files up to 5 MB are accepted. Type/content checks reject mismatches, oversized files, active PDF features and the EICAR test signature. Images are decoded/verified. Document contents are encrypted with Fernet before storage and authenticated on download. Document access is restricted to the applicant, assessment staff, Customer Service and administrators. Required evidence must be manually verified before approval.

The payment provider is a **separate local checkout page and simulated provider ledger**. No real money or card information is collected. Signed ledger records and a unique payment key allow retry/reconciliation after a simulated timeout. Refunds require finance permission and a reason. This is not an accredited hosted gateway or a Council finance integration.

Status is authoritative in the portal. Outbox delivery outcomes are simulated, not real emails/text messages. Password recovery/assisted activation links appear in the queue; the public local demo mailbox exposes **only the six synthetic sample accounts**. For another created applicant, an authorised Customer Service officer can view the activation message in their outbox. A production messaging adapter is not configured.

## Normal mode and existing accounts

```bat
.venv\Scripts\python server.py run
```

Normal mode defaults to `instance/bookings.sqlite3`; demo mode uses **a separate `instance/demo.sqlite3`**. Existing accounts/bookings are preserved by additive migrations. In normal mode, public registration creates a customer account. Normal mode does not seed public demo credentials or expose demo codes/mailbox. Its payment and delivery adapters remain simulations and must be replaced before any real service use.

To create your own staff account in normal mode (password prompted securely):

```bat
.venv\Scripts\python server.py create-staff --email you@example.com --name "Facility coordinator" --role coordinator
```

Allowed staff roles are `coordinator`, `service`, `finance`, `admin`, `auditor`. For an administrator use `--role admin`. The command does not overwrite/promote an existing account. First staff login enrols an authenticator. Privileged accounts can be given/revoked access in Administration; changes revoke their existing sessions. Another administrator can authorise an MFA reset.

## Testing

```bat
.venv\Scripts\python -m unittest discover -s tests -v
```

Tests use temporary databases, not your demo data. They exercise the report's acceptance scenarios, concurrency, security, encrypted documents, recovery and financial state transitions.

The optional real-browser acceptance script is `tests/browser.cjs`. It uses Playwright and a temporary database. If Node.js is installed:

```bash
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node tests/browser.cjs
```

In the cloud workspace the script can use the preinstalled system Chromium. It exercises customer and staff screens, uploads, amendments, checkout timeouts, refunds, assistance, outbox retry, administration, reports, audit/backup and mobile reflow. Automatic checks do not replace independent WCAG/screen-reader/security acceptance.

## Recovery

An administrator can choose **Administration → Download private recovery backup**. This contains the database, encrypted documents and encryption key. **Keep it private; never upload it to GitHub.**

To rehearse a restore, stop the server and restore to a new path:

```bat
.venv\Scripts\python server.py restore --file DCF-BAS-private-backup.zip --destination instance\recovery.sqlite3
set DATABASE_PATH=%CD%\instance\recovery.sqlite3
.venv\Scripts\python server.py run
```

Use `export DATABASE_PATH="$PWD/instance/recovery.sqlite3"` on Mac/Linux. Restoring validates SQLite integrity, foreign keys, document decryption/digests and the audit chain. It refuses to overwrite an existing database. Preserve the old database and verify users, documents, conflicts and finance references before switching over. The report's RTO/RPO targets are not established by one local restore test.

## Public sharing and configuration

To show it on your own laptop, no hosting account is needed. The localhost link works on your computer only. Public sharing requires a Python host with HTTPS and persistent storage; Netlify Drop cannot run this backend.

A Render Python service is one option (a persistent-disk plan can have a cost):

- Build: `pip install -r requirements.txt`
- Start: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 2 'server:create_app()'`
- Persistent disk: `/var/data`; set `DATABASE_PATH=/var/data/bookings.sqlite3`.
- HTTPS: `COOKIE_SECURE=1`; `TRUST_PROXY=1` only behind one trusted proxy that overwrites `X-Forwarded-Proto`.
- Health path: `/api/venues`.
- No public deployment has been performed.

`DEMO_MODE=1` deliberately exposes test MFA codes and synthetic-account messages. Do not enable it for real accounts or personal data. Only `server.py demo` seeds sample data; merely setting that variable for Gunicorn does not seed accounts. Host normal mode with individually created accounts for controlled access. The original `.openai/hosting.json` remains metadata for the old static prototype and cannot deploy this backend.

SQLite contents, private backups, keys, `.env` and virtual environments are excluded from Git. Protect both the `.sqlite3` database and adjacent `.key`: loss of the key makes evidence/MFA secrets unrecoverable. Account/session/booking metadata is not encrypted at rest by this application; production needs encrypted storage and managed keys. Database snapshots contain expiring session data; protect them as credentials. The service does not use raw card numbers or security codes.

## Report evidence and limits

Read [Report traceability](docs/REPORT_TRACEABILITY.md), [Teacher walkthrough](docs/TEACHER_WALKTHROUGH.md), and [Validation record](docs/VALIDATION.md).

This is a working coursework demonstration, not a Council deployment. Live payment/email/SMS/finance integrations, production malware scanning, encrypted cloud object storage, standard SSO, independent WCAG/penetration/privacy assessment, approved retention/disposal, externally anchored audit logging, production monitoring and availability/load/recovery certification remain outside the demo. Staff operational roles share application metadata; finance/auditor views redact event notes and evidence details. The report's targets are design goals, not achieved service metrics. Marks depend on your teacher's rubric, your explanation and verified contribution; this repository does not guarantee a grade.

## Source layout

- `server.py`: core HTTP/session/account setup, database access and CLI.
- `features.py`: report-aligned workflow, evidence, MFA, payments, notifications, configuration, reporting and recovery.
- `dist/`: responsive portal and separate demo checkout.
- `samples/`: fictitious evidence PDFs.
- `tests/`: isolated backend and real-browser acceptance scenarios.
- `docs/`: traceability, presentation steps and validation evidence.
- `START_DEMO.bat`, `start_demo.sh`: launchers.
- `Dockerfile`: optional production-server container; not built in this workspace. It requires a writable persistent volume for the database and key.
