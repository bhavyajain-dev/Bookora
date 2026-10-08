"""
Tests for CORS, Cross-Origin Session Cookies, CSRF Origin Verification,
and Frontend-Backend Split Endpoints (Phase 5).
"""
import unittest
import json
import os
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
        """When SameSite=None is configured, Secure is automatically enforced."""
        # Simulated check: verify that app logic ensures Secure=True when SameSite=None
        samesite = app.config.get('SESSION_COOKIE_SAMESITE')
        if samesite and samesite.lower() == 'none':
            self.assertTrue(app.config.get('SESSION_COOKIE_SECURE'))

    def test_logout_clears_session(self):
        """POST /api/logout clears session."""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 100

        response = client.post('/api/logout')
        self.assertEqual(response.status_code, 200)
        with client.session_transaction() as sess:
            self.assertNotIn('user_id', sess)


if __name__ == '__main__':
    unittest.main()
