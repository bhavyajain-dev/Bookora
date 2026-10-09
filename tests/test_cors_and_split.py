"""
Tests for CORS, Cross-Origin Session Cookies, CSRF Origin Verification,
and Frontend-Backend Split Endpoints (Phase 5).
"""
import unittest
import json
import os
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

# Ensure test execution uses predictable test origins
os.environ['CORS_ALLOWED_ORIGINS'] = 'http://localhost:3000,http://127.0.0.1:3000,https://bookora.onrender.com'
os.environ['SECRET_KEY'] = 'test-secret-key-for-cors-and-split-tests-32chars'
os.environ['DEBUG'] = 'True'

from app import app, _parse_allowed_origins


class TestCorsConfiguration(unittest.TestCase):
    """Test CORS headers, origin whitelisting, preflight OPTIONS, and unauthorized origins."""

    def setUp(self):
        self.client = app.test_client()
        self.allowed_origin = 'http://localhost:3000'
        self.unauthorized_origin = 'https://malicious-site.com'

    def test_allowed_origin_receives_cors_headers_on_get(self):
        """Allowed origin receives Access-Control-Allow-Origin and Credentials."""
        response = self.client.get('/api/movies', headers={'Origin': self.allowed_origin})
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), self.allowed_origin)
        self.assertEqual(response.headers.get('Access-Control-Allow-Credentials'), 'true')
        self.assertIn('Origin', response.headers.get('Vary', ''))

    def test_allowed_origin_render_subdomain(self):
        """Production whitelisted Render origin receives explicit CORS header (never wildcard)."""
        prod_origin = 'https://bookora.onrender.com'
        response = self.client.get('/api/movies', headers={'Origin': prod_origin})
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), prod_origin)
        self.assertNotEqual(response.headers.get('Access-Control-Allow-Origin'), '*')
        self.assertEqual(response.headers.get('Access-Control-Allow-Credentials'), 'true')

    def test_unauthorized_origin_does_not_receive_cors_headers(self):
        """Unauthorized origin gets no Access-Control-Allow-Origin header."""
        response = self.client.get('/api/movies', headers={'Origin': self.unauthorized_origin})
        self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))
        self.assertIsNone(response.headers.get('Access-Control-Allow-Credentials'))

    def test_options_preflight_allowed_origin(self):
        """Preflight OPTIONS request from allowed origin returns 204 with full CORS headers."""
        response = self.client.open(
            '/api/create-booking',
            method='OPTIONS',
            headers={
                'Origin': self.allowed_origin,
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'Content-Type, X-CSRF-Token'
            }
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), self.allowed_origin)
        self.assertEqual(response.headers.get('Access-Control-Allow-Credentials'), 'true')
        self.assertIn('POST', response.headers.get('Access-Control-Allow-Methods', ''))
        self.assertIn('Content-Type', response.headers.get('Access-Control-Allow-Headers', ''))
        self.assertEqual(response.headers.get('Access-Control-Max-Age'), '86400')

    def test_options_preflight_unauthorized_origin_rejected(self):
        """Preflight OPTIONS request from unauthorized origin returns 403 Forbidden."""
        response = self.client.open(
            '/api/create-booking',
            method='OPTIONS',
            headers={
                'Origin': self.unauthorized_origin,
                'Access-Control-Request-Method': 'POST'
            }
        )
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))


class TestCsrfOriginProtection(unittest.TestCase):
    """Test CSRF origin validation on state-changing API endpoints."""

    def setUp(self):
        self.client = app.test_client()
        self.allowed_origin = 'http://localhost:3000'
        self.unauthorized_origin = 'https://evil-attacker.example'

    def test_csrf_rejects_state_changing_post_from_unauthorized_origin(self):
        """State-changing POST with unauthorized Origin header is blocked with 403."""
        response = self.client.post(
            '/api/send-otp',
            headers={'Origin': self.unauthorized_origin},
            json={'email': 'user@example.com'}
        )
        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertFalse(data.get('success'))
        self.assertIn('Cross-origin request rejected', data.get('message', ''))

    def test_csrf_rejects_state_changing_put_from_unauthorized_origin(self):
        """State-changing PUT with unauthorized Origin header is blocked with 403."""
        response = self.client.put(
            '/api/profile/update',
            headers={'Origin': self.unauthorized_origin},
            json={'name': 'Attacker'}
        )
        self.assertEqual(response.status_code, 403)

    def test_csrf_allows_state_changing_post_from_whitelisted_origin(self):
        """State-changing POST with whitelisted Origin proceeds to view logic."""
        response = self.client.post(
            '/api/logout',
            headers={'Origin': self.allowed_origin}
        )
        # Logout succeeds and returns 200
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json().get('success'))

    def test_csrf_allows_same_origin_or_non_browser_requests(self):
        """Requests without Origin (e.g. server-to-server or standard same-origin) pass CSRF check."""
        response = self.client.post('/api/logout')
        self.assertEqual(response.status_code, 200)


