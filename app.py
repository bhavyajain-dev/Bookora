"""
Flask Backend for Bookora - Clean Database-Driven API
Rebuilt booking system using MySQL only
"""
import sys

# Force UTF-8 on stdout/stderr before anything can print.
# Windows consoles default to cp1252, which cannot encode the emoji used in the
# startup banner: print() then raises UnicodeEncodeError and kills the process
# before app.run() is ever reached. errors='replace' means an exotic stream can
# degrade a character but never crash the server.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError, OSError):  # pragma: no cover - stream without reconfigure
        pass

from flask import Flask, render_template, request, jsonify, send_from_directory, session, g, make_response
from flask.sessions import SecureCookieSessionInterface
from werkzeug.exceptions import HTTPException
import mysql.connector
from mysql.connector import pooling
from datetime import datetime, timedelta, date
import os
import tempfile
import re
import time
import json
import secrets
import smtplib
import logging
import threading
import urllib.request
import urllib.error
from urllib.parse import urlparse, unquote
from collections import defaultdict, deque, OrderedDict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from dotenv import load_dotenv
from services.show_maintenance import business_now, maintain_upcoming_shows

# Load environment variables
load_dotenv()


def _env_bool(name, default=False):
    """Read a boolean from the environment; 'true'/'1'/'yes'/'on' are true."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    return raw.strip().lower() in ('true', '1', 'yes', 'on')


app = Flask(__name__, template_folder='templates', static_folder='static')


def business_now_naive():
    """India business time for comparisons with MySQL DATE/TIME show fields.

    Show date/time columns intentionally store a local cinema date and time,
    not UTC timestamps.  Keeping the comparison naive after obtaining the time
    in Asia/Kolkata avoids accidentally interpreting those values in the cloud
    host's timezone.
    """
    return business_now().replace(tzinfo=None)

# ============================================
# CONFIGURATION (environment-driven)
#
# flask-cors was removed deliberately: the frontend is served by this same Flask
# app and every fetch() uses a relative /api/... path, so there is no cross-origin
# request to permit. The old configuration also pinned the allowed origins to
# http://localhost:5000, which would have had to change for production anyway.
# ============================================

DEBUG = _env_bool('DEBUG', False)
BOOKORA_API_ONLY = _env_bool('BOOKORA_API_ONLY', False)
app.config['BOOKORA_API_ONLY'] = BOOKORA_API_ONLY


def _is_api_only():
    """Return True if backend is configured to operate in API-only mode (split architecture)."""
    return app.config.get('BOOKORA_API_ONLY', False) or _env_bool('BOOKORA_API_ONLY', False)

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s %(levelname)-8s %(name)s: %(message)s',
)
logger = logging.getLogger('bookora')

# --- Secret key -------------------------------------------------------------
# There is no production fallback on purpose. The Flask session is a *signed*
# cookie, so anyone who knows SECRET_KEY can forge session['user_id'] and act as
# any user. Booting with a shipped default key is therefore a silent, total auth
# bypass - better to refuse to start. DEBUG keeps a fixed local key so the dev
# server and its reloader stay usable without any setup.
_DEV_SECRET_KEY = 'dev-only-insecure-key-not-for-production'
_INSECURE_SECRET_KEYS = {
    _DEV_SECRET_KEY,
    'dev-secret-key-change-in-production',  # the previous hardcoded fallback
    'changeme', 'change-me', 'secret', 'password',
}
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = _DEV_SECRET_KEY
        logger.warning(
            'SECRET_KEY is not set - falling back to an insecure development key. '
            'Set SECRET_KEY in the environment before deploying.'
        )
    else:
        raise RuntimeError(
            'SECRET_KEY environment variable is required when DEBUG=False. '
            'Generate one with:  python -c "import secrets; print(secrets.token_hex(32))"'
        )
elif SECRET_KEY.strip().lower() in _INSECURE_SECRET_KEYS and not DEBUG:
    raise RuntimeError(
        'SECRET_KEY is set to a known placeholder value and cannot be used when '
        'DEBUG=False. Generate a real secret with:  '
        'python -c "import secrets; print(secrets.token_hex(32))"'
    )
app.config['SECRET_KEY'] = SECRET_KEY

# --- CORS & Allowed Origins Configuration -----------------------------------
# Explicit origin whitelisting: comma-separated list of approved frontend origins.
# NEVER use wildcard '*' with credentialed sessions.
def _parse_allowed_origins():
    raw = os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000')
    return {origin.strip().rstrip('/') for origin in raw.split(',') if origin.strip()}


# --- Session cookie & Partitioned CHIPS Support ------------------------------
# Flask signs the session cookie with SECRET_KEY, so the client cannot forge or
# alter the authenticated user id - the server is the source of truth for identity.
app.config['SESSION_COOKIE_HTTPONLY'] = True   # JS cannot read the session cookie (mitigates XSS token theft)

# Detect if running in cross-origin / cross-site mode (e.g. Render separated frontend/backend)
_allowed_origins_set = _parse_allowed_origins()
_has_https_origins = any(orig.startswith('https://') for orig in _allowed_origins_set)
_is_cross_site = (
    _env_bool('CROSS_SITE_DEPLOYMENT', False)
    or _env_bool('BOOKORA_CROSS_ORIGIN_PROD', False)
    or _env_bool('BOOKORA_API_ONLY', False)
    or _has_https_origins
)

# SameSite & Secure:
# When frontend and backend are on separate Render domains (*.onrender.com),
# browsers require SameSite=None and Secure=True for cross-origin session cookies.
# Modern Chrome (CHIPS) also requires the Partitioned attribute on cross-site cookies.
# For same-site / custom domains or local monolithic, Lax is preferred.
_default_samesite = 'None' if _is_cross_site else 'Lax'
_samesite_val = os.getenv('SESSION_COOKIE_SAMESITE', _default_samesite)
app.config['SESSION_COOKIE_SAMESITE'] = _samesite_val

if _samesite_val and _samesite_val.lower() == 'none':
    # Browsers strictly reject SameSite=None without Secure=True
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_PARTITIONED'] = _env_bool('SESSION_COOKIE_PARTITIONED', True)
else:
    app.config['SESSION_COOKIE_SECURE'] = _env_bool('SESSION_COOKIE_SECURE', not DEBUG)
    app.config['SESSION_COOKIE_PARTITIONED'] = _env_bool('SESSION_COOKIE_PARTITIONED', False)

# Custom session interface ensuring Partitioned attribute is serialized to Set-Cookie
class PartitionedSecureCookieSessionInterface(SecureCookieSessionInterface):
    """
    Session interface with CHIPS (Cookies Having Independent Partitioned State)
    and cross-origin SameSite=None support for modern partitioned storage in Chrome.
    """
    def get_cookie_partitioned(self, app):
        return app.config.get('SESSION_COOKIE_PARTITIONED', False)

    def save_session(self, app, session, response):
        name = self.get_cookie_name(app)
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)
        secure = self.get_cookie_secure(app)
        samesite = self.get_cookie_samesite(app)
        httponly = self.get_cookie_httponly(app)
        partitioned = self.get_cookie_partitioned(app)

        if not session:
            if session.modified:
                response.delete_cookie(
                    name,
                    domain=domain,
                    path=path,
                    secure=secure,
                    samesite=samesite,
                    httponly=httponly,
                    partitioned=partitioned,
                )
            return

        if not self.should_set_cookie(app, session):
            return

        expires = self.get_expiration_time(app, session)
        val = self.get_signing_serializer(app).dumps(dict(session))
        response.set_cookie(
            name,
            val,
            expires=expires,
            httponly=httponly,
            domain=domain,
            path=path,
            secure=secure,
            samesite=samesite,
            partitioned=partitioned,
        )

app.session_interface = PartitionedSecureCookieSessionInterface()

# Optional cookie domain (do not set unless explicitly required)
_cookie_domain = os.getenv('SESSION_COOKIE_DOMAIN', '').strip()
if _cookie_domain:
    app.config['SESSION_COOKIE_DOMAIN'] = _cookie_domain

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=int(os.getenv('SESSION_LIFETIME_DAYS', '7')))

# X-Forwarded-For is client-settable, so it is only trusted when the deployment
# explicitly declares that it sits behind a trusted reverse proxy. Otherwise a
# single attacker could evade the per-IP OTP limits by spoofing the header.
TRUST_PROXY_HEADERS = _env_bool('TRUST_PROXY_HEADERS', False)


@app.before_request
def handle_cors_preflight_and_csrf():
    allowed_origins = _parse_allowed_origins()
    origin = request.headers.get('Origin')
    
    # 1. Handle CORS preflight (OPTIONS)
    if request.method == 'OPTIONS':
        if origin and origin.rstrip('/') in allowed_origins:
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-CSRF-Token, Authorization, X-Requested-With, X-Bookora-Request'
            response.headers['Access-Control-Max-Age'] = '86400'
            response.headers['Vary'] = 'Origin'
            return response
        return jsonify({'error': 'CORS preflight origin not allowed'}), 403

    # 2. CSRF Origin Verification on state-changing API requests
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH') and request.path.startswith('/api/'):
        if origin:
            clean_origin = origin.rstrip('/')
            if clean_origin not in allowed_origins:
                # In monolithic mode, Origin may match backend's own host_url
                host_url = request.host_url.rstrip('/')
                if clean_origin != host_url:
                    logger.warning('CSRF rejected: Origin %s not in allowed origins or host (ip=%s)', origin, _client_ip())
                    return jsonify({'success': False, 'message': 'Cross-origin request rejected'}), 403


@app.after_request
def apply_cors_and_security_headers(response):
    allowed_origins = _parse_allowed_origins()
    origin = request.headers.get('Origin')
    if origin and origin.rstrip('/') in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Vary'] = 'Origin'
    return response

# --- Email / OTP Transport --------------------------------------------------
EMAIL_PROVIDER = os.getenv('EMAIL_PROVIDER', '').strip().lower()
BREVO_API_KEY = os.getenv('BREVO_API_KEY')
RESEND_API_KEY = os.getenv('RESEND_API_KEY')

EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_FROM = os.getenv('EMAIL_FROM', EMAIL_USER)
EMAIL_FROM_NAME = os.getenv('EMAIL_FROM_NAME', 'Bookora')


def _get_email_provider():
    """Determine active email transport: 'brevo', 'resend', or 'smtp'.

    Precedence:
      1. Explicit EMAIL_PROVIDER ('brevo', 'resend', 'smtp').
      2. Inferred from present API keys (BREVO_API_KEY -> 'brevo', RESEND_API_KEY -> 'resend').
      3. Default fallback to 'smtp' (preserves local development with Gmail).
    """
    provider = os.getenv('EMAIL_PROVIDER', '').strip().lower() or EMAIL_PROVIDER
    if provider in ('brevo', 'resend', 'smtp'):
        return provider
    if os.getenv('BREVO_API_KEY') or BREVO_API_KEY:
        return 'brevo'
    if os.getenv('RESEND_API_KEY') or RESEND_API_KEY:
        return 'resend'
    return 'smtp'


if not DEBUG:
    _active_email_provider = _get_email_provider()
    if _active_email_provider == 'brevo' and not BREVO_API_KEY:
        raise RuntimeError(
            'BREVO_API_KEY environment variable is required when EMAIL_PROVIDER=brevo.'
        )
    elif _active_email_provider == 'resend' and not RESEND_API_KEY:
        raise RuntimeError(
            'RESEND_API_KEY environment variable is required when EMAIL_PROVIDER=resend.'
        )
    elif _active_email_provider == 'smtp' and not (EMAIL_USER and EMAIL_PASSWORD):
        raise RuntimeError(
            'EMAIL_USER and EMAIL_PASSWORD environment variables are required when '
            'using SMTP with DEBUG=False. In cloud environments where outbound SMTP '
            'ports are blocked (such as Render Free), set EMAIL_PROVIDER=brevo and '
            'BREVO_API_KEY (or RESEND_API_KEY).'
        )

# ============================================
# DATABASE (environment-driven, pooled)
# ============================================


def _parse_database_url():
    """Extract database connection parameters from DATABASE_URL or MYSQL_URL if present."""
    raw_url = os.getenv('DATABASE_URL') or os.getenv('MYSQL_URL')
    if not raw_url or not raw_url.strip():
        return {}
    raw_url = raw_url.strip().strip("'\"")
    if '://' in raw_url:
        _, remainder = raw_url.split('://', 1)
        normalized_url = f'mysql://{remainder}'
    else:
        normalized_url = f'mysql://{raw_url}'

    try:
        parsed = urlparse(normalized_url)
        params = {}
        if parsed.hostname:
            params['host'] = parsed.hostname.strip()
        if parsed.port:
            params['port'] = int(parsed.port)
        if parsed.username:
            params['user'] = unquote(parsed.username).strip()
        if parsed.password:
            params['password'] = unquote(parsed.password)
        if parsed.path and parsed.path.strip('/'):
            params['database'] = unquote(parsed.path.strip('/')).strip()
        return params
    except Exception as exc:
        logger.warning('Failed to parse DATABASE_URL / MYSQL_URL: %s', exc)
        return {}


_PARSED_DB_URL = _parse_database_url()


def _get_clean_env(name, aliases=()):
    """Retrieve an environment variable or its aliases, stripping quotes and whitespace."""
    for key in (name, *aliases):
        val = os.getenv(key)
        if val is not None:
            cleaned = val.strip().strip("'\"")
            if cleaned != '':
                return cleaned
    return None


def _db_setting(name, dev_default, aliases=(), url_key=None):
    """Database settings come from the environment or DATABASE_URL.
    
    Local development keeps the XAMPP defaults for convenience, but in
    production every value must be supplied explicitly - the app must never be
    able to quietly fall back to localhost / root / no-password against a real deployment.
    """
    env_val = _get_clean_env(name, aliases)
    if env_val is not None:
        return env_val

    if url_key and url_key in _PARSED_DB_URL:
        return _PARSED_DB_URL[url_key]

    if DEBUG:
        return dev_default

    raise RuntimeError(
        f'{name} environment variable is required when DEBUG=False '
        '(localhost/root defaults are development-only).'
    )


def _db_port():
    """Retrieve database port with validation against silent default errors in production.

    In development (DEBUG=True), defaults to 3306 for local XAMPP.
    In production (DEBUG=False), DB_PORT must be specified (or extracted from DATABASE_URL)
    because cloud services like Aiven MySQL listen on assigned high ports (e.g. 15053).
    Defaulting to 3306 in production causes immediate TCP connection failure (InterfaceError: 2003).
    """
    raw_port = _get_clean_env('DB_PORT', ('MYSQL_PORT', 'MYSQLPORT'))
    if raw_port is not None:
        try:
            return int(raw_port)
        except ValueError:
            raise RuntimeError(f'Invalid DB_PORT: {raw_port!r} must be an integer.')

    if 'port' in _PARSED_DB_URL:
        return int(_PARSED_DB_URL['port'])

    if DEBUG:
        return 3306

    raise RuntimeError(
        'DB_PORT environment variable is required when DEBUG=False '
        '(e.g., Aiven port like 15053). Defaulting to 3306 in production is not allowed.'
    )


_db_password = _get_clean_env('DB_PASSWORD', ('MYSQL_PASSWORD', 'MYSQLPASSWORD', 'MYSQL_PWD'))
if _db_password is None and 'password' in _PARSED_DB_URL:
    _db_password = _PARSED_DB_URL['password']

if _db_password is None or _db_password == '':
    if not DEBUG:
        raise RuntimeError('DB_PASSWORD environment variable is required when DEBUG=False.')
    _db_password = ''


DB_CONFIG = {
    'host': _db_setting('DB_HOST', 'localhost', aliases=('MYSQL_HOST', 'MYSQLHOST'), url_key='host'),
    'port': _db_port(),
    'user': _db_setting('DB_USER', 'root', aliases=('MYSQL_USER', 'MYSQLUSER', 'MYSQL_USERNAME'), url_key='user'),
    'database': _db_setting('DB_NAME', 'bookora', aliases=('DB_DATABASE', 'MYSQL_DATABASE', 'MYSQLDATABASE'), url_key='database'),
    'password': _db_password,
    'charset': 'utf8mb4',
    # Connection timeout in seconds to prevent indefinitely hanging on unresponsive sockets
    'connection_timeout': int(os.getenv('DB_CONNECT_TIMEOUT', '10')),
    # Buffered cursors by default. This is the actual guarantee behind the
    # explicit buffered=True at every conn.cursor(...) call site below: a
    # connection-level default also covers any cursor opened without the keyword,
    # so the invariant cannot be broken by forgetting it once.
    #
    # Why it matters here specifically: connections are POOLED, and conn.close()
    # hands the connection to the next request instead of closing the socket.
    # mysql-connector's default (unbuffered) cursor streams rows, so a SELECT
    # whose rows are not fully consumed - fetchone() on a query that can match
    # more than one row, or an early `return` between execute() and the fetch -
    # leaves the connection holding unread results. The next borrower then fails
    # with InternalError("Unread result found") on a completely unrelated query.
    # A buffered cursor reads the whole result set during execute(), so there is
    # never an unread result to leak. Every query in this app already consumes
    # its rows immediately, so nothing about the queries themselves changes.
    'buffered': True,
}


def _resolve_ssl_ca():
    """Resolve the SSL CA certificate file path.

    Supports:
      1. Direct PEM certificate content via DB_SSL_CA_CERT or DB_SSL_CA_CONTENT
         (or DB_SSL_CA containing the PEM text directly). The certificate is
         written to a temporary file so mysql-connector can verify against it
         without requiring ca.pem to be committed to version control.
      2. A path to an existing certificate file via DB_SSL_CA (e.g. 'ca.pem'
         locally or '/etc/secrets/ca.pem' via Render Secret Files).
    """
    ca_path = _get_clean_env('DB_SSL_CA', ('MYSQL_SSL_CA',))
    ca_content = _get_clean_env('DB_SSL_CA_CERT', ('DB_SSL_CA_CONTENT', 'MYSQL_SSL_CA_CERT'))

    if ca_path and 'BEGIN CERTIFICATE' in ca_path:
        ca_content = ca_path
        ca_path = None

    if ca_content and ca_content.strip():
        clean_pem = ca_content.replace('\\n', '\n').strip() + '\n'
        target_path = os.path.join(tempfile.gettempdir(), 'bookora-aiven-ca.pem')
        try:
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(clean_pem)
            return target_path
        except Exception as exc:
            logger.warning('Failed to write DB_SSL_CA_CERT to temporary file: %s', exc)

    if ca_path:
        if os.path.isabs(ca_path) and os.path.exists(ca_path):
            return ca_path
        base_dir = os.path.abspath(os.path.dirname(__file__))
        candidate = os.path.join(base_dir, ca_path)
        if os.path.exists(candidate):
            return candidate

        logger.warning(
            'Configured DB_SSL_CA file "%s" does not exist on disk. '
            'Skipping invalid path so connection does not fail on missing file.',
            ca_path
        )
        return None

    return None


# Optional TLS to a hosted database, configured entirely through env vars. When
# none of these are set the connection behaves exactly as before, so local XAMPP
# is unaffected.
_db_ssl_ca = _resolve_ssl_ca()
if _db_ssl_ca:
    DB_CONFIG['ssl_ca'] = _db_ssl_ca
    DB_CONFIG['ssl_verify_cert'] = _env_bool('DB_SSL_VERIFY_CERT', True)
elif _env_bool('DB_SSL_DISABLED', False):
    DB_CONFIG['ssl_disabled'] = True
elif not DEBUG and ('aivencloud.com' in str(DB_CONFIG.get('host', '')) or _env_bool('DB_SSL_REQUIRED', False)):
    # If connecting to Aiven MySQL without a specific CA file, enable TLS with system certs
    DB_CONFIG['ssl_verify_cert'] = _env_bool('DB_SSL_VERIFY_CERT', False)

# Per-process pool. Under Gunicorn each worker builds its own, so the total
# connection count is DB_POOL_SIZE x worker count - keep that under the hosted
# database's connection limit.
DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '5'))

_db_pool = None
_db_pool_lock = threading.Lock()


def _get_pool():
    """Build the connection pool on first use rather than at import time, so the
    process still starts (and /healthz still answers) if the database happens to
    be briefly unreachable at boot.
    """
    global _db_pool
    if _db_pool is None:
        with _db_pool_lock:
            if _db_pool is None:
                target_host = DB_CONFIG.get('host')
                target_port = DB_CONFIG.get('port')
                target_user = DB_CONFIG.get('user')
                target_database = DB_CONFIG.get('database')
                has_ssl = bool(DB_CONFIG.get('ssl_ca') or DB_CONFIG.get('ssl_verify_cert'))

                logger.info(
                    'Initializing MySQL connection pool (host=%s, port=%s, user=%s, db=%s, ssl=%s, pool_size=%s)',
                    target_host, target_port, target_user, target_database, has_ssl, DB_POOL_SIZE
                )

                try:
                    _db_pool = pooling.MySQLConnectionPool(
                        pool_name='bookora_pool',
                        pool_size=DB_POOL_SIZE,
                        pool_reset_session=True,
                        **DB_CONFIG,
                    )
                    logger.info('MySQL connection pool created successfully (size=%s)', DB_POOL_SIZE)
                except mysql.connector.Error as exc:
                    logger.critical(
                        'Failed to establish MySQL connection to %s:%s (database=%s, user=%s, ssl=%s): %s',
                        target_host, target_port, target_database, target_user, has_ssl, exc
                    )
                    raise
        _ensure_background_scheduler()
    return _db_pool


_maintenance_thread_started = False
_maintenance_thread_lock = threading.Lock()


def run_show_maintenance_job():
    """Run show maintenance safely under an advisory lock on a dedicated connection.

    Safe across multiple Gunicorn workers: only the worker that acquires the advisory
    lock performs the maintenance run; all others skip immediately.
    """
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT GET_LOCK('bookora_show_maintenance', 0)")
        lock_res = cursor.fetchone()
        has_lock = lock_res and lock_res[0] == 1
        cursor.close()

        if not has_lock:
            logger.debug('Show maintenance skipped: another process holds the advisory lock.')
            conn.close()
            return None

        try:
            result = maintain_upcoming_shows(conn)
            if result.get('created_shows', 0) > 0:
                logger.info(
                    'Background show maintenance completed: %s shows and %s seats created for %s through %s',
                    result['created_shows'], result['created_seats'], result['today'], result['horizon']
                )
            else:
                logger.info('Background show maintenance: 7-day rolling window is fully up to date.')
            return result
        finally:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT RELEASE_LOCK('bookora_show_maintenance')")
                cursor.fetchone()
                cursor.close()
            except Exception:
                pass
            conn.close()
    except Exception as exc:
        logger.warning('Background show maintenance failed: %s', exc)
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return None


def _ensure_background_scheduler():
    """Start background show maintenance thread once per process."""
    global _maintenance_thread_started
    if not _maintenance_thread_started and not _env_bool('DISABLE_SHOW_MAINTENANCE', False):
        with _maintenance_thread_lock:
            if not _maintenance_thread_started:
                _maintenance_thread_started = True

                def _loop():
                    # Initial brief pause so worker process can finish bootstrapping
                    time.sleep(5)
                    while True:
                        try:
                            run_show_maintenance_job()
                        except Exception as e:
                            logger.warning('Periodic show maintenance encountered an error: %s', e)
                        # Check twice daily (every 12 hours)
                        time.sleep(12 * 3600)

                t = threading.Thread(target=_loop, daemon=True, name='show-maintenance-worker')
                t.start()
                logger.info('Background show maintenance thread initialized.')


def get_db():
    """
    Check out a connection from the pool.

    Callers keep calling conn.close() exactly as before; on a pooled connection
    that returns it to the pool instead of tearing down the socket. Connections
    are also tracked on `g` so _release_db_connections() can reclaim any that an
    early return or an exception skipped - with a pool, a leaked connection is
    gone for good and enough of them deadlock the app.
    """
    conn = _get_pool().get_connection()
    # Hosted MySQL closes idle connections, so a pooled socket can be dead by the
    # time it is checked out. Reviving it here turns a guaranteed 500 into a
    # transparent reconnect.
    try:
        conn.ping(reconnect=True, attempts=2, delay=0)
    except mysql.connector.Error:
        try:
            if hasattr(conn, '_cnx') and conn._cnx is not None:
                conn.close()
        except Exception:
            pass
        conn = _get_pool().get_connection()

    if not hasattr(g, '_db_connections'):
        g._db_connections = []
    g._db_connections.append(conn)
    return conn


@app.teardown_appcontext
def _release_db_connections(exception=None):
    """Return any pooled connection the request handler did not close itself.

    Also rolls back first. A pooled connection is reused by the next request, so
    an uncommitted transaction left behind by a handler that raised part-way
    through would otherwise still be open when someone else borrows it - and its
    row locks would still be held. Every handler that writes now rolls back on its
    own error path; this is the backstop for the paths that never got that far.
    """
    for conn in getattr(g, '_db_connections', ()):
        try:
            conn.rollback()
        except Exception:
            # Already returned to the pool by the handler, or never had an open
            # transaction. Either way there is nothing to undo.
            pass
        try:
            if hasattr(conn, '_cnx'):
                if conn._cnx is not None:
                    conn.close()
            else:
                conn.close()
        except Exception:
            pass
    g._db_connections = []


# ============================================
# ERROR RESPONSES
# ============================================

GENERIC_ERROR_MESSAGE = 'Something went wrong. Please try again.'


def _server_error(context, message=GENERIC_ERROR_MESSAGE):
    """
    Log the real exception server-side and return a generic message to the client.

    Raw exception text is never returned: driver errors routinely contain the SQL
    statement, table and column names, the database host and the connected user,
    all of which hand an attacker a free map of the backend. Must be called from
    inside an `except` block so logger.exception() can capture the traceback -
    which is strictly more diagnostic than the old print(f"...{e}") ever was.
    """
    logger.exception('%s failed', context)
    return jsonify({'success': False, 'message': message}), 500


def _rate_limited(message, retry_after):
    """429 with a Retry-After header. The frontend already renders data.message."""
    response = jsonify({'success': False, 'message': message})
    response.headers['Retry-After'] = str(retry_after)
    return response, 429


if not DEBUG:
    @app.errorhandler(Exception)
    def _handle_unexpected_exception(error):
        """
        Last line of defence in production: an exception escaping a route must not
        reach the client as a traceback. Only registered when DEBUG is off so the
        interactive debugger still works locally.
        """
        if isinstance(error, HTTPException):
            return error
        logger.exception('Unhandled exception on %s %s', request.method, request.path)
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'message': GENERIC_ERROR_MESSAGE}), 500
        return 'Internal Server Error', 500


# ============================================
# OTP POLICY, VALIDATION AND RATE LIMITING
# ============================================

OTP_LENGTH = 6
OTP_TTL_MINUTES = int(os.getenv('OTP_TTL_MINUTES', '10'))
OTP_MAX_VERIFY_ATTEMPTS = int(os.getenv('OTP_MAX_VERIFY_ATTEMPTS', '5'))
OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv('OTP_RESEND_COOLDOWN_SECONDS', '45'))
OTP_WINDOW_MINUTES = int(os.getenv('OTP_WINDOW_MINUTES', '15'))
OTP_MAX_SENDS_PER_EMAIL = int(os.getenv('OTP_MAX_SENDS_PER_EMAIL', '5'))
OTP_MAX_SENDS_PER_IP = int(os.getenv('OTP_MAX_SENDS_PER_IP', '20'))
OTP_MAX_VERIFIES_PER_IP = int(os.getenv('OTP_MAX_VERIFIES_PER_IP', '30'))

# How long a successful OTP verification stays usable as proof for
# POST /api/complete-profile. The client shows a 2.5s success animation and then
# a short form, so this only has to cover form-filling time; keeping it well
# under the session lifetime limits how long a one-shot signup credential lives.
PENDING_PROFILE_TTL_MINUTES = int(os.getenv('PENDING_PROFILE_TTL_MINUTES', '15'))

# Session key holding proof that an identifier was just verified by OTP but has
# no account yet. It is the ONLY thing /api/complete-profile will trust as the
# identity being registered.
PENDING_PROFILE_KEY = 'pending_profile'

# Full RFC 5322 is not worth implementing here; this rejects the shapes that
# actually matter (missing @, no dot in the domain, whitespace, multiple @).
# Server-side validation is the point: the client-side check in signin-modal.js
# is bypassed entirely by a direct POST.
EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$')
EMAIL_MAX_LENGTH = 100  # matches otp_verification.identifier VARCHAR(100)


def is_valid_email(value):
    """True if `value` is a plausible email address that fits the identifier column."""
    return bool(value) and len(value) <= EMAIL_MAX_LENGTH and EMAIL_RE.match(value) is not None


def mask_email(value):
    """
    Partially redact an address for logging. Server logs are frequently shipped
    to third-party aggregators, so full addresses do not belong in them.
    """
    if not value or '@' not in value:
        return '<redacted>'
    local, _, domain = value.partition('@')
    return f'{local[:2]}***@{domain}'


class SlidingWindowLimiter:
    """
    Minimal in-process sliding-window counter.

    SCOPE WARNING - read this before tuning the numbers above.

    This limiter lives in one Python process. Under `gunicorn -w N` (see Procfile)
    every worker keeps its own copy, so each published limit is really "limit per
    worker" and the cluster-wide ceiling is limit x N; counters also reset on every
    restart or deploy. It is therefore development / single-instance protection,
    not an exact production control.

    Which OTP limits ARE cluster-wide today, with no extra infrastructure:

      * the resend cooldown  - anchored on otp_verification.created_at in MySQL
                               (see send_otp), so it is exact across workers AND
                               hosts and survives restarts;
      * code invalidation    - crossing OTP_MAX_VERIFY_ATTEMPTS expires the row in
                               MySQL, which every worker immediately sees.

    Which are still per-worker (approximate):

      * the per-IP send and verify windows;
      * the per-identifier send count inside OTP_WINDOW_MINUTES;
      * the wrong-guess counter that decides WHEN to invalidate (the invalidation
        itself is durable, only the threshold is counted per worker).

    Making those exact needs storage shared by all workers. Deliberately NOT done
    here: a SQLite file adds a writable-path requirement, a busy-timeout/fail-open
    decision and per-host-only accuracy, and it would make limits survive restarts
    in a way that locks developers out of their own address. The correct upgrade is
    Redis + flask-limiter, which is documented in DEPLOYMENT_READINESS_REPORT.md
    and needs infrastructure this deployment does not yet have. Until then, size
    the env vars for the worker count: the effective ceiling is value x workers.
    """

    _MAX_KEYS = 10000  # crude bound so a rotating-identifier attack cannot grow the dict forever
    _MIN_PRUNE_INTERVAL = 10  # seconds; keeps the O(n) sweep off the hot path

    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_prune = 0.0

    def hit(self, key, limit, window_seconds, min_interval_seconds=0):
        """
        Record an event against `key`.

        Returns (allowed, retry_after_seconds, reason) where reason is 'interval'
        when the minimum spacing between events was violated, 'window' when the
        per-window limit is exhausted, and None when allowed.
        """
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._hits[key]
            while events and events[0] <= cutoff:
                events.popleft()

            if min_interval_seconds and events:
                elapsed = now - events[-1]
                if elapsed < min_interval_seconds:
                    return False, int(min_interval_seconds - elapsed) + 1, 'interval'

            if len(events) >= limit:
                return False, max(int(events[0] + window_seconds - now) + 1, 1), 'window'

            events.append(now)
            # Time-gated: once the dictionary is over the cap the sweep can find
            # nothing to drop (every key still in-window), and re-running it on
            # every request would hold the lock for an O(n) scan each time.
            if (len(self._hits) > self._MAX_KEYS
                    and now - self._last_prune >= self._MIN_PRUNE_INTERVAL):
                self._last_prune = now
                self._prune(cutoff)
            return True, 0, None

    def _prune(self, cutoff):
        """Drop keys whose most recent event has aged out. Caller holds the lock."""
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[key]


_otp_send_limiter = SlidingWindowLimiter()
_otp_verify_limiter = SlidingWindowLimiter()

# Failed verification attempts per identifier, so a live OTP can be invalidated
# after too many wrong guesses. The counter is in-memory (and therefore per
# worker), but the invalidation is durable: crossing the limit expires the row in
# MySQL, which every worker then sees.
_otp_attempts = OrderedDict()
_otp_attempts_lock = threading.Lock()
_OTP_ATTEMPTS_MAX_KEYS = 10000


def _register_failed_attempt(identifier):
    """Increment and return the failed-attempt count for `identifier`."""
    with _otp_attempts_lock:
        count = _otp_attempts.pop(identifier, 0) + 1
        _otp_attempts[identifier] = count  # re-inserting moves it to the MRU end
        # Bounded LRU eviction. This used to .clear() the whole dictionary once it
        # passed the cap, which handed every identifier under active attack a free
        # reset of its wrong-guess budget. Dropping only the least-recently-touched
        # key keeps the memory bound without that side effect.
        while len(_otp_attempts) > _OTP_ATTEMPTS_MAX_KEYS:
            _otp_attempts.popitem(last=False)
        return count


def _reset_otp_attempts(identifier):
    """Clear the attempt budget - on success, invalidation, or a freshly sent code."""
    with _otp_attempts_lock:
        _otp_attempts.pop(identifier, None)


# Longest X-Forwarded-For element worth keeping. An IPv6 address with a zone id
# fits well inside this; anything longer is padding, and it would otherwise become
# a dictionary key in the limiter above.
_MAX_IP_KEY_LENGTH = 64


def _client_ip():
    """
    Best-effort client IP for rate limiting.

    X-Forwarded-For is client-settable, so it is only honoured when the operator
    sets TRUST_PROXY_HEADERS=True. Trusting it unconditionally would let one
    attacker mint unlimited fake IPs and walk straight past the per-IP limits.

    Even when the header IS trusted, the RIGHTMOST element is used rather than the
    leftmost. A proxy APPENDS the peer address it saw to whatever the client
    already sent, so the leftmost value is still attacker-supplied text - reading
    it would have left the per-IP limits forgeable by anyone willing to set the
    header themselves. The rightmost element is the one the trusted edge wrote.
    (With more than one trusted proxy in front of the app this yields the innermost
    proxy's address, which merges buckets rather than splitting them - degraded
    accuracy, not a bypass.)
    """
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            candidate = forwarded.rsplit(',', 1)[-1].strip()
            if candidate:
                return candidate[:_MAX_IP_KEY_LENGTH]
    return request.remote_addr or 'unknown'


# Phone number normalization helper
def normalize_phone(phone):
    """
    Normalize phone number to 10-digit format (no +91 prefix)
    Returns normalized phone or None if invalid
    """
    if not phone:
        return None
    
    # Convert to string and remove all whitespace
    phone = str(phone).strip().replace(' ', '').replace('-', '')
    
    # Remove +91 prefix if present
    if phone.startswith('+91'):
        phone = phone[3:]
    elif phone.startswith('91') and len(phone) == 12:
        phone = phone[2:]
    
    # Validate it's exactly 10 digits
    if len(phone) == 10 and phone.isdigit():
        return phone
    
    return None

# ============================================
# AUTHENTICATION HELPERS (server-side session)
# ============================================

def get_current_user():
    """
    Return the currently authenticated user based on the server-side session.

    Identity comes from session['user_id'], which is set only after a successful
    OTP verification / profile completion. The signed session cookie cannot be
    forged or altered by the client, so the server — not the request body/query —
    decides who the user is. Returns the user dict, or None if there is no valid
    session or the referenced user no longer exists.
    """
    # Resolve at most once per request.
    if 'current_user' in g:
        return g.current_user

    user_id = session.get('user_id')
    if not user_id:
        g.current_user = None
        return None

    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute(
            "SELECT id, name, email, phone FROM users WHERE id = %s",
            (user_id,)
        )
        user = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    # Session points at a user that no longer exists — clear the stale session.
    if not user:
        session.pop('user_id', None)

    g.current_user = user
    return user


def login_required(view):
    """
    Decorator that rejects unauthenticated requests with HTTP 401 and otherwise
    exposes the authenticated user as g.current_user to the wrapped view.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'message': 'Authentication required'}), 401
        g.current_user = user
        return view(*args, **kwargs)
    return wrapped

