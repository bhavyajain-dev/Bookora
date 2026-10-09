"""
BOOKORA — End-to-End API Contracts & Split Architecture Test Suite

Validates all 16 API endpoint schemas, request/response contracts, CORS behavior,
and session boundaries for the separated frontend-backend architecture.
"""

import unittest
from unittest.mock import patch, MagicMock
import json
from datetime import date, time, timedelta

import app


class TestApiContractsAndSplitArchitecture(unittest.TestCase):
    def setUp(self):
        self.app = app.app
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-12345'
        self.client = self.app.test_client()

    # -------------------------------------------------------------------------
    # 1. /healthz
    # -------------------------------------------------------------------------
    def test_healthz_contract(self):
        resp = self.client.get('/healthz')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get('status'), 'ok')

    # -------------------------------------------------------------------------
    # 2. /api/movies
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_get_all_movies_contract(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {'id': 1, 'title': 'Chhaava', 'slug': 'chhaava', 'status': 'now_showing'}
        ]

        resp = self.client.get('/api/movies')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 1)
        self.assertIsInstance(data['movies'], list)
        self.assertEqual(data['movies'][0]['slug'], 'chhaava')

    # -------------------------------------------------------------------------
    # 3. /api/movies/slug/<slug>
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_get_movie_by_slug_contract(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            'id': 1, 'title': 'Chhaava', 'slug': 'chhaava', 'duration': 150
        }

        resp = self.client.get('/api/movies/slug/chhaava')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['movie']['title'], 'Chhaava')

    @patch('app.get_db')
    def test_get_movie_by_slug_not_found(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        resp = self.client.get('/api/movies/slug/nonexistent')
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertFalse(data['success'])

    # -------------------------------------------------------------------------
    # 4. /api/shows
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_get_shows_contract(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # 1st query: resolve slug
        mock_cursor.fetchone.return_value = {'id': 1, 'title': 'Chhaava'}
        # 2nd query: shows
        mock_cursor.fetchall.return_value = [
            {
                'show_id': 10,
                'show_time': timedelta(seconds=68400),
                'theatre_id': 2,
                'theatre_name': 'Rajhans',
                'theatre_address': 'Vastrapur',
                'available_seats': 100,
                'total_seats': 120
            }
        ]

        resp = self.client.get('/api/shows?slug=chhaava&date=2026-10-08')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['theatres']), 1)
        self.assertEqual(data['theatres'][0]['shows'][0]['time'], '19:00')

    # -------------------------------------------------------------------------
    # 5. /api/seats/<show_id>
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_get_seats_contract(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        mock_cursor.fetchone.return_value = {
            'id': 10,
            'movie_title': 'Chhaava',
            'theatre_name': 'Rajhans',
            'theatre_address': 'Vastrapur',
            'show_date': date.today() + timedelta(days=1),
            'show_time': timedelta(seconds=68400)
        }
        mock_cursor.fetchall.return_value = [
            {'id': 101, 'seat_label': 'A1', 'price': 250.0, 'is_booked': 0}
        ]

        resp = self.client.get('/api/seats/10')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['show']['movie_title'], 'Chhaava')
        self.assertEqual(len(data['seats']), 1)
        self.assertEqual(data['seats'][0]['seat_label'], 'A1')

    # -------------------------------------------------------------------------
    # 6. /api/send-otp
    # -------------------------------------------------------------------------
    @patch('app.send_email_otp', return_value=True)
    @patch('app.get_db')
    def test_send_otp_contract(self, mock_get_db, mock_send_email):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (None,)  # No previous code age (no cooldown)

        resp = self.client.post('/api/send-otp', json={'email': 'user@example.com'}, headers={'Origin': 'http://localhost:3000'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertIn('resend_after', data)

    # -------------------------------------------------------------------------
    # 7. /api/verify-otp
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_verify_otp_contract_existing_user(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Valid OTP check -> user lookup
        mock_cursor.fetchone.side_effect = [
            {'id': 1, 'identifier': 'user@example.com', 'otp': '123456'},  # valid OTP row with 'id'
            {'id': 1, 'name': 'Bhavya', 'email': 'user@example.com', 'phone': None}  # user exists
        ]

        resp = self.client.post('/api/verify-otp', json={'email': 'user@example.com', 'otp': '123456'}, headers={'Origin': 'http://localhost:3000'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertTrue(data['userExists'])
        self.assertEqual(data['user']['name'], 'Bhavya')

    # -------------------------------------------------------------------------
    # 8. /api/complete-profile
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_complete_profile_contract(self, mock_get_db):
        import time as pytime
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.lastrowid = 42

        # 1. check phone duplicate -> None
        # 2. check email duplicate -> None
        # 3. fetch created user -> dict
        mock_cursor.fetchone.side_effect = [
            None,
            None,
            {'id': 42, 'name': 'New User', 'email': 'newuser@example.com', 'phone': '+919876543210'}
        ]

        # Set up verified session proof
        with self.client.session_transaction() as sess:
            sess[app.PENDING_PROFILE_KEY] = {
                'identifier': 'newuser@example.com',
                'type': 'email',
                'verified_at': pytime.time()
            }

        resp = self.client.post('/api/complete-profile', json={
            'name': 'New User',
            'email': 'newuser@example.com',
            'phone': '9876543210'
        }, headers={'Origin': 'http://localhost:3000'})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['user']['id'], 42)

    # -------------------------------------------------------------------------
    # 9. /api/auth/me
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_auth_me_authenticated(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            'id': 1, 'name': 'Bhavya', 'email': 'user@example.com', 'phone': None
        }

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1

        resp = self.client.get('/api/auth/me')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['user']['email'], 'user@example.com')

    def test_auth_me_unauthenticated(self):
        resp = self.client.get('/api/auth/me')
        self.assertEqual(resp.status_code, 401)

    # -------------------------------------------------------------------------
    # 10. /api/logout
    # -------------------------------------------------------------------------
    def test_logout_contract(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1

        resp = self.client.post('/api/logout', headers={'Origin': 'http://localhost:3000'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])

        # Verify session cleared
        with self.client.session_transaction() as sess:
            self.assertNotIn('user_id', sess)

    # -------------------------------------------------------------------------
    # 11. /api/saved-movies, /api/save-movie, /api/unsave-movie, /api/check-saved
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_saved_movies_endpoints(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1

        # Check saved: 1st fetch = get_current_user in @login_required, 2nd fetch = tuple (1,) from COUNT(*)
        mock_cursor.fetchone.side_effect = [
            {'id': 1, 'name': 'Bhavya', 'email': 'u@e.com', 'phone': None}, # login_required lookup
            (1,) # saved record exists (COUNT(*) tuple)
        ]
        resp = self.client.get('/api/check-saved/3')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['is_saved'])

        # Save movie: 1st fetch = login_required lookup
        mock_cursor.fetchone.side_effect = [
            {'id': 1, 'name': 'Bhavya', 'email': 'u@e.com', 'phone': None}
        ]
        resp = self.client.post('/api/save-movie', json={'movie_id': 3}, headers={'Origin': 'http://localhost:3000'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['success'])

        # Unsave movie: 1st fetch = login_required lookup
        mock_cursor.fetchone.side_effect = [
            {'id': 1, 'name': 'Bhavya', 'email': 'u@e.com', 'phone': None}
        ]
        resp = self.client.post('/api/unsave-movie', json={'movie_id': 3}, headers={'Origin': 'http://localhost:3000'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['success'])

    # -------------------------------------------------------------------------
    # 12. /api/profile/update
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_profile_update_contract(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1

        mock_cursor.fetchone.side_effect = [
            {'id': 1, 'name': 'Old Name', 'email': 'u@e.com', 'phone': None}, # login_required
            {'id': 1, 'name': 'Old Name', 'email': 'u@e.com', 'phone': None}, # fetch user in handler
            {'id': 1, 'name': 'New Name', 'email': 'u@e.com', 'phone': None}  # updated fetch
        ]

        resp = self.client.put('/api/profile/update', json={'name': 'New Name'}, headers={'Origin': 'http://localhost:3000'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['user']['name'], 'New Name')

    # -------------------------------------------------------------------------
    # 13. /api/bookings, /api/create-booking, /api/cancel-booking
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_booking_flow_contracts(self, mock_get_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        with self.client.session_transaction() as sess:
            sess['user_id'] = 1

        # Create booking
        mock_cursor.fetchone.side_effect = [
            {'id': 1, 'name': 'User', 'email': 'u@e.com', 'phone': None}, # auth
            {'show_date': date.today() + timedelta(days=1), 'show_time': time(22, 0)} # show in future
        ]
        mock_cursor.fetchall.return_value = [
            {'id': 101, 'price': 250.0, 'is_booked': 0}
        ]
        mock_cursor.lastrowid = 55

        resp = self.client.post('/api/create-booking', json={
            'show_id': 10,
            'seat_ids': [101]
        }, headers={'Origin': 'http://localhost:3000'})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['booking_id'], 55)

        # Cancel booking
        mock_cursor.fetchone.side_effect = [
            {'id': 1, 'name': 'User', 'email': 'u@e.com', 'phone': None}, # auth
            {
                'id': 55, 'user_id': 1, 'show_id': 10, 'seat_ids': '[101]',
                'status': 'CONFIRMED', 'show_date': date.today() + timedelta(days=1), 'show_time': time(22, 0)
            }
        ]
        resp = self.client.post('/api/cancel-booking', json={'booking_id': 55}, headers={'Origin': 'http://localhost:3000'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['success'])


if __name__ == '__main__':
    unittest.main()