class TestAuthMeEndpoint(unittest.TestCase):
    """Test /api/auth/me authentication and IDOR protection."""

    def setUp(self):
        self.client = app.test_client()

    def test_auth_me_unauthenticated_returns_401(self):
        """GET /api/auth/me without active session returns 401 Authentication required."""
        response = self.client.get('/api/auth/me')
        self.assertEqual(response.status_code, 401)
        data = response.get_json()
        self.assertFalse(data.get('success'))
        self.assertEqual(data.get('message'), 'Authentication required')

    @patch('app.get_db')
    def test_auth_me_authenticated_returns_user_profile(self, mock_get_db):
        """GET /api/auth/me with valid session returns authenticated user info."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'id': 42,
            'name': 'Bhavya Jain',
            'email': 'bhavya@example.com',
            'phone': '9876543210'
        }
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        with self.client.session_transaction() as sess:
            sess['user_id'] = 42

        response = self.client.get('/api/auth/me', headers={'Origin': 'http://localhost:3000'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data['user']['id'], 42)
        self.assertEqual(data['user']['name'], 'Bhavya Jain')
        self.assertEqual(data['user']['email'], 'bhavya@example.com')
        self.assertEqual(data['user']['phone'], '9876543210')
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:3000')

    @patch('app.get_db')
    def test_auth_me_cannot_be_manipulated_by_query_params(self, mock_get_db):
        """GET /api/auth/me?user_id=999 ignores parameter and reads only session user ID."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'id': 42,
            'name': 'Legitimate User',
            'email': 'user@example.com',
            'phone': '1234567890'
        }
        mock_conn.cursor.return_value = mock_cursor
        mock_get_db.return_value = mock_conn

        with self.client.session_transaction() as sess:
            sess['user_id'] = 42

        # Attacker attempts to pass a different user_id in query string
        response = self.client.get('/api/auth/me?user_id=999')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        # Must return session user (42), not query user (999)
        self.assertEqual(data['user']['id'], 42)
        self.assertEqual(data['user']['name'], 'Legitimate User')


class TestSessionCookieConfiguration(unittest.TestCase):
    """Test session cookie security attributes under different deployment profiles."""

    def test_session_cookie_httponly_is_true(self):
        """Session cookie HttpOnly is enabled to prevent XSS theft."""
        self.assertTrue(app.config.get('SESSION_COOKIE_HTTPONLY'))

    def test_session_cookie_samesite_none_requires_secure(self):
        """When SameSite=None is configured, Secure and Partitioned are automatically enforced."""
        samesite = app.config.get('SESSION_COOKIE_SAMESITE')
        if samesite and samesite.lower() == 'none':
            self.assertTrue(app.config.get('SESSION_COOKIE_SECURE'))
            self.assertTrue(app.config.get('SESSION_COOKIE_PARTITIONED'))

    def test_set_cookie_includes_partitioned_attribute(self):
        """Cross-site session cookie includes Partitioned attribute (CHIPS) for modern browsers."""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 42

        # Make request to trigger session cookie generation
        response = client.post('/api/logout', headers={'Origin': 'https://bookora.onrender.com'})
        self.assertEqual(response.status_code, 200)

        # Check Set-Cookie headers
        set_cookies = response.headers.getlist('Set-Cookie')
        self.assertTrue(len(set_cookies) > 0)
        cookie_header = set_cookies[0]
        self.assertIn('HttpOnly', cookie_header)
        if app.config.get('SESSION_COOKIE_SAMESITE', '').lower() == 'none':
            self.assertIn('SameSite=None', cookie_header)
            self.assertIn('Secure', cookie_header)
            self.assertIn('Partitioned', cookie_header)

    def test_logout_clears_session(self):
        """POST /api/logout clears session."""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 100

        response = client.post('/api/logout')
        self.assertEqual(response.status_code, 200)
        with client.session_transaction() as sess:
            self.assertNotIn('user_id', sess)


class TestCrossSiteOtpAndBookingSessionFlow(unittest.TestCase):
    """Test full session flow from OTP verification to booking in split cross-site architecture."""

    def setUp(self):
        self.client = app.test_client()
        self.frontend_origin = 'https://bookora.onrender.com'

    @patch('app.get_db')
    def test_otp_verification_issues_partitioned_cookie_and_authorizes_booking(self, mock_get_db):
        """OTP verification generates partitioned session cookie that authorizes subsequent booking."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock OTP verification success for existing user
        mock_cursor.fetchone.side_effect = [
            {'id': 1},                                                    # OTP record exists
            {'id': 42, 'name': 'Bhavya', 'email': 'bhavya@example.com', 'phone': '1234567890'}, # User exists
            {'id': 42, 'name': 'Bhavya', 'email': 'bhavya@example.com', 'phone': '1234567890'}, # Auth check
            {'show_date': date.today() + timedelta(days=2), 'show_time': timedelta(hours=19)},   # Show check
        ]
        mock_cursor.fetchall.return_value = [
            {'id': 101, 'price': 250.0, 'is_booked': 0}                  # Seat check
        ]
        mock_cursor.lastrowid = 777

        # 1. Verify OTP from cross-origin frontend
        verify_resp = self.client.post(
            '/api/verify-otp',
            headers={'Origin': self.frontend_origin},
            json={'email': 'bhavya@example.com', 'otp': '123456', 'type': 'email'}
        )
        self.assertEqual(verify_resp.status_code, 200)
        verify_data = verify_resp.get_json()
        self.assertTrue(verify_data['success'])
        self.assertTrue(verify_data['userExists'])

        # Check Set-Cookie on OTP response
        set_cookies = verify_resp.headers.getlist('Set-Cookie')
        self.assertTrue(len(set_cookies) > 0)
        cookie_header = set_cookies[0]
        self.assertIn('session=', cookie_header)
        self.assertIn('HttpOnly', cookie_header)
        if app.config.get('SESSION_COOKIE_SAMESITE', '').lower() == 'none':
            self.assertIn('SameSite=None', cookie_header)
            self.assertIn('Secure', cookie_header)
            self.assertIn('Partitioned', cookie_header)

        # 2. Subsequent create-booking request carrying the session
        booking_resp = self.client.post(
            '/api/create-booking',
            headers={'Origin': self.frontend_origin},
            json={'show_id': 1, 'seat_ids': [101]}
        )
        self.assertEqual(booking_resp.status_code, 200)
        booking_data = booking_resp.get_json()
        self.assertTrue(booking_data['success'])
        self.assertEqual(booking_data['booking_id'], 777)


if __name__ == '__main__':
    unittest.main()