# ============================================
# MOVIE APIs
# ============================================

@app.route('/api/movies/slug/<slug>', methods=['GET'])
def get_movie_by_slug(slug):
    """Get movie details by slug"""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)
        
        cursor.execute("SELECT * FROM movies WHERE slug = %s", (slug,))
        movie = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if not movie:
            return jsonify({'success': False, 'message': 'Movie not found'}), 404
        
        return jsonify({'success': True, 'movie': movie}), 200

    except Exception:
        return _server_error('GET /api/movies/slug')

@app.route('/api/movies', methods=['GET'])
def get_all_movies():
    """Get all movies"""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)
        
        cursor.execute("SELECT * FROM movies WHERE status = 'now_showing' ORDER BY title")
        movies = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'movies': movies, 'count': len(movies)}), 200

    except Exception:
        return _server_error('GET /api/movies')

# ============================================
# SHOWS APIs
# ============================================

@app.route('/api/shows', methods=['GET'])
def get_shows():
    """Get shows for a movie on a specific date - accepts slug or movie_id"""
    try:
        # Accept either slug or movie_id
        slug = request.args.get('slug')
        movie_id = request.args.get('movie_id')
        requested_date = request.args.get('date')
        
        if not requested_date:
            return jsonify({'success': False, 'message': 'date parameter required'}), 400
        try:
            requested_date = datetime.strptime(requested_date, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'date must use YYYY-MM-DD'}), 400
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)
        
        # Resolve slug to movie_id if slug provided
        if slug and not movie_id:
            cursor.execute("SELECT id, title FROM movies WHERE slug = %s", (slug,))
            movie = cursor.fetchone()
            
            if not movie:
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': 'Movie not found'}), 404

            movie_id = movie['id']

        if not movie_id:
            # Close before returning: this branch is reachable from client input
            # alone (?date=... with no slug/movie_id), so with a connection pool
            # an unauthenticated caller could exhaust it by looping this URL.
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'slug or movie_id required'}), 400
        
        # Get shows with theatre information
        query = """
            SELECT 
                s.id as show_id,
                s.show_time,
                t.id as theatre_id,
                t.name as theatre_name,
                t.address as theatre_address,
                (SELECT COUNT(*) FROM seats WHERE show_id = s.id AND is_booked = 0) as available_seats,
                (SELECT COUNT(*) FROM seats WHERE show_id = s.id) as total_seats
            FROM shows s
            JOIN theatres t ON s.theatre_id = t.id
            WHERE s.movie_id = %s
              AND s.show_date = %s
              AND TIMESTAMP(s.show_date, s.show_time) > %s
            ORDER BY t.name, s.show_time
        """
        
        cursor.execute(query, (movie_id, requested_date, business_now_naive()))
        shows = cursor.fetchall()
        
        # Group by theatre
        theatres = {}
        for show in shows:
            theatre_id = show['theatre_id']
            if theatre_id not in theatres:
                theatres[theatre_id] = {
                    'id': theatre_id,
                    'name': show['theatre_name'],
                    'address': show['theatre_address'],
                    'shows': []
                }
            
            occupancy_pct = ((show['total_seats'] - show['available_seats']) / show['total_seats'] * 100) if show['total_seats'] > 0 else 0
            
            # FIX: MySQL TIME columns are returned as timedelta objects
            # Convert timedelta to HH:MM string format
            show_time = show['show_time']
            if isinstance(show_time, timedelta):
                total_seconds = int(show_time.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                time_str = f"{hours:02d}:{minutes:02d}"
            else:
                # Fallback for datetime.time objects
                time_str = show_time.strftime('%H:%M')
            
            theatres[theatre_id]['shows'].append({
                'show_id': show['show_id'],
                'time': time_str,
                'available_seats': show['available_seats'],
                'occupancy': round(occupancy_pct, 1),
                'show_date': requested_date.strftime('%Y-%m-%d')
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'theatres': list(theatres.values())
        }), 200
        
    except Exception:
        return _server_error('GET /api/shows')

# ============================================
# SEATS APIs
# ============================================

@app.route('/api/seats/<int:show_id>', methods=['GET'])
def get_seats(show_id):
    """Get all seats for a show"""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)
        
        # Get show details
        cursor.execute("""
            SELECT s.*, m.title as movie_title, t.name as theatre_name, t.address as theatre_address
            FROM shows s
            JOIN movies m ON s.movie_id = m.id
            JOIN theatres t ON s.theatre_id = t.id
            WHERE s.id = %s
        """, (show_id,))
        
        show = cursor.fetchone()

        if not show:
            # Close before returning: /api/seats/<id> is public, so any request
            # for a nonexistent show id would otherwise leak a pooled connection.
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Show not found'}), 404
        
        # Check if show has already started (server-side validation)
        show_date = show['show_date']
        show_time = show['show_time']
        
        # Convert show_time (timedelta or time) to datetime
        if isinstance(show_time, timedelta):
            total_seconds = int(show_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            show_datetime = datetime.combine(show_date, datetime.min.time().replace(hour=hours, minute=minutes))
        else:
            show_datetime = datetime.combine(show_date, show_time)
        
        current_datetime = business_now_naive()
        
        if current_datetime >= show_datetime:
            cursor.close()
            conn.close()
            return jsonify({
                'success': False, 
                'message': 'This show has already started and is no longer available for booking.'
            }), 400
        
        # Get seats.
        # Order by row letter first, then by the NUMERIC seat number.
        # A plain "ORDER BY seat_label" sorts as text, which puts 'A10' before
        # 'A2' (giving 1,10,11,12,2,3...). Casting the numeric part fixes that.
        cursor.execute("""
            SELECT id, seat_label, price, is_booked
            FROM seats
            WHERE show_id = %s
            ORDER BY LEFT(seat_label, 1), CAST(SUBSTRING(seat_label, 2) AS UNSIGNED)
        """, (show_id,))
        
        seats = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # FIX: Handle timedelta for show_time (MySQL TIME columns)
        show_time = show['show_time']
        if isinstance(show_time, timedelta):
            total_seconds = int(show_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_str = f"{hours:02d}:{minutes:02d}"
        else:
            time_str = show_time.strftime('%H:%M')
        
        return jsonify({
            'success': True,
            'show': {
                'id': show['id'],
                'movie_title': show['movie_title'],
                'theatre_name': show['theatre_name'],
                'theatre_address': show['theatre_address'],
                'show_date': show['show_date'].strftime('%Y-%m-%d'),
                'show_time': time_str
            },
            'seats': seats
        }), 200

    except Exception:
        return _server_error('GET /api/seats')

# ============================================
# AUTHENTICATION APIs
# ============================================

def _build_otp_html(otp):
    """Render the branded HTML email body for Bookora OTP verification."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Inter', Arial, sans-serif; margin: 0; padding: 0; background-color: #FAF9F8; }}
        .container {{ max-width: 600px; margin: 40px auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(42, 37, 32, 0.08); }}
        .header {{ background: linear-gradient(135deg, #D4A59A 0%, #C89B8E 100%); padding: 40px 30px; text-align: center; }}
        .header h1 {{ color: white; margin: 0; font-size: 32px; font-weight: 600; letter-spacing: 1px; }}
        .content {{ padding: 40px 30px; }}
        .otp-box {{ background: #FAF9F8; border: 2px dashed #D4A59A; border-radius: 8px; padding: 30px; text-align: center; margin: 30px 0; }}
        .otp-code {{ font-size: 42px; font-weight: 700; color: #D4A59A; letter-spacing: 12px; margin: 0; }}
        .message {{ color: #2A2520; font-size: 16px; line-height: 1.6; margin: 20px 0; }}
        .footer {{ background: #FAF9F8; padding: 20px 30px; text-align: center; color: #8B7E74; font-size: 13px; }}
        .brand {{ color: #D4A59A; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎬 BOOKORA</h1>
        </div>
        <div class="content">
            <p class="message">Hello!</p>
            <p class="message">Your One-Time Password (OTP) to verify your account is:</p>
            <div class="otp-box">
                <p class="otp-code">{otp}</p>
            </div>
            <p class="message">This code is valid for <strong>{OTP_TTL_MINUTES} minutes</strong>. Please do not share it with anyone.</p>
            <p class="message">If you didn't request this code, please ignore this email.</p>
        </div>
        <div class="footer">
            <p>© 2026 <span class="brand">Bookora</span> | Your Premium Movie Booking Experience</p>
        </div>
    </div>
</body>
</html>"""


def _build_otp_text(otp):
    """Render plain-text fallback body for OTP verification."""
    return (
        f"Hello!\n\n"
        f"Your One-Time Password (OTP) to verify your Bookora account is: {otp}\n\n"
        f"This code is valid for {OTP_TTL_MINUTES} minutes. Please do not share it with anyone.\n"
        f"If you didn't request this code, please ignore this email.\n\n"
        f"© 2026 Bookora | Your Premium Movie Booking Experience\n"
    )


def _send_email_brevo(email, otp, subject, html_content, text_content):
    """Send OTP email via Brevo (Sendinblue) HTTPS REST API (port 443)."""
    api_key = os.getenv('BREVO_API_KEY') or BREVO_API_KEY
    if not api_key:
        logger.error("Brevo transport selected but BREVO_API_KEY is not set")
        return False

    sender_email = os.getenv('EMAIL_FROM') or EMAIL_FROM or os.getenv('EMAIL_USER') or EMAIL_USER
    if not sender_email:
        logger.error("Brevo transport requires EMAIL_FROM or EMAIL_USER as the sender address")
        return False

    from_name = os.getenv('EMAIL_FROM_NAME') or EMAIL_FROM_NAME or 'Bookora'
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
    }
    payload = {
        "sender": {
            "name": from_name,
            "email": sender_email,
        },
        "to": [{"email": email}],
        "subject": subject,
        "htmlContent": html_content,
        "textContent": text_content,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace")[:300]
        logger.error("Brevo API HTTP %s error: %s", err.code, err_body)
        return False
    except urllib.error.URLError as err:
        logger.error("Brevo API network error: %s", err.reason)
        return False


def _send_email_resend(email, otp, subject, html_content, text_content):
    """Send OTP email via Resend HTTPS REST API (port 443)."""
    api_key = os.getenv('RESEND_API_KEY') or RESEND_API_KEY
    if not api_key:
        logger.error("Resend transport selected but RESEND_API_KEY is not set")
        return False

    sender_email = os.getenv('EMAIL_FROM') or EMAIL_FROM or "onboarding@resend.dev"
    from_name = os.getenv('EMAIL_FROM_NAME') or EMAIL_FROM_NAME or 'Bookora'
    from_field = f"{from_name} <{sender_email}>" if from_name and "<" not in sender_email else sender_email

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": from_field,
        "to": [email],
        "subject": subject,
        "html": html_content,
        "text": text_content,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace")[:300]
        logger.error("Resend API HTTP %s error: %s", err.code, err_body)
        return False
    except urllib.error.URLError as err:
        logger.error("Resend API network error: %s", err.reason)
        return False


def _send_email_smtp(email, otp, subject, html_content, text_content):
    """Send OTP email using standard SMTP (for local development)."""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    from_addr = EMAIL_FROM or EMAIL_USER
    msg['From'] = f"{EMAIL_FROM_NAME} <{from_addr}>" if EMAIL_FROM_NAME and "<" not in (from_addr or "") else from_addr
    msg['To'] = email

    msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=5) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(msg)
    return True


def send_email_otp(email, otp):
    """Send OTP email using the configured email transport (HTTPS API or SMTP)."""
    try:
        subject = 'Your Bookora Verification Code'
        html_content = _build_otp_html(otp)
        text_content = _build_otp_text(otp)

        provider = _get_email_provider()

        if provider == 'brevo':
            success = _send_email_brevo(email, otp, subject, html_content, text_content)
        elif provider == 'resend':
            success = _send_email_resend(email, otp, subject, html_content, text_content)
        elif provider == 'smtp':
            success = _send_email_smtp(email, otp, subject, html_content, text_content)
        else:
            logger.error('Unknown EMAIL_PROVIDER: %s', provider)
            return False

        if success:
            logger.info('OTP email sent to %s via %s', mask_email(email), provider)
            return True
        return False
    except Exception:
        logger.exception('Failed to send OTP email via %s', _get_email_provider())
        return False

@app.route('/api/send-otp', methods=['POST'])
def send_otp():
    """
    Generate a one-time code, store it, and email it.

    Hardened against the three abuses the original endpoint allowed: unlimited
    mail sends (a free unauthenticated relay that also burns the Gmail quota),
    arbitrary unvalidated identifiers, and a predictable code.
    """
    try:
        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '')
        email = email.strip().lower() if isinstance(email, str) else ''

        if not email:
            return jsonify({'success': False, 'message': 'Email is required'}), 400

        # Server-side format validation. The client-side regex in signin-modal.js
        # is bypassed completely by a direct POST, and an unvalidated identifier
        # goes on to become an SMTP envelope recipient.
        if not is_valid_email(email):
            return jsonify({'success': False, 'message': 'Please enter a valid email address'}), 400

        client_ip = _client_ip()
        window = OTP_WINDOW_MINUTES * 60

        # Per-IP cap first: without it an attacker just rotates the email address
        # and the per-identifier limit never engages.
        allowed, retry_after, _ = _otp_send_limiter.hit(
            f'send:ip:{client_ip}', OTP_MAX_SENDS_PER_IP, window
        )
        if not allowed:
            logger.warning('OTP send rate limit (per IP) hit for %s', client_ip)
            return _rate_limited('Too many verification requests. Please try again later.', retry_after)

        # Per-identifier window cap plus a minimum spacing between sends. Both are
        # per worker; the authoritative, cluster-wide cooldown is the MySQL check
        # below. This one is kept as a cheap pre-filter so an abusive caller is
        # usually turned away before a pooled connection is borrowed.
        allowed, retry_after, reason = _otp_send_limiter.hit(
            f'send:id:{email}', OTP_MAX_SENDS_PER_EMAIL, window,
            min_interval_seconds=OTP_RESEND_COOLDOWN_SECONDS,
        )
        if not allowed:
            if reason == 'interval':
                return _rate_limited(
                    f'Please wait {retry_after} seconds before requesting another code.', retry_after
                )
            logger.warning('OTP send rate limit (per identifier) hit for %s', mask_email(email))
            return _rate_limited(
                'Too many codes requested for this email. Please try again later.', retry_after
            )

        conn = get_db()
        cursor = conn.cursor(buffered=True)
        try:
            # ---- Cluster-wide resend cooldown ------------------------------
            # The in-memory limiter above lives in one Gunicorn worker, so its
            # spacing is really "one send per 45s per worker" and `-w 4` will accept
            # four sends in the same second. otp_verification.created_at is written
            # and read by MySQL, which every worker and every host shares, so it
            # gives an exact cluster-wide cooldown that also survives restarts -
            # with no schema change and no new dependency (this endpoint already
            # cannot function without MySQL).
            #
            # created_at, not expires_at: created_at is a TIMESTAMP set by MySQL and
            # compared here against MySQL's own NOW(), so the difference is
            # timezone-invariant. expires_at is written from this process's naive
            # datetime.now() and would be skewed by any app-vs-database timezone gap.
            #
            # MAX(): identifier has no UNIQUE key, so more than one row per address
            # is possible and the newest is the anchor. Read BEFORE the DELETE
            # below, which is what removes the previous send's row.
            cursor.execute(
                """SELECT TIMESTAMPDIFF(SECOND, MAX(created_at), NOW()) AS age
                   FROM otp_verification WHERE identifier = %s""",
                (email,)
            )
            anchor = cursor.fetchone()
            age = anchor[0] if anchor else None
            if age is not None and age < OTP_RESEND_COOLDOWN_SECONDS:
                wait = max(OTP_RESEND_COOLDOWN_SECONDS - int(age), 1)
                conn.rollback()  # release the read transaction before returning
                return _rate_limited(
                    f'Please wait {wait} seconds before requesting another code.', wait
                )

            # secrets, not random: random.randint is a Mersenne Twister, so observing
            # a few outputs makes the rest predictable - and a predictable OTP is a
            # complete authentication bypass. randbelow also allows leading zeros,
            # which restores the full 10**6 code space (the old range had 9*10**5).
            otp = f'{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}'
            expires_at = datetime.now() + timedelta(minutes=OTP_TTL_MINUTES)

            # A newly issued code supersedes any earlier one for this identifier.
            cursor.execute("DELETE FROM otp_verification WHERE identifier = %s", (email,))
            cursor.execute(
                """INSERT INTO otp_verification (identifier, otp, expires_at)
                   VALUES (%s, %s, %s)""",
                (email, otp, expires_at)
            )
            # Opportunistic cleanup: nothing else ever pruned this table, so
            # long-expired rows accumulated forever.
            cursor.execute(
                "DELETE FROM otp_verification WHERE expires_at < (NOW() - INTERVAL 1 DAY)"
            )
            conn.commit()
        except Exception:
            # This was the one write path with no rollback. It DELETEs the previous
            # code before INSERTing the new one, so a failure between the two would
            # otherwise hand a pooled connection to the next request with the
            # transaction still open and the old code already gone.
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

        # A fresh code resets the wrong-guess budget for this identifier.
        _reset_otp_attempts(email)

        # Sent after the connection is released so the SMTP round-trip never
        # holds a pooled connection.
        if send_email_otp(email, otp):
            return jsonify({
                'success': True,
                'message': 'OTP sent successfully to your email',
                # So the client's Resend countdown matches the server's cooldown
                # instead of re-enabling the button early and earning a guaranteed 429.
                'resend_after': OTP_RESEND_COOLDOWN_SECONDS
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to send email. Please try again.'
            }), 500

    except Exception:
        return _server_error('POST /api/send-otp', 'Could not send the verification code. Please try again.')

