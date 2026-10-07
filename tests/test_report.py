"""Acceptance scenarios mapped to Appendix F of the supplied final-year report."""

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from werkzeug.security import generate_password_hash
import test_app
from server import create_app, today, now
from features import backup_bytes, restore_archive, totp, seed_demo


class ReportTests(unittest.TestCase):
    send = test_app.BookingTests.send
    register = test_app.BookingTests.register
    book = test_app.BookingTests.book
    setUp = test_app.BookingTests.setUp
    tearDown = test_app.BookingTests.tearDown

    def test_portal_entry_and_legacy_links(self):
        entry = self.app.test_client().get("/")
        self.assertIn(b'data-portal="customer"', entry.data)
        self.assertIn(b'data-portal="admin"', entry.data)
        entry.close()
        for path in ("/customer", "/admin"):
            with self.app.test_client().get(path) as page:
                self.assertEqual(page.status_code, 200)
        old = self.app.test_client().get("/?paid=1")
        self.assertEqual(old.location, "/customer?paid=1")

    def test_demo_admin_signup_requires_mfa(self):
        client = self.app.test_client()
        self.tokens[id(client)] = client.get("/api/session").json["csrf"]
        response = self.send(
            client,
            "/api/auth/register",
            {
                "portal": "admin",
                "name": "Demo administrator",
                "email": "new-admin@example.com",
                "password": "New admin password!",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["mfa_required"])
        self.assertIsNone(client.get("/api/session").json["user"])
        self.assertEqual(client.get("/api/admin/users").status_code, 401)
        verified = self.send(
            client,
            "/api/auth/mfa",
            {
                "challenge": response.json["challenge"],
                "code": response.json["demo_code"],
            },
        )
        self.assertEqual(verified.json["user"]["staff_role"], "admin")
        self.assertEqual(client.get("/api/admin/users").status_code, 200)

    def test_normal_mode_blocks_public_admin_signup(self):
        self.app.config["DEMO_MODE"] = False
        client = self.app.test_client()
        self.tokens[id(client)] = client.get("/api/session").json["csrf"]
        response = self.send(
            client,
            "/api/auth/register",
            {
                "portal": "admin",
                "name": "Not an administrator",
                "email": "public-admin@example.com",
                "password": "New admin password!",
            },
        )
        self.assertEqual(response.status_code, 403)
        with sqlite3.connect(self.database) as database:
            self.assertEqual(
                database.execute(
                    "SELECT COUNT(*) FROM users WHERE email='public-admin@example.com'"
                ).fetchone()[0],
                0,
            )

    def test_demo_seed_does_not_invent_customer_requests(self):
        seed_demo(self.app)
        seed_demo(self.app)
        self.assertEqual(self.staff.get("/api/bookings").json["bookings"], [])
        booking = self.book().json["booking"]
        seed_demo(self.app)
        self.assertEqual(
            [item["id"] for item in self.staff.get("/api/bookings").json["bookings"]],
            [booking["id"]],
        )

    def test_portal_login_requires_correct_account_type(self):
        client = self.app.test_client()
        self.tokens[id(client)] = client.get("/api/session").json["csrf"]
        customer = {
            "email": "customer@example.com",
            "password": "Long customer password!",
        }
        staff = {"email": "staff@example.com", "password": "Long staff password!"}
        for credentials, portal in ((customer, "admin"), (staff, "customer")):
            response = self.send(
                client, "/api/auth/login", {**credentials, "portal": portal}
            )
            self.assertEqual(response.status_code, 403)
            self.assertIsNone(client.get("/api/session").json["user"])
        denied = self.send(client, "/api/auth/login", {**customer, "portal": "invalid"})
        self.assertEqual(denied.status_code, 400)
        verified = self.send(
            client, "/api/auth/login", {**customer, "portal": "customer"}
        )
        self.assertEqual(verified.json["user"]["role"], "customer")
        challenge = self.send(client, "/api/auth/login", {**staff, "portal": "admin"})
        self.assertTrue(challenge.json["mfa_required"])
        self.assertEqual(client.get("/api/session").json["user"]["role"], "customer")

    def role(self, role):
        email = role + "@example.com"
        with sqlite3.connect(self.database) as db:
            db.execute(
                "INSERT INTO users(name,email,password_hash,role,staff_role,created_at) VALUES(?,?,?,'staff',?,?)",
                (
                    role,
                    email,
                    generate_password_hash("Role test password!"),
                    role,
                    now(),
                ),
            )
        client = self.app.test_client()
        self.tokens[id(client)] = client.get("/api/session").json["csrf"]
        login = self.send(
            client,
            "/api/auth/login",
            {"email": email, "password": "Role test password!"},
        )
        verified = self.send(
            client,
            "/api/auth/mfa",
            {"challenge": login.json["challenge"], "code": login.json["demo_code"]},
        )
        self.assertEqual(verified.status_code, 200)
        return client

    def upload(
        self,
        client,
        kind="insurance",
        content=None,
        filename="certificate.pdf",
        owner=None,
    ):
        content = (
            content
            if content is not None
            else (
                Path(__file__).resolve().parents[1] / "samples/insurance-demo.pdf"
            ).read_bytes()
        )
        fields = {"kind": kind, "file": (io.BytesIO(content), filename)}
        if owner is not None:
            fields["applicantId"] = str(owner)
        response = client.post(
            "/api/documents",
            data=fields,
            headers={"X-CSRF-Token": self.tokens[id(client)]},
            content_type="multipart/form-data",
        )
        response.request.close()
        response.request.environ["wsgi.input"].close()
        return response

    def approved(self, **changes):
        response = self.book(**changes)
        self.assertEqual(response.status_code, 201)
        booking = response.json["booking"]
        result = self.send(
            self.staff,
            f"/api/bookings/{booking['id']}/decision",
            {
                "status": "approved",
                "note": "Accepted for demonstration.",
                "conditions": "Leave the room clean.",
            },
        )
        self.assertEqual(result.status_code, 200)
        return result.json["booking"]

    def test_tc01_configurable_discovery_and_fees(self):
        catalog = self.customer.get("/api/venues").json["venues"]
        self.assertEqual(len(catalog), 3)
        self.assertTrue(
            all(
                "equipment" in v and "rate_cents" in v and "conditions" in v
                for v in catalog
            )
        )
        admin = self.role("admin")
        v = dict(catalog[0], id="test-centre", name="New Test Centre", capacity=100)
        self.assertEqual(
            self.send(
                admin, "/api/admin/venues", {"venue": v, "reason": "Test expansion"}
            ).status_code,
            200,
        )
        self.assertEqual(len(self.customer.get("/api/venues").json["venues"]), 4)
        self.assertEqual(self.book(venue="test-centre").status_code, 201)

    def test_tc02_adaptive_evidence_and_server_validation(self):
        self.assertEqual(self.book(setupTime="").status_code, 400)
        self.assertEqual(self.book(adult=False).status_code, 400)
        self.assertEqual(self.book(privacy=False).status_code, 400)
        self.assertEqual(self.book(alcohol="Yes").status_code, 400)
        insurance = self.upload(self.customer).json["document"]["id"]
        permit = self.upload(self.customer, "permit").json["document"]["id"]
        response = self.book(
            alcohol="Yes",
            eventType="Workshop or class",
            documentIds=[insurance, permit],
        )
        self.assertEqual(response.status_code, 201)
        booking = response.json["booking"]
        path = f"/api/bookings/{booking['id']}/decision"
        self.assertEqual(
            self.send(
                self.staff, path, {"status": "approved", "note": "Not yet verified"}
            ).status_code,
            400,
        )
        for doc in (insurance, permit):
            self.assertEqual(
                self.send(
                    self.staff,
                    f"/api/documents/{doc}/verify",
                    {"note": "Sample reviewed."},
                ).status_code,
                200,
            )
        self.assertEqual(
            self.send(
                self.staff, path, {"status": "approved", "note": "Evidence verified."}
            ).status_code,
            200,
        )

    def test_tc03_unsafe_upload_private_encryption(self):
        self.assertEqual(
            self.upload(
                self.customer,
                content=b"<script>malicious</script>",
                filename="bad.html",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.upload(
                self.customer,
                content=b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
                filename="bad.pdf",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.upload(
                self.customer, content=b"%PDF-1.4 /JavaScript unsafe %%EOF"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.upload(
                self.customer, content=b"x" * (5 * 1024 * 1024 + 1)
            ).status_code,
            400,
        )
        content = (
            Path(__file__).resolve().parents[1] / "samples/insurance-demo.pdf"
        ).read_bytes()
        document = self.upload(self.customer).json["document"]
        url = "/api/documents/" + document["id"]
        self.assertEqual(self.customer.get(url).data, content)
        self.assertEqual(self.other.get(url).status_code, 404)
        finance = self.role("finance")
        self.assertEqual(finance.get(url).status_code, 404)
        with sqlite3.connect(self.database) as db:
            encrypted = db.execute(
                "SELECT encrypted FROM documents WHERE id=?", (document["id"],)
            ).fetchone()[0]
            self.assertNotIn(b"%PDF", encrypted)
            self.assertGreater(
                db.execute(
                    "SELECT COUNT(*) FROM event_log WHERE action='request_denied'"
                ).fetchone()[0],
                0,
            )

    def test_tc05_assisted_draft_submission_same_record(self):
        service = self.role("service")
        owner = self.customer.get("/api/session").json["user"]["id"]
        self.assertEqual(
            self.send(
                service, f"/api/draft?applicant={owner}", self.payload, "PUT"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.customer.get("/api/draft").json["draft"]["eventName"],
            self.payload["eventName"],
        )
        response = self.book(service, applicantId=owner)
        self.assertEqual(response.status_code, 201)
        row = response.json["booking"]
        self.assertEqual(row["channel"], "assisted")
        self.assertEqual(row["user_id"], owner)
        self.assertEqual(
            self.customer.get("/api/bookings").json["bookings"][0]["reference"],
            row["reference"],
        )
        self.assertEqual(
            self.send(
                service,
                f"/api/bookings/{row['id']}/decision",
                {"status": "approved", "note": "Not coordinator"},
            ).status_code,
            403,
        )

    def test_tc07_gateway_timeout_and_idempotent_retry(self):
        b = self.approved()
        pid = b["payment"]["id"]
        url = "/api/payments/" + pid + "/pay"
        self.assertEqual(
            self.send(self.customer, url, {"outcome": "timeout"}).json["payment"][
                "status"
            ],
            "processing",
        )
        paid = self.send(self.customer, url, {"outcome": "success"}).json["payment"]
        self.assertEqual(paid["status"], "paid")
        again = self.send(self.customer, url, {"outcome": "success"}).json["payment"]
        self.assertEqual(paid["provider_reference"], again["provider_reference"])
        with sqlite3.connect(self.database) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM gateway_ledger").fetchone()[0], 1
            )
        self.assertEqual(self.other.get("/api/payments/" + pid).status_code, 404)
        self.assertEqual(
            self.customer.get(f"/api/bookings/{b['id']}/receipt").status_code, 200
        )
        ics = self.customer.get(f"/api/bookings/{b['id']}/calendar.ics").data
        self.assertIn(b"BEGIN:VEVENT", ics)

    def test_tc08_unauthorised_refund_and_finance_authorisation(self):
        finance = self.role("finance")
        b = self.approved()
        bid = b["id"]
        pid = b["payment"]["id"]
        self.send(
            self.customer, "/api/payments/" + pid + "/pay", {"outcome": "success"}
        )
        self.send(self.customer, f"/api/bookings/{bid}/cancel", {})
        self.assertEqual(
            self.send(
                self.customer,
                f"/api/bookings/{bid}/refund",
                {"reason": "Cancelled the event."},
            ).status_code,
            201,
        )
        rid = finance.get("/api/finance").json["refunds"][0]["id"]
        self.assertEqual(
            self.send(
                self.staff,
                f"/api/refunds/{rid}/decision",
                {"approve": True, "note": "No authority"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.send(
                finance,
                f"/api/refunds/{rid}/decision",
                {"approve": True, "note": "Authorised in the demo."},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.send(
                finance,
                f"/api/refunds/{rid}/decision",
                {"approve": True, "note": "Duplicate"},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.customer.get("/api/bookings").json["bookings"][0]["payment"]["status"],
            "refunded",
        )

    def test_finance_reconciliation_decline_and_waiver(self):
        finance = self.role("finance")
        b = self.approved()
        url = "/api/payments/" + b["payment"]["id"] + "/pay"
        self.assertEqual(
            self.send(self.customer, url, {"outcome": "declined"}).json["payment"][
                "status"
            ],
            "declined",
        )
        self.assertEqual(
            self.send(
                finance,
                f"/api/bookings/{b['id']}/waiver",
                {"amount_cents": 1000, "note": "Approved partial waiver."},
            ).status_code,
            200,
        )
        self.send(self.customer, url, {"outcome": "timeout"})
        self.assertEqual(
            self.send(finance, "/api/finance/reconcile", {}).json["corrected"], 1
        )
        self.assertEqual(
            self.send(finance, "/api/finance/reconcile", {}).json["corrected"], 0
        )

    def test_tc09_reports_reconcile_with_occurrences_and_closures(self):
        b = self.approved(repeatCount=3)
        coordinator = self.staff
        query = {
            "from": self.payload["eventDate"],
            "to": (today() + timedelta(days=30)).isoformat(),
        }
        r = coordinator.get("/api/reports", query_string=query).json["report"]
        self.assertEqual(r["metrics"]["applications"], 1)
        self.assertEqual(r["metrics"]["approved"], 1)
        self.assertEqual(r["utilisation"][0]["booked_hours"], 12)
        self.assertEqual(self.customer.get("/api/reports").status_code, 403)
        self.assertEqual(
            coordinator.get("/api/reports/export", query_string=query).status_code, 200
        )

    def test_tc10_restore_documents_calendar_and_integrity(self):
        admin = self.role("admin")
        doc = self.upload(self.customer).json["document"]["id"]
        b = self.book(documentIds=[doc]).json["booking"]
        backup = admin.get("/api/admin/backup")
        self.assertEqual(backup.status_code, 200)
        archive = Path(self.directory.name) / "backup.zip"
        archive.write_bytes(backup.data)
        restored = Path(self.directory.name) / "restored.sqlite3"
        restore_archive(archive, restored)
        app = create_app(
            {"TESTING": True, "DATABASE": str(restored), "DEMO_MODE": True}
        )
        client = app.test_client()
        self.tokens[id(client)] = client.get("/api/session").json["csrf"]
        self.send(
            client,
            "/api/auth/login",
            {"email": "customer@example.com", "password": "Long customer password!"},
        )
        self.assertEqual(client.get("/api/bookings").json["bookings"][0]["id"], b["id"])
        self.assertEqual(
            client.get("/api/documents/" + doc).data,
            self.customer.get("/api/documents/" + doc).data,
        )
        self.assertFalse(
            client.get(
                "/api/availability",
                query_string={"venue": "nightcliff", "date": self.payload["eventDate"]},
            ).json["slots"][0]["available"]
        )
        self.assertTrue(admin.get("/api/audit").json["integrity"]["valid"])

    def test_recurring_conflict_atomic_and_closure_controls(self):
        conflict_date = (today() + timedelta(days=21)).isoformat()
        self.assertEqual(
            self.book(self.other, eventDate=conflict_date).status_code, 201
        )
        self.assertEqual(self.book(repeatCount=3).status_code, 409)
        self.assertEqual(self.customer.get("/api/bookings").json["bookings"], [])
        d = (today() + timedelta(days=15)).isoformat()
        self.assertEqual(
            self.send(
                self.staff,
                "/api/closures",
                {
                    "venue": "nightcliff",
                    "date": d,
                    "start": "09:00",
                    "end": "12:30",
                    "reason": "Maintenance",
                },
            ).status_code,
            201,
        )
        self.assertFalse(
            self.customer.get(
                "/api/availability", query_string={"venue": "nightcliff", "date": d}
            ).json["slots"][0]["available"]
        )
        self.assertEqual(self.book(eventDate=d).status_code, 409)

    def test_amendment_versioning_and_calendar_release(self):
        b = self.approved()
        bid = b["id"]
        new = self.payload | {
            "eventDate": (today() + timedelta(days=16)).isoformat(),
            "eventName": "Changed workshop",
        }
        self.assertEqual(
            self.send(
                self.customer,
                f"/api/bookings/{bid}/amend",
                {"proposed": new, "reason": "Change of date"},
            ).status_code,
            201,
        )
        record = self.customer.get("/api/bookings").json["bookings"][0]
        a = record["amendments"][0]
        self.assertEqual(
            self.send(
                self.staff,
                f"/api/amendments/{a['id']}/decision",
                {"approve": True, "note": "Date change accepted."},
            ).status_code,
            200,
        )
        record = self.customer.get("/api/bookings").json["bookings"][0]
        self.assertEqual(record["event_date"], new["eventDate"])
        self.assertGreaterEqual(record["version_count"], 3)
        self.assertTrue(
            self.customer.get(
                "/api/availability",
                query_string={"venue": "nightcliff", "date": self.payload["eventDate"]},
            ).json["slots"][0]["available"]
        )

    def test_staff_mfa_is_required_and_role_revocation(self):
        admin = self.role("admin")
        client = self.app.test_client()
        self.tokens[id(client)] = client.get("/api/session").json["csrf"]
        r = self.send(
            client,
            "/api/auth/login",
            {"email": "staff@example.com", "password": "Long staff password!"},
        )
        self.assertTrue(r.json["mfa_required"])
        self.assertEqual(client.get("/api/bookings").status_code, 401)
        self.assertEqual(
            self.send(
                client,
                "/api/auth/mfa",
                {"challenge": r.json["challenge"], "code": "xxxxxx"},
            ).status_code,
            401,
        )
        sid = self.staff.get("/api/session").json["user"]["id"]
        self.assertEqual(
            self.send(
                admin,
                f"/api/admin/users/{sid}/role",
                {"role": "customer", "note": "Revoke staff access"},
            ).status_code,
            200,
        )
        self.assertEqual(self.staff.get("/api/bookings").status_code, 401)

    def test_notifications_outbox_retry_and_deep_link_data(self):
        service = self.role("service")
        b = self.book().json["booking"]
        messages = self.customer.get("/api/notifications").json["notifications"]
        self.assertEqual(messages[0]["booking_id"], b["id"])
        self.assertEqual(messages[0]["read"], 0)
        self.send(self.customer, f"/api/notifications/{messages[0]['id']}/read", {})
        self.assertEqual(
            self.customer.get("/api/notifications").json["notifications"][0]["read"], 1
        )
        outbox = service.get("/api/staff/outbox").json["messages"][0]
        self.send(
            service, f"/api/staff/outbox/{outbox['id']}/retry", {"outcome": "failed"}
        )
        self.send(
            service, f"/api/staff/outbox/{outbox['id']}/retry", {"outcome": "delivered"}
        )
        self.assertEqual(
            service.get("/api/staff/outbox").json["messages"][0]["attempts"], 2
        )

    def test_audit_append_only_and_tamper_detection(self):
        admin = self.role("admin")
        self.book()
        self.assertTrue(admin.get("/api/audit").json["integrity"]["valid"])
        with sqlite3.connect(self.database) as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE event_log SET detail='tampered' WHERE id=1")
            c.execute("DROP TRIGGER immutable_events_update")
            c.execute("UPDATE event_log SET detail='tampered' WHERE id=1")
        self.assertFalse(admin.get("/api/audit").json["integrity"]["valid"])

    def test_single_use_password_recovery(self):
        r = self.send(
            self.customer, "/api/auth/reset-request", {"email": "customer@example.com"}
        )
        self.assertEqual(r.status_code, 200)
        service = self.role("service")
        message = service.get("/api/staff/outbox").json["messages"][0]
        token = message["body"].split("reset=")[1]
        result = self.send(
            self.customer,
            "/api/auth/reset",
            {"token": token, "password": "Recovered password long!"},
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            self.send(
                self.customer,
                "/api/auth/reset",
                {"token": token, "password": "Another password long!"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.send(
                self.customer,
                "/api/auth/login",
                {
                    "email": "customer@example.com",
                    "password": "Recovered password long!",
                },
            ).status_code,
            200,
        )

    def test_feedback_and_completion(self):
        b = self.approved()
        bid = b["id"]
        self.send(
            self.customer,
            "/api/payments/" + b["payment"]["id"] + "/pay",
            {"outcome": "success"},
        )
        self.assertEqual(
            self.send(
                self.staff,
                f"/api/bookings/{bid}/complete",
                {"note": "Demo event completed."},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.send(
                self.customer,
                f"/api/bookings/{bid}/feedback",
                {"rating": 5, "comment": "Easy to use."},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.staff.get("/api/reports").json["report"]["metrics"][
                "positive_feedback_percent"
            ],
            100,
        )
        self.assertEqual(
            self.send(self.customer, f"/api/bookings/{bid}/cancel", {}).status_code, 409
        )

    def test_finance_redaction_and_admin_mfa_reset(self):
        finance = self.role("finance")
        admin = self.role("admin")
        doc = self.upload(self.customer).json["document"]["id"]
        self.book(documentIds=[doc], notes="Private access information.")
        row = finance.get("/api/bookings").json["bookings"][0]
        self.assertEqual(row["notes"], "")
        self.assertEqual(row["documents"], [])
        staff_id = self.staff.get("/api/session").json["user"]["id"]
        self.assertEqual(
            self.send(
                finance,
                f"/api/admin/users/{staff_id}/reset-mfa",
                {"note": "Not authorised"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.send(
                admin,
                f"/api/admin/users/{staff_id}/reset-mfa",
                {"note": "Identity verified; replace lost authenticator."},
            ).status_code,
            200,
        )
        self.assertEqual(self.staff.get("/api/bookings").status_code, 401)
        with sqlite3.connect(self.database) as c:
            self.assertEqual(
                c.execute(
                    "SELECT totp_secret FROM users WHERE id=?", (staff_id,)
                ).fetchone()[0],
                "",
            )

    def test_configuration_does_not_invalidate_existing_reservations(self):
        admin = self.role("admin")
        self.book()
        venue = self.customer.get("/api/venues").json["venues"][0]
        self.assertEqual(
            self.send(
                admin,
                "/api/admin/venues",
                {
                    "venue": venue | {"capacity": 50},
                    "reason": "Unsafe capacity reduction.",
                },
            ).status_code,
            409,
        )
        self.assertEqual(
            self.send(
                admin,
                "/api/admin/venues",
                {
                    "venue": venue | {"opens": "10:00"},
                    "reason": "Unsafe hours reduction.",
                },
            ).status_code,
            409,
        )
        self.assertEqual(
            self.customer.get("/api/venues").json["venues"][0]["capacity"], 120
        )
        original = self.customer.get("/api/bookings").json["bookings"][0]
        self.assertEqual(
            self.send(
                admin,
                "/api/admin/venues",
                {
                    "venue": venue | {"rate_cents": 4600},
                    "reason": "Versioned fee revision.",
                },
            ).status_code,
            200,
        )
        versions = admin.get("/api/admin/venues/nightcliff/versions").json["versions"]
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["content"]["rate_cents"], 4600)
        self.assertEqual(
            self.customer.get("/api/bookings").json["bookings"][0]["amount_cents"],
            original["amount_cents"],
        )


if __name__ == "__main__":
    unittest.main()
