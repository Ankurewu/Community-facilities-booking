import concurrent.futures
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash
from server import create_app, today, now

class BookingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = str(Path(self.directory.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.database})
        self.customer, self.other, self.staff = [self.app.test_client() for _ in range(3)]
        self.tokens = {}
        self.register(self.customer, 'customer@example.com')
        self.register(self.other, 'other@example.com')
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,'staff',?)", ('Coordinator', 'staff@example.com', generate_password_hash('Long staff password!'), now()))
        self.tokens[id(self.staff)] = self.staff.get('/api/session').json['csrf']
        self.send(self.staff, '/api/auth/login', {'email': 'staff@example.com', 'password': 'Long staff password!'})
        self.payload = {'venue': 'nightcliff', 'eventDate': (today()+timedelta(days=14)).isoformat(), 'slot': '09:00–12:00', 'eventName': 'Community workshop', 'eventType': 'Community meeting', 'attendance': 60, 'setupTime': '08:30', 'cleanupTime': '12:30', 'alcohol': 'No', 'notes': '', 'declaration': True}
    def tearDown(self):
        self.directory.cleanup()
    def send(self, client, url, body, method='POST'):
        response = client.open(url, method=method, json=body, headers={'X-CSRF-Token': self.tokens[id(client)]})
        if response.is_json and 'csrf' in response.json:
            self.tokens[id(client)] = response.json['csrf']
        return response
    def register(self, client, email):
        self.tokens[id(client)] = client.get('/api/session').json['csrf']
        response = self.send(client, '/api/auth/register', {'name': 'Applicant', 'email': email, 'password': 'Long customer password!', 'role': 'staff'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['user']['role'], 'customer')
    def book(self, client=None, **changes):
        return self.send(client or self.customer, '/api/bookings', self.payload | changes)
    def test_password_hashes_and_cookie_security(self):
        with sqlite3.connect(self.database) as db:
            hashed = db.execute("SELECT password_hash FROM users WHERE email='customer@example.com'").fetchone()[0]
        self.assertNotEqual(hashed, 'Long customer password!')
        self.assertTrue(check_password_hash(hashed, 'Long customer password!'))
        response = self.app.test_client().get('/api/session')
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', response.headers['Set-Cookie'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
    def test_auth_csrf_origin_and_roles(self):
        self.assertEqual(self.app.test_client().get('/api/bookings').status_code, 401)
        self.assertEqual(self.customer.post('/api/bookings', json=self.payload).status_code, 403)
        self.assertEqual(self.customer.post('/api/bookings', json=self.payload, headers={'X-CSRF-Token': self.tokens[id(self.customer)], 'Origin': 'https://evil.example'}).status_code, 403)
        booking = self.book().json['booking']
        self.assertEqual(self.send(self.customer, f"/api/bookings/{booking['id']}/decision", {'status': 'approved', 'note': 'Not staff'}).status_code, 403)
    def test_full_review_reply_and_cancel(self):
        response = self.book(); self.assertEqual(response.status_code, 201)
        booking = response.json['booking']; path = f"/api/bookings/{booking['id']}"
        self.assertEqual(self.send(self.staff, path+'/decision', {'status': 'needs_info', 'note': 'Explain access needs.'}).status_code, 200)
        self.assertEqual(self.customer.get('/api/bookings').json['bookings'][0]['status'], 'needs_info')
        self.assertEqual(self.send(self.customer, path+'/reply', {'note': 'Step-free entry needed.'}).json['booking']['status'], 'pending')
        approved = self.send(self.staff, path+'/decision', {'status': 'approved', 'note': 'Access confirmed.'})
        self.assertEqual(approved.json['booking']['status'], 'approved'); self.assertEqual(len(approved.json['booking']['history']), 4)
        self.assertEqual(self.send(self.staff, path+'/decision', {'status': 'rejected', 'note': 'Final decision.'}).status_code, 409)
        self.assertEqual(self.send(self.customer, path+'/cancel', {}).status_code, 200)
        self.assertEqual(self.book(self.other).status_code, 201)
    def test_ownership(self):
        booking = self.book().json['booking']; path = f"/api/bookings/{booking['id']}"
        self.assertEqual(self.other.get('/api/bookings').json['bookings'], [])
        self.assertEqual(self.send(self.other, path+'/cancel', {}).status_code, 404)
        self.assertEqual(self.send(self.other, path+'/reply', {'note': 'Not mine'}).status_code, 404)
        self.assertEqual(self.send(self.staff, path+'/cancel', {}).status_code, 403)
    def test_overlap_includes_setup_and_cleanup(self):
        self.assertEqual(self.book(cleanupTime='13:30').status_code, 201)
        self.assertEqual(self.book(self.other, slot='13:00–17:00', setupTime='13:00', cleanupTime='17:00').status_code, 409)
        slots = self.customer.get('/api/availability', query_string={'venue': 'nightcliff', 'date': self.payload['eventDate']}).json['slots']
        self.assertFalse(slots[0]['available']); self.assertFalse(slots[1]['available']); self.assertTrue(slots[2]['available'])
        self.assertEqual(self.book(self.other, venue='malak').status_code, 201)
    def test_validation(self):
        for changes in [{'attendance': 121}, {'attendance': 1.5}, {'attendance': True}, {'eventDate': today().isoformat()}, {'eventDate': '2026-99-99'}, {'eventDate': (today()+timedelta(days=366)).isoformat()}, {'setupTime': '10:00'}, {'setupTime': '00:00'}, {'cleanupTime': '11:00'}, {'eventName': ' '}, {'slot': '07:00–08:00'}, {'venue': 'missing'}, {'declaration': False}, {'alcohol': 'Maybe'}, {'eventType': 'Invalid'}]:
            with self.subTest(changes=changes): self.assertEqual(self.book(**changes).status_code, 400)
        self.assertEqual(self.customer.get('/api/bookings').json['bookings'], [])
    def test_concurrent_reservations(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda client: self.book(client).status_code, [self.customer, self.other]))
        self.assertEqual(sorted(responses), [201, 409])
    def test_rejection_releases_time(self):
        booking = self.book().json['booking']; path = f"/api/bookings/{booking['id']}/decision"
        self.assertEqual(self.send(self.staff, path, {'status': 'rejected', 'note': ' '}).status_code, 400)
        self.assertEqual(self.send(self.staff, path, {'status': 'rejected', 'note': 'Facility unsuitable.'}).status_code, 200)
        self.assertEqual(self.book(self.other).status_code, 201)
    def test_staff_cannot_approve_own_request(self):
        booking = self.book(self.staff).json['booking']
        self.assertEqual(self.send(self.staff, f"/api/bookings/{booking['id']}/decision", {'status': 'approved', 'note': 'Own request'}).status_code, 403)
    def test_private_drafts(self):
        draft = {'eventName': 'My saved draft', 'venue': 'nightcliff'}
        self.assertEqual(self.send(self.customer, '/api/draft', draft, 'PUT').status_code, 200)
        self.assertEqual(self.customer.get('/api/draft').json['draft'], draft)
        self.assertIsNone(self.other.get('/api/draft').json['draft'])
        self.book(); self.assertIsNone(self.customer.get('/api/draft').json['draft'])
    def test_persistence_password_change_and_logout(self):
        self.book()
        app2 = create_app({'TESTING': True, 'DATABASE': self.database})
        client2 = app2.test_client(); self.tokens[id(client2)] = client2.get('/api/session').json['csrf']
        self.assertEqual(self.send(client2, '/api/auth/login', {'email': 'customer@example.com', 'password': 'Long customer password!'}).status_code, 200)
        self.assertEqual(len(client2.get('/api/bookings').json['bookings']), 1)
        self.assertEqual(self.send(self.customer, '/api/auth/password', {'current_password': 'Long customer password!', 'new_password': 'New long password!'}).status_code, 200)
        self.assertEqual(client2.get('/api/bookings').status_code, 401)
        self.send(self.customer, '/api/auth/logout', {})
        self.assertEqual(self.customer.get('/api/bookings').status_code, 401)
        self.assertEqual(self.send(self.customer, '/api/auth/login', {'email': 'customer@example.com', 'password': 'Long customer password!'}).status_code, 401)
        self.assertEqual(self.send(self.customer, '/api/auth/login', {'email': 'customer@example.com', 'password': 'New long password!'}).status_code, 200)
    def test_rate_limit(self):
        for _ in range(20):
            response = self.send(self.other, '/api/auth/login', {'email': 'other@example.com', 'password': 'wrong'})
            if response.status_code == 429: break
        self.assertEqual(response.status_code, 429)

if __name__ == '__main__': unittest.main()