@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    """Verify OTP and check if user exists"""
    try:
        data = request.get_json(silent=True) or {}
        identifier = data.get('email') or data.get('phone')
        otp = data.get('otp')
        contact_type = data.get('type', 'email')  # 'email' or 'phone'

        # Normalize phone identifier if it's a phone type
        if contact_type == 'phone' and identifier:
            normalized_phone = normalize_phone(identifier)
            if normalized_phone:
                identifier = normalized_phone
        elif isinstance(identifier, str):
            # The users/otp columns already match case-insensitively via their
            # collation, but normalizing here keeps the rate-limit and
            # attempt-counter keys from splitting across casings of one address.
            identifier = identifier.strip().lower()

        if not identifier or not otp:
            return jsonify({'success': False, 'message': 'Identifier and OTP are required'}), 400

        # Shape-check the code before touching the database. The old code passed
        # any string straight into the query, so a 200-character guess still cost
        # a full round trip.
        otp = str(otp).strip()
        if not otp.isdigit() or len(otp) != OTP_LENGTH:
            return jsonify({'success': False, 'message': 'Invalid or expired OTP'}), 400

        if contact_type == 'email' and not is_valid_email(identifier):
            return jsonify({'success': False, 'message': 'Please enter a valid email address'}), 400

        client_ip = _client_ip()
        allowed, retry_after, _ = _otp_verify_limiter.hit(
            f'verify:ip:{client_ip}', OTP_MAX_VERIFIES_PER_IP, OTP_WINDOW_MINUTES * 60
        )
        if not allowed:
            logger.warning('OTP verify rate limit hit for %s', client_ip)
            return _rate_limited('Too many verification attempts. Please try again later.', retry_after)

        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)
        try:
            # Wrong code and expired code intentionally produce the same response,
            # so the message cannot be used to confirm that a code is still live.
            cursor.execute("""
                SELECT id FROM otp_verification
                WHERE identifier = %s AND otp = %s AND expires_at > NOW()
                LIMIT 1
            """, (identifier, otp))

            otp_record = cursor.fetchone()

            if not otp_record:
                # Count the miss, and destroy the code once the budget is spent.
                # Without a ceiling a live code could be brute-forced with
                # unlimited guesses for its whole validity window. The counter is
                # per-process but the invalidation is a MySQL write, so it is
                # durable and visible to every worker.
                attempts = _register_failed_attempt(identifier)
                if attempts >= OTP_MAX_VERIFY_ATTEMPTS:
                    # Expire the code rather than DELETEing the row. That row's
                    # created_at is the cluster-wide resend-cooldown anchor read by
                    # send_otp, so deleting it here would mean five wrong guesses
                    # clears the cooldown and unlocks an immediate resend. Blanking
                    # otp and back-dating expires_at makes the code unmatchable by
                    # the SELECT above (which requires expires_at > NOW() and a
                    # 6-digit otp); the next send, or send_otp's daily sweep,
                    # removes the row.
                    cursor.execute(
                        """UPDATE otp_verification
                           SET otp = '', expires_at = NOW() - INTERVAL 1 SECOND
                           WHERE identifier = %s""",
                        (identifier,)
                    )
                    conn.commit()
                    _reset_otp_attempts(identifier)
                    logger.warning(
                        'OTP invalidated after %s failed attempts for %s',
                        attempts, mask_email(identifier)
                    )
                    return jsonify({
                        'success': False,
                        'message': 'Too many incorrect attempts. Please request a new code.'
                    }), 400
                return jsonify({'success': False, 'message': 'Invalid or expired OTP'}), 400

            # Delete used OTP
            cursor.execute("DELETE FROM otp_verification WHERE id = %s", (otp_record['id'],))
            conn.commit()
            _reset_otp_attempts(identifier)

            # Check if user exists
            if contact_type == 'email':
                cursor.execute("SELECT * FROM users WHERE email = %s", (identifier,))
            else:
                cursor.execute("SELECT * FROM users WHERE phone = %s", (identifier,))

            user = cursor.fetchone()
        finally:
            cursor.close()
            # Every non-committed exit from the block above (a wrong code returns
            # 400 from inside it, an exception propagates out of it) still has the
            # implicit read transaction open - mysql-connector does not autocommit.
            # Roll it back before the connection returns to the pool, or the next
            # borrower inherits it. After a commit this is a no-op.
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
        
        if user:
            # User exists — establish the authenticated server-side session.
            # From here on the server derives identity from session['user_id'];
            # the client no longer needs to (and must not) supply its own user_id.
            session.permanent = True
            session['user_id'] = user['id']
            # This identifier already has an account, so there is nothing left to
            # register. Drop any stale signup proof so it cannot be spent later.
            session.pop(PENDING_PROFILE_KEY, None)
            return jsonify({
                'success': True,
                'message': 'OTP verified successfully',
                'userExists': True,
                'user': {
                    'id': user['id'],
                    'name': user['name'],
                    'email': user['email'],
                    'phone': user['phone']
                }
            }), 200
        else:
            # New user - needs profile completion.
            #
            # Record the proof of verification server-side, in the signed session
            # cookie. /api/complete-profile reads the identifier from HERE and
            # never from its request body, so an unauthenticated caller can no
            # longer register an address it does not control. The client keeps
            # sending `email` in that body and it is cross-checked, not trusted.
            #
            # user_id is cleared first: whoever completes this signup becomes the
            # session's user, so no previous login may linger alongside the proof.
            #
            # session.permanent is deliberately NOT set here. This cookie carries a
            # one-shot signup credential, so it should die with the browser session;
            # PENDING_PROFILE_TTL_MINUTES is the real control, and the durable
            # 7-day cookie is only issued once complete_profile logs the user in.
            session.pop('user_id', None)
            session[PENDING_PROFILE_KEY] = {
                'identifier': identifier,
                'type': contact_type,
                'verified_at': time.time(),
            }
            return jsonify({
                'success': True,
                'message': 'OTP verified successfully',
                'userExists': False,
                'identifier': identifier,
                'type': contact_type
            }), 200
            
    except Exception:
        return _server_error('POST /api/verify-otp', 'Could not verify the code. Please try again.')

