# DCF-BAS · Community facilities booking

A working coursework website based on the supplied Darwin community facilities prototype. The original visual design is retained, with a Flask API and SQLite database for accounts, booking requests and staff decisions. Demonstration facilities are not connected to actual council booking systems.

## Features

- Customer registration, sign-in, sign-out and password changes.
- Passwords hashed with scrypt; opaque, expiring server-side sessions in HttpOnly cookies.
- CSRF protection, sign-in rate limiting and server-enforced customer/staff permissions.
- Facility filtering, live availability and validated dates, attendance and access periods.
- Reservations include setup and cleanup. Concurrent overlapping requests cannot both succeed.
- Account-bound saved drafts and restoration after signing in again.
- Booking history, cancellation, staff information requests and customer replies.
- Staff queue with status filters, approval, rejection and persistent decision history.
- Responsive desktop and mobile screens, keyboard-accessible forms and dialogs.

## Run locally (Python 3.12+)

From this project folder:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py run
```

Open `http://localhost:8000` in your own browser. Create a customer account using the Create account tab. A password must contain 12–128 characters. The server must run: opening the HTML directly or using a static file server will not provide login or bookings.

On Windows use `py -m venv .venv`, then `.venv\Scripts\python -m pip install -r requirements.txt` and `.venv\Scripts\python server.py run`.

## Create a staff account

In a second terminal:

```bash
.venv/bin/python server.py create-staff --email teacher@example.com --name "Facility coordinator"
```

Replace the example email with the intended account email. The command securely prompts for a password and its confirmation. There is no default admin password. Public registration always creates a customer; it cannot grant staff access. Existing accounts are not promoted or overwritten. Sign out of your customer account and sign in with the staff account, or use a separate browser profile.

## Demonstrate to your teacher

1. Create a customer account and choose a facility.
2. Pick a future date and available time; provide an event name, type and attendance.
3. Include the event in the setup-to-cleanup period, then review and submit.
4. Sign in as staff in a different browser profile. Choose the new request in Staff workspace.
5. Request more information with a note. Return to the customer's My bookings and reply.
6. Refresh the staff queue and approve the request. Refresh the customer's bookings to see approval and history.
7. Try reserving the same facility and period: it is unavailable. Cancel as the customer to release it.
8. Restart the server and sign in again to demonstrate persistence.

All event dates and hours use Australia/Darwin. Bookings are allowed from tomorrow through the next 365 days. Pending, awaiting-information and approved requests hold their full access period. Rejected/cancelled requests release it. Applicants may cancel active future bookings; final staff decisions cannot be changed, and staff cannot approve their own requests.

## Share a public link

This version requires a Python web host with a persistent disk. A static Netlify Drop upload cannot run its backend.

One option is a Render Python web service connected to your GitHub repository:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 2 'server:create_app()'`
- Attach a persistent disk at `/var/data` (choose a plan supporting disks; this can have a cost).
- Set `DATABASE_PATH=/var/data/bookings.sqlite3` and `COOKIE_SECURE=1`.
- Set `TRUST_PROXY=1` only when behind the host's single trusted HTTPS reverse proxy, which must overwrite `X-Forwarded-Proto`.
- Health-check path: `/api/venues`.
- Run the create-staff command in the host's shell so it uses that same database. Enter the staff password at the prompt, never in Git or environment scripts.

The host provides an HTTPS URL to share with your teacher. Deployment has not been performed by this project. The uploaded `.openai/hosting.json` is retained as metadata for the old static site; it does not deploy this backend.

You can also use the Dockerfile on a host with persistent storage. It listens on port 8000; mount persistent storage writable by the `booking` user at `/app/instance`, or set `DATABASE_PATH` to a writable mounted path. Set secure cookies and trusted-proxy configuration when using HTTPS. The Docker image has not been built in this workspace.

## Database and configuration

The database defaults to `instance/bookings.sqlite3` and is excluded from Git. It contains personal account and booking data; protect it and never upload it as source. Sessions expire after eight hours. Changing a password revokes the account's other sessions. No secret signing key is needed because session tokens are random and only their SHA-256 hashes are stored in the database.

Use `DATABASE_PATH` to select another persistent location. `COOKIE_SECURE=0` is the default for local HTTP only; set it to `1` for public HTTPS. IP rate limits use the immediate client address; on hosts with a shared proxy address, add host-level rate limiting as appropriate. Do not trust arbitrary forwarded client-IP headers.

Back up SQLite using its backup API while the service is running, or stop the service before copying the database. Do not copy only the main database while writes are in progress: WAL files may contain current data.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover authentication, CSRF, authorization and ownership, password hashing and session revocation, input validation, simultaneous conflicting reservations, setup/cleanup overlap, drafts, cancellation, staff decisions and database persistence. Tests use temporary databases, not your real accounts.

## Scope

This is a complete working teacher demonstration of the account and booking workflow. It does not send emails, verify email addresses, recover forgotten passwords, take payments, upload insurance documents or connect to council services. Staff decisions and replies appear inside the website; use Refresh to retrieve updates. Public production use would require those integrations as applicable, operational backups, monitoring and a security review. A forgotten password currently requires creating a new demo account; there is no email reset flow.

## Files

- `server.py`: API, account security, database initialization and staff creation.
- `dist/index.html`, `dist/styles.css`, `dist/app.js`: website interface.
- `requirements.txt`: pinned Python dependencies.
- `tests/test_app.py`: isolated API/integration tests.
- `Dockerfile`: optional container hosting configuration.
