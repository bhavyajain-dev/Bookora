"""
BOOKORA — API-Only Backend Mode Test Suite

Verifies that:
1. With BOOKORA_API_ONLY=true:
   - GET / returns a JSON service status object, not HTML.
   - /healthz continues returning HTTP 200 {"status": "ok"}.
   - All REST APIs (/api/movies, /api/shows, /api/seats, /api/auth/me, /api/send-otp, etc.) function normally.
   - Template page routes (/movie/<slug>, /shows/<slug>, /seats/<id>, /profile, etc.) return JSON 404.
   - Static file requests (/static/...) and non-API HTML endpoints return JSON 404.
   - CORS, CSRF, session cookies, and authentication operate securely without regression.
2. With BOOKORA_API_ONLY=false (default):
   - Legacy monolithic behavior is preserved (GET / renders index.html, page routes render templates).
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta

import app


class TestApiOnlyMode(unittest.TestCase):
    def setUp(self):
        self.app = app.app
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-12345'
        self.client = self.app.test_client()

    # -------------------------------------------------------------------------
    # 1. API-Only Mode Enabled: Root & Health Check
    # -------------------------------------------------------------------------
    def test_root_returns_json_in_api_only_mode(self):
        """GET / must return a JSON service status response when API-only mode is active."""
        self.app.config['BOOKORA_API_ONLY'] = True
        try:
            resp = self.client.get('/')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.content_type, 'application/json')
            data = resp.get_json()
            self.assertIsInstance(data, dict)
            self.assertEqual(data.get('service'), 'Bookora API')
            self.assertEqual(data.get('status'), 'online')
            self.assertEqual(data.get('mode'), 'api-only')
            self.assertEqual(data.get('health'), '/healthz')
        finally:
            self.app.config['BOOKORA_API_ONLY'] = False

    def test_healthz_remains_operational_in_api_only_mode(self):
        """GET /healthz must return HTTP 200 {"status": "ok"} in API-only mode."""
        self.app.config['BOOKORA_API_ONLY'] = True
        try:
            resp = self.client.get('/healthz')
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data.get('status'), 'ok')
        finally:
            self.app.config['BOOKORA_API_ONLY'] = False

    # -------------------------------------------------------------------------
    # 2. API Endpoints Remain Functional
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_api_movies_functional_in_api_only_mode(self, mock_get_db):
        """GET /api/movies returns the movie list unchanged in API-only mode."""
        self.app.config['BOOKORA_API_ONLY'] = True
        try:
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
            self.assertEqual(data['movies'][0]['slug'], 'chhaava')
        finally:
            self.app.config['BOOKORA_API_ONLY'] = False

    @patch('app.get_db')
    def test_api_shows_and_seats_functional_in_api_only_mode(self, mock_get_db):
        """GET /api/shows and GET /api/seats/<id> function normally in API-only mode."""
        self.app.config['BOOKORA_API_ONLY'] = True
        try:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor

            # 1. Shows endpoint
            mock_cursor.fetchone.return_value = {'id': 1, 'title': 'Chhaava'}
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
            resp_shows = self.client.get('/api/shows?slug=chhaava&date=2026-10-10')
            self.assertEqual(resp_shows.status_code, 200)
            self.assertTrue(resp_shows.get_json()['success'])

            # 2. Seats endpoint
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
            resp_seats = self.client.get('/api/seats/10')
            self.assertEqual(resp_seats.status_code, 200)
            self.assertTrue(resp_seats.get_json()['success'])
        finally:
            self.app.config['BOOKORA_API_ONLY'] = False

    # -------------------------------------------------------------------------
    # 3. Authentication & Sessions in API-Only Mode
    # -------------------------------------------------------------------------
    @patch('app.get_db')
    def test_auth_me_in_api_only_mode(self, mock_get_db):
        """GET /api/auth/me correctly reflects session state in API-only mode."""
        self.app.config['BOOKORA_API_ONLY'] = True
        try:
            # Unauthenticated
            resp_unauth = self.client.get('/api/auth/me')
            self.assertEqual(resp_unauth.status_code, 401)

            # Authenticated
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_get_db.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = {
                'id': 1, 'name': 'Bhavya', 'email': 'user@example.com', 'phone': None
            }

            with self.client.session_transaction() as sess:
                sess['user_id'] = 1

            resp_auth = self.client.get('/api/auth/me')
            self.assertEqual(resp_auth.status_code, 200)
            data = resp_auth.get_json()
            self.assertTrue(data['success'])
            self.assertEqual(data['user']['email'], 'user@example.com')
        finally:
            self.app.config['BOOKORA_API_ONLY'] = False

    # -------------------------------------------------------------------------
    # 4. Page Routes Return JSON 404 in API-Only Mode
    # -------------------------------------------------------------------------
    def test_page_routes_return_404_in_api_only_mode(self):
        """Template rendering page routes must return JSON 404 in API-only mode."""
        self.app.config['BOOKORA_API_ONLY'] = True
        try:
            page_routes = [
                '/movie/chhaava',
                '/shows/chhaava',
                '/seats/10',
                '/profile',
                '/my-bookings',
                '/saved-movies',
                '/movie-details.html',
                '/shows.html',
                '/profile.html',
                '/nonexistent-page'
            ]
            for route in page_routes:
                with self.subTest(route=route):
                    resp = self.client.get(route)
                    self.assertEqual(resp.status_code, 404, f"Route {route} did not return 404")
                    self.assertEqual(resp.content_type, 'application/json')
                    data = resp.get_json()
                    self.assertEqual(data.get('error'), 'Not Found')
        finally:
            self.app.config['BOOKORA_API_ONLY'] = False

    def test_static_assets_return_404_in_api_only_mode(self):
        """Static asset routes (/static/...) must return JSON 404 in API-only mode."""
        self.app.config['BOOKORA_API_ONLY'] = True
        try:
            resp = self.client.get('/static/css/styles.css')
            self.assertEqual(resp.status_code, 404)
            self.assertEqual(resp.content_type, 'application/json')
            data = resp.get_json()
            self.assertEqual(data.get('error'), 'Not Found')
        finally:
            self.app.config['BOOKORA_API_ONLY'] = False

    # -------------------------------------------------------------------------
    # 5. CORS and CSRF Protections Intact in API-Only Mode
    # -------------------------------------------------------------------------
    def test_cors_preflight_in_api_only_mode(self):
        """CORS OPTIONS preflight requests remain functional in API-only mode."""
        self.app.config['BOOKORA_API_ONLY'] = True
        try:
            resp = self.client.options(
                '/api/movies',
                headers={
                    'Origin': 'http://localhost:3000',
                    'Access-Control-Request-Method': 'GET',
                }
            )
            self.assertEqual(resp.status_code, 204)
            self.assertEqual(resp.headers.get('Access-Control-Allow-Origin'), 'http://localhost:3000')
            self.assertEqual(resp.headers.get('Access-Control-Allow-Credentials'), 'true')
        finally:
            self.app.config['BOOKORA_API_ONLY'] = False

    def test_csrf_origin_rejection_in_api_only_mode(self):
        """State-changing requests with unapproved origins are blocked in API-only mode."""
        self.app.config['BOOKORA_API_ONLY'] = True
        try:
            resp = self.client.post(
                '/api/create-booking',
                json={'show_id': 10, 'seat_ids': [101]},
                headers={'Origin': 'http://unauthorized-evil-site.com'}
            )
            self.assertEqual(resp.status_code, 403)
        finally:
            self.app.config['BOOKORA_API_ONLY'] = False

    # -------------------------------------------------------------------------
    # 6. Backward Compatibility: Monolithic Mode Enabled (API-Only Disabled)
    # -------------------------------------------------------------------------
    def test_legacy_monolithic_mode_renders_templates(self):
        """When BOOKORA_API_ONLY is False, root and page routes render HTML templates."""
        self.app.config['BOOKORA_API_ONLY'] = False

        # Root renders index.html
        resp_root = self.client.get('/')
        self.assertEqual(resp_root.status_code, 200)
        self.assertIn('text/html', resp_root.content_type)
        self.assertIn(b'Bookora', resp_root.data)

        # Movie details page renders movie-details.html
        resp_movie = self.client.get('/movie/chhaava')
        self.assertEqual(resp_movie.status_code, 200)
        self.assertIn('text/html', resp_movie.content_type)


if __name__ == '__main__':
    unittest.main()