def _consume_verification_proof():
    """
    Return (identifier, contact_type) for the OTP verification this session just
    completed, or (None, None) if there is no usable proof.

    This is the authorization gate for signup. /api/verify-otp writes the proof
    into the signed session cookie only after a code was matched and consumed, so
    a caller cannot manufacture one: the cookie is signed with SECRET_KEY, and
    without it there is no way to reach the registration path at all.

    Expired proof is discarded here rather than merely ignored, so a stale marker
    cannot sit in a long-lived cookie waiting to be spent.
    """
    pending = session.get(PENDING_PROFILE_KEY)
    if not isinstance(pending, dict):
        return None, None

    identifier = pending.get('identifier')
    contact_type = pending.get('type')
    verified_at = pending.get('verified_at')

    if (not identifier or contact_type not in ('email', 'phone')
            or not isinstance(verified_at, (int, float))):
        session.pop(PENDING_PROFILE_KEY, None)
        return None, None

    if time.time() - verified_at > PENDING_PROFILE_TTL_MINUTES * 60:
        session.pop(PENDING_PROFILE_KEY, None)
        logger.info('Signup proof expired for %s', mask_email(identifier))
        return None, None

    return identifier, contact_type


@app.route('/api/complete-profile', methods=['POST'])
def complete_profile():
    """
    Create the account for the identifier this session has just proved it owns.

    AUTHORIZATION: the email being registered comes from the server-side session
    (written by /api/verify-otp after a code was matched and consumed), NEVER from
    the request body. The endpoint used to INSERT whatever `email` the body named
    and then log the caller straight in as that new user, so an unauthenticated
    POST could register - and thereby squat - any address in the world, including
    one belonging to a real person who had not signed up yet. Anyone doing that
    also got a valid session for the account they created.

    The body is still allowed to carry `email` (the existing client sends it) but
    it is only cross-checked against the verified value. `phone` is different: it
    is a user-typed secondary contact that is NOT OTP-verified, and it cannot be
    used to sign in - /api/send-otp only ever issues codes for email addresses -
    so it is accepted as profile data exactly as before, still subject to the
    duplicate check.
    """
    conn = None
    cursor = None
    try:
        # --- Authorization ---------------------------------------------------
        if session.get('user_id'):
            # Already signed in. Creating a second account here would silently
            # move the session onto it.
            return jsonify({
                'success': False,
                'message': 'You are already signed in.'
            }), 400

        verified_identifier, verified_type = _consume_verification_proof()
        if not verified_identifier:
            logger.warning(
                'complete-profile rejected: no valid OTP verification in session (ip=%s)',
                _client_ip()
            )
            return jsonify({
                'success': False,
                'message': 'Please verify your email with a new code before completing your profile.'
            }), 403

        data = request.get_json(silent=True) or {}
        name = data.get('name')

        # ONLY name is required - mobile and email are optional
        if not name:
            return jsonify({'success': False, 'message': 'Name is required'}), 400

        # Validate name format (letters and spaces only, 2-50 characters)
        import re
        name_pattern = r'^[A-Za-z][A-Za-z ]{1,49}$'
        if not re.match(name_pattern, name):
            return jsonify({'success': False, 'message': 'Invalid name format.'}), 400

        # --- Identity: taken from the proof, not the body --------------------
        if verified_type == 'email':
            email = verified_identifier
            phone = data.get('phone')

            # The client sends the same address it verified. A mismatch means the
            # body is trying to register something else, so refuse loudly instead
            # of quietly substituting the verified value.
            body_email = data.get('email')
            if isinstance(body_email, str) and body_email.strip():
                if body_email.strip().lower() != verified_identifier:
                    logger.warning(
                        'complete-profile email mismatch: body=%s verified=%s',
                        mask_email(body_email.strip().lower()), mask_email(verified_identifier)
                    )
                    return jsonify({
                        'success': False,
                        'message': 'This email does not match the address you verified.'
                    }), 403
        else:
            # Phone-verified signup. Unreachable today (send-otp is email-only)
            # but handled rather than left to fall through: the verified phone is
            # the identity, and an unverified email from the body is discarded.
            phone = verified_identifier
            email = None
            if data.get('email'):
                logger.warning('complete-profile ignored an unverified email on a phone signup')

        # primary_contact_type is derived from what was actually verified rather
        # than read from the body, which also removes the chance of a bad value
        # reaching the ENUM column.
        primary_contact = verified_type

        # Normalize phone number if provided
        if phone:
            normalized_phone = normalize_phone(phone)
            if not normalized_phone:
                return jsonify({'success': False, 'message': 'Invalid phone number format'}), 400
            phone = normalized_phone

        # Ensure at least one contact method exists (from OTP verification)
        if not email and not phone:
            return jsonify({'success': False, 'message': 'At least email or phone is required'}), 400

        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        # Check for duplicate phone number
        if phone:
            cursor.execute("SELECT id FROM users WHERE phone = %s", (phone,))
            existing_user = cursor.fetchone()
            if existing_user:
                conn.rollback()
                return jsonify({'success': False, 'message': 'This mobile number is already registered with another account.'}), 400

        # Check for duplicate email
        if email:
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            existing_user = cursor.fetchone()
            if existing_user:
                conn.rollback()
                return jsonify({'success': False, 'message': 'This email is already registered with another account.'}), 400

        # Insert new user
        try:
            cursor.execute("""
                INSERT INTO users (name, email, phone, primary_contact_type)
                VALUES (%s, %s, %s, %s)
            """, (name, email, phone, primary_contact))
        except mysql.connector.IntegrityError:
            # users.email and users.phone are both UNIQUE. The checks above race
            # with a concurrent signup, so the constraint is the real arbiter.
            conn.rollback()
            logger.info('complete-profile hit a uniqueness conflict for %s', mask_email(email or phone))
            return jsonify({
                'success': False,
                'message': 'This email is already registered with another account.'
            }), 400

        user_id = cursor.lastrowid
        conn.commit()

        # Fetch created user
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        # New account created via a verified OTP flow — establish the session so
        # the server (not the client) tracks this authenticated user going forward.
        # The proof is spent at the same moment, so it cannot be replayed to
        # create a second account.
        session.pop(PENDING_PROFILE_KEY, None)
        session.permanent = True
        session['user_id'] = user['id']

        return jsonify({
            'success': True,
            'message': 'Profile completed successfully',
            'user': {
                'id': user['id'],
                'name': user['name'],
                'email': user['email'],
                'phone': user['phone']
            }
        }), 200

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                logger.warning('complete_profile: rollback failed', exc_info=True)
        return _server_error('POST /api/complete-profile')
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

@app.route('/api/logout', methods=['POST'])
def logout():
    """Clear the authenticated server-side session (server-side sign-out)."""
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out successfully'}), 200

@app.route('/api/auth/me', methods=['GET'])
@login_required
def get_auth_me():
    """
    Return current authenticated user profile from verified session.
    Returns 401 if unauthenticated (enforced by @login_required).
    Identity is derived strictly from server session; no IDOR possible.
    """
    return jsonify({
        'success': True,
        'user': {
            'id': g.current_user['id'],
            'name': g.current_user['name'],
            'email': g.current_user['email'],
            'phone': g.current_user['phone']
        }
    }), 200

# ============================================
# SAVED MOVIES APIs
# ============================================

@app.route('/api/saved-movies', methods=['GET'])
@login_required
def get_saved_movies():
    """Get all saved movies for the authenticated user"""
    try:
        user_id = g.current_user['id']
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        cursor.execute("""
            SELECT m.* FROM movies m
            INNER JOIN saved_movies sm ON m.id = sm.movie_id
            WHERE sm.user_id = %s
            ORDER BY sm.created_at DESC
        """, (user_id,))
        
        saved_movies = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'movies': saved_movies}), 200
    except Exception:
        return _server_error('GET /api/saved-movies')

@app.route('/api/save-movie', methods=['POST'])
@login_required
def save_movie():
    """Save a movie for the authenticated user"""
    try:
        data = request.get_json()
        user_id = g.current_user['id']
        movie_id = data.get('movie_id')

        if not movie_id:
            return jsonify({'success': False, 'message': 'Movie ID required'}), 400
        
        conn = get_db()
        cursor = conn.cursor(buffered=True)
        
        # Insert; a duplicate (already saved) is fine and treated as success
        try:
            cursor.execute("""
                INSERT INTO saved_movies (user_id, movie_id)
                VALUES (%s, %s)
            """, (user_id, movie_id))
            conn.commit()
        except mysql.connector.IntegrityError:
            # Movie already saved for this user (UNIQUE constraint) - idempotent, ignore
            conn.rollback()
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Movie saved successfully'}), 200
    except Exception:
        return _server_error('POST /api/save-movie')

@app.route('/api/unsave-movie', methods=['POST'])
@login_required
def unsave_movie():
    """Remove a saved movie for the authenticated user"""
    try:
        data = request.get_json()
        user_id = g.current_user['id']
        movie_id = data.get('movie_id')

        if not movie_id:
            return jsonify({'success': False, 'message': 'Movie ID required'}), 400
        
        conn = get_db()
        cursor = conn.cursor(buffered=True)
        
        cursor.execute("""
            DELETE FROM saved_movies
            WHERE user_id = %s AND movie_id = %s
        """, (user_id, movie_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Movie unsaved successfully'}), 200
    except Exception:
        return _server_error('POST /api/unsave-movie')

@app.route('/api/check-saved/<int:movie_id>', methods=['GET'])
@login_required
def check_saved(movie_id):
    """Check if a movie is saved by the authenticated user"""
    try:
        user_id = g.current_user['id']
        conn = get_db()
        cursor = conn.cursor(buffered=True)

        cursor.execute("""
            SELECT COUNT(*) as count FROM saved_movies
            WHERE user_id = %s AND movie_id = %s
        """, (user_id, movie_id))
        
        result = cursor.fetchone()
        is_saved = result[0] > 0
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'is_saved': is_saved}), 200
    except Exception:
        return _server_error('GET /api/check-saved')

# ============================================
# PAGE ROUTES (Template / UI Rendering)
# ============================================

def _serve_page(template_name):
    """Render an HTML page template in monolithic mode, or return JSON 404 in API-only mode."""
    if _is_api_only():
        return jsonify({
            'error': 'Not Found',
            'message': 'Page routes are disabled in API-only mode. UI is hosted separately on the frontend static service.'
        }), 404
    return render_template(template_name)


@app.route('/')
def home():
    if _is_api_only():
        return jsonify({
            'service': 'Bookora API',
            'status': 'online',
            'mode': 'api-only',
            'health': '/healthz'
        }), 200
    return render_template('index.html')

@app.route('/movie/<slug>')
def movie_details(slug):
    return _serve_page('movie-details.html')

@app.route('/shows/<slug>')
def shows_page(slug):
    return _serve_page('shows.html')

@app.route('/seats/<int:show_id>')
def seats_page(show_id):
    return _serve_page('seat-selection.html')

@app.route('/profile')
def profile_page():
    return _serve_page('profile.html')

@app.route('/my-bookings')
def my_bookings_page():
    return _serve_page('my-bookings.html')

@app.route('/saved-movies')
def saved_movies_page():
    return _serve_page('saved-movies.html')

# ============================================
# PROFILE APIs
# ============================================

@app.route('/api/profile/update', methods=['PUT'])
@login_required
def update_profile():
    """Update the authenticated user's profile (name, and phone if currently NULL)"""
    try:
        data = request.json
        user_id = g.current_user['id']
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip() if 'phone' in data else None

        if not name:
            return jsonify({'success': False, 'message': 'Name is required'}), 400
        
        # Validate name format (letters and spaces only, 2-50 characters)
        import re
        name_pattern = r'^[A-Za-z][A-Za-z ]{1,49}$'
        if not re.match(name_pattern, name):
            return jsonify({'success': False, 'message': 'Invalid name format.'}), 400
        
        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)
        
        # Normalize phone number if provided
        if phone:
            normalized_phone = normalize_phone(phone)
            if not normalized_phone:
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': 'Invalid phone number format. Please enter a valid 10-digit mobile number.'}), 400
            phone = normalized_phone
        
        # Check current phone value
        cursor.execute("SELECT phone FROM users WHERE id = %s", (user_id,))
        current_user = cursor.fetchone()
        
        if not current_user:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Update name (always allowed)
        # Update phone ONLY if current phone is NULL and new phone is provided
        if phone and current_user['phone'] is None:
            # Check if phone number already exists in database
            cursor.execute("SELECT id FROM users WHERE phone = %s AND id != %s", (phone, user_id))
            existing_user = cursor.fetchone()
            if existing_user:
                cursor.close()
                conn.close()
                return jsonify({'success': False, 'message': 'This mobile number is already registered with another account.'}), 400
            
            # Allow adding phone number (one-time only)
            cursor.execute(
                "UPDATE users SET name = %s, phone = %s WHERE id = %s",
                (name, phone, user_id)
            )
        elif phone and current_user['phone'] is not None:
            # Reject attempt to change existing phone number
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'message': 'Phone number cannot be changed once set'}), 400
        else:
            # Only update name
            cursor.execute(
                "UPDATE users SET name = %s WHERE id = %s",
                (name, user_id)
            )
        
        conn.commit()
        
        # Fetch updated user data
        cursor.execute("SELECT id, name, email, phone FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if user:
            return jsonify({'success': True, 'user': user})
        else:
            return jsonify({'success': False, 'message': 'User not found'}), 404
            
    except Exception:
        return _server_error('PUT /api/profile/update')

# ============================================
# BOOKINGS APIs
# ============================================

@app.route('/api/bookings', methods=['GET'])
@login_required
def get_user_bookings():
    """Get all bookings for the authenticated user.

    Identity is taken from the server-side session, NOT from the request. Any
    ?user_id= supplied by the client is ignored, which closes the IDOR where a
    user could read another user's bookings by changing the query parameter.
    """
    try:
        user_id = g.current_user['id']

        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)
        
        # Get bookings with show and movie details
        query = """
            SELECT 
                b.id as booking_id,
                b.seat_ids,
                b.total_price,
                b.status,
                b.booking_date,
                s.id as show_id,
                s.show_date,
                s.show_time,
                m.id as movie_id,
                m.title as movie_title,
                m.poster_url,
                m.duration,
                m.certification,
                t.name as theatre_name,
                t.address as theatre_address
            FROM bookings b
            JOIN shows s ON b.show_id = s.id
            JOIN movies m ON s.movie_id = m.id
            JOIN theatres t ON s.theatre_id = t.id
            WHERE b.user_id = %s
            ORDER BY b.booking_date DESC
        """
        
        cursor.execute(query, (user_id,))
        bookings = cursor.fetchall()
        
        # Process seat_ids JSON and convert dates/times to strings
        for booking in bookings:
            seat_ids = json.loads(booking['seat_ids'])
            booking['seat_ids'] = seat_ids
            
            # Fetch seat details (labels, types, prices) for this booking
            if seat_ids:
                placeholders = ','.join(['%s'] * len(seat_ids))
                seat_query = f"""
                    SELECT id, seat_label, price
                    FROM seats
                    WHERE id IN ({placeholders})
                """
                cursor.execute(seat_query, tuple(seat_ids))
                seat_details = cursor.fetchall()
                
                # Convert Decimal prices to float for JSON serialization
                for seat in seat_details:
                    if 'price' in seat:
                        seat['price'] = float(seat['price'])
                
                booking['seat_details'] = seat_details
            else:
                booking['seat_details'] = []
            
            # Convert date to string
            if isinstance(booking.get('show_date'), date):
                booking['show_date'] = booking['show_date'].strftime('%Y-%m-%d')
            
            # Convert time (timedelta) to string
            if isinstance(booking.get('show_time'), timedelta):
                total_seconds = int(booking['show_time'].total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                booking['show_time'] = f"{hours:02d}:{minutes:02d}:00"
            
            # Convert booking_date to string
            if isinstance(booking.get('booking_date'), date):
                booking['booking_date'] = booking['booking_date'].strftime('%Y-%m-%d %H:%M:%S') if hasattr(booking['booking_date'], 'strftime') else str(booking['booking_date'])
        
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'bookings': bookings})
        
    except Exception:
        return _server_error('GET /api/bookings')

@app.route('/api/cancel-booking', methods=['POST'])
@login_required
def cancel_booking():
    """Cancel a booking and release seats (only the owner's own booking).

    The two writes below - marking the booking CANCELLED and releasing its seats -
    must either both happen or neither. They are one transaction, and every exit
    path now ends it explicitly:

      * success            -> commit
      * 404 / 400 refusals -> rollback (the ownership SELECT already opened a
                              transaction, and an idle open transaction handed
                              back to the pool holds locks for the next borrower)
      * any exception      -> rollback before returning the generic 500

    Without that rollback a failure between the two writes left the booking marked
    CANCELLED with its seats still flagged as booked - unsellable seats plus a
    refunded booking - and returned a connection to the pool mid-transaction.
    """
    conn = None
    cursor = None
    try:
        data = request.json or {}
        booking_id = data.get('booking_id')
        user_id = g.current_user['id']

        if not booking_id:
            return jsonify({'success': False, 'message': 'Booking ID required'}), 400

        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        # Verify booking belongs to user and is confirmed
        cursor.execute("""
            SELECT b.*, s.show_date, s.show_time
            FROM bookings b
            JOIN shows s ON b.show_id = s.id
            WHERE b.id = %s AND b.user_id = %s AND b.status = 'CONFIRMED'
        """, (booking_id, user_id))

        booking = cursor.fetchone()

        if not booking:
            conn.rollback()
            return jsonify({'success': False, 'message': 'Booking not found or already cancelled'}), 404

        # Check if show is in the future
        show_datetime = datetime.combine(booking['show_date'],
                                        datetime.strptime(str(booking['show_time']), '%H:%M:%S').time())

        if show_datetime <= business_now_naive():
            conn.rollback()
            return jsonify({'success': False, 'message': 'Cannot cancel past bookings'}), 400

        # Decode the seat list BEFORE the first write. It used to be parsed
        # between the two UPDATEs, so a malformed seat_ids value marked the
        # booking cancelled and then raised, leaving the seats booked forever.
        seat_ids = json.loads(booking['seat_ids'])

        # Update booking status to CANCELLED
        cursor.execute("UPDATE bookings SET status = 'CANCELLED' WHERE id = %s", (booking_id,))

        # Release seats - update seats to available
        for seat_id in seat_ids:
            cursor.execute(
                "UPDATE seats SET is_booked = FALSE, booked_by = NULL, booked_at = NULL WHERE id = %s",
                (seat_id,)
            )

        conn.commit()

        return jsonify({'success': True, 'message': 'Booking cancelled successfully'})

    except Exception:
        # Roll back before the response is built: _server_error() logs and
        # returns, so anything left undone here would be committed by nobody and
        # released by nothing.
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                logger.warning('cancel_booking: rollback failed', exc_info=True)
        return _server_error('POST /api/cancel-booking', 'Could not cancel the booking. Please try again.')
    finally:
        # One exit point for cleanup, so no early return can leak a pooled
        # connection or leave a cursor open.
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

@app.route('/api/create-booking', methods=['POST'])
@login_required
def create_booking():
    """Create a new booking with server-side price calculation and row locking."""
    conn = None
    cursor = None
    try:
        data = request.json or {}
        user_id = g.current_user['id']
        show_id = data.get('show_id')
        seat_ids = data.get('seat_ids', [])
        # NOTE: any client-supplied total_price is intentionally ignored.
        # The price is always calculated on the server from the seats table.
        # user_id also comes from the session, never from the request body.

        if not show_id or not seat_ids:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400

        # Validate and de-duplicate seat ids (must be integers)
        try:
            seat_ids = [int(s) for s in seat_ids]
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Invalid seat selection'}), 400
        seat_ids = list(dict.fromkeys(seat_ids))  # de-dupe, preserve order
        if not seat_ids:
            return jsonify({'success': False, 'message': 'No seats selected'}), 400

        conn = get_db()
        cursor = conn.cursor(dictionary=True, buffered=True)

        # Run the whole booking as a single transaction so the availability
        # check and the seat update are atomic (prevents double-booking).
        conn.start_transaction()

        # NOTE: the user's existence is already guaranteed by get_current_user()
        # (login_required), so no separate user lookup is needed here.

        # Get show details to validate timing
        cursor.execute("SELECT show_date, show_time FROM shows WHERE id = %s", (show_id,))
        show = cursor.fetchone()
        if not show:
            conn.rollback()
            return jsonify({'success': False, 'message': 'Show not found'}), 404

        # Reject bookings for shows that have already started (server-side)
        show_date = show['show_date']
        show_time = show['show_time']
        if isinstance(show_time, timedelta):
            total_seconds = int(show_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            show_datetime = datetime.combine(
                show_date, datetime.min.time().replace(hour=hours, minute=minutes)
            )
        else:
            show_datetime = datetime.combine(show_date, show_time)

        if business_now_naive() >= show_datetime:
            conn.rollback()
            return jsonify({
                'success': False,
                'message': 'This show has already started and is no longer available for booking.'
            }), 400

        # Lock the requested seats FOR UPDATE so concurrent requests cannot
        # grab the same seats between the availability check and the update.
        placeholders = ','.join(['%s'] * len(seat_ids))
        cursor.execute(
            f"""SELECT id, price, is_booked
                FROM seats
                WHERE show_id = %s AND id IN ({placeholders})
                FOR UPDATE""",
            (show_id, *seat_ids)
        )
        rows = cursor.fetchall()

        # Every requested seat must exist and belong to this show
        found_ids = {row['id'] for row in rows}
        missing = [s for s in seat_ids if s not in found_ids]
        if missing:
            conn.rollback()
            # The internal seats.id values go to the log, not to the client.
            logger.info('create_booking: seat ids %s not found for show %s', missing, show_id)
            return jsonify({
                'success': False,
                'message': 'Some of the selected seats are not available for this show. Please refresh and try again.'
            }), 404

        # None of the requested seats may already be booked
        already_booked = [row['id'] for row in rows if row['is_booked']]
        if already_booked:
            conn.rollback()
            logger.info('create_booking: seat ids %s already booked for show %s', already_booked, show_id)
            return jsonify({
                'success': False,
                'message': 'Some of the selected seats have just been booked. Please choose different seats.'
            }), 409

        # Authoritative price: sum of the seat prices straight from the database
        total_price = sum(row['price'] for row in rows)

        # Mark the seats as booked and record who booked them and when
        cursor.execute(
            f"""UPDATE seats
                SET is_booked = TRUE, booked_by = %s, booked_at = NOW()
                WHERE show_id = %s AND id IN ({placeholders})""",
            (user_id, show_id, *seat_ids)
        )

        # Create the booking using the server-calculated price
        cursor.execute(
            """INSERT INTO bookings (user_id, show_id, seat_ids, total_price, status)
               VALUES (%s, %s, %s, %s, 'CONFIRMED')""",
            (user_id, show_id, json.dumps(seat_ids), total_price)
        )
        booking_id = cursor.lastrowid

        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Booking confirmed successfully',
            'booking_id': booking_id,
            'total_price': float(total_price)
        })

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.exception('POST /api/create-booking failed')
        return jsonify({'success': False, 'message': 'Could not complete booking. Please try again.'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ============================================
# OPERATIONS
# ============================================

@app.route('/healthz')
def healthz():
    """Liveness probe for the hosting platform.

    Deliberately says nothing about the database, config or version: the point
    is 'this process is up and serving', and anything more becomes an
    unauthenticated window into the deployment.
    """
    return jsonify({'status': 'ok'}), 200

# ============================================
# STATIC FILE SERVING & 404 HANDLER
# ============================================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve files from static folder in monolithic mode only."""
    if _is_api_only():
        return jsonify({
            'error': 'Not Found',
            'message': 'Static asset serving is disabled in API-only mode. Assets are hosted on the frontend service.'
        }), 404
    return send_from_directory('static', filename)

@app.errorhandler(404)
def _handle_not_found(error):
    """Return JSON 404 responses for API requests or when in API-only mode."""
    if _is_api_only() or request.path.startswith('/api/'):
        return jsonify({
            'error': 'Not Found',
            'message': f'The requested endpoint {request.path} was not found on this server.'
        }), 404
    if hasattr(error, 'get_response'):
        return error.get_response()
    return 'Not Found', 404

# There used to be a `/<path:filename>` catch-all here that served any file in
# the project root. It published .env, .git/config, app.py, database_schema.sql
# and the seed scripts to anyone who asked. Nothing referenced it: every asset
# in the templates is under /static/ (served by the rule above), the project
# uses no url_for(), and /favicon.ico has its own route. Do not restore it -
# put new assets in static/ instead.

# Favicon route to prevent 404 errors
@app.route('/favicon.ico')
def favicon():
    return '', 204  # No Content response

if __name__ == '__main__':
    # Emoji are safe here: stdout/stderr were reconfigured to UTF-8 at import
    # time, so a cp1252 Windows console can no longer raise UnicodeEncodeError
    # and kill the server before app.run() is reached.
    print("🚀 Starting Bookora Server...")
    print("📍 Database: MySQL (bookora)")
    print("🎬 Movie system: Active")
    print("🎫 Booking system: Database-driven")
    app.run(debug=DEBUG, port=int(os.getenv('PORT', 5000)))
