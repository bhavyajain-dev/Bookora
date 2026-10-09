/**
 * BOOKORA — Centralized Frontend Configuration, API Client & Router
 * 
 * Provides:
 *   1. Dynamic environment-aware API URL resolution (local vs production)
 *   2. Unified BookoraAPI fetch wrapper with credential & header defaults
 *   3. Universal BookoraRouter for robust path & query parameter resolution
 * 
 * Works seamlessly across browser scripts and Node/testing environments.
 */
(function (global) {
    'use strict';

    // =========================================================================
    // 1. API CONFIGURATION & BASE URL RESOLUTION
    // =========================================================================

    /**
     * Determine the active backend API base URL.
     * 
     * Priority:
     *   1. window.BOOKORA_BACKEND_URL (explicit global override)
     *   2. window.BOOKORA_CONFIG.API_URL (pre-set configuration object)
     *   3. Localhost detection:
     *      - If running on port 5000 (monolithic Flask server): '' (relative)
     *      - If running on a standalone static port (3000, 5500, 8080, etc.):
     *        http://<hostname>:5000
     *   4. Production cloud default:
     *      https://bookora-backend-t4w5.onrender.com (or relative if same-origin)
     */
    function resolveApiUrl() {
        // Explicit overrides (useful for testing or runtime environment injection)
        if (typeof global !== 'undefined' && global.BOOKORA_BACKEND_URL) {
            return sanitizeBaseUrl(global.BOOKORA_BACKEND_URL);
        }
        if (typeof global !== 'undefined' && global.BOOKORA_CONFIG && global.BOOKORA_CONFIG.API_URL !== undefined) {
            return sanitizeBaseUrl(global.BOOKORA_CONFIG.API_URL);
        }

        // Browser runtime environment detection
        if (typeof window !== 'undefined' && window.location) {
            const hostname = window.location.hostname || '';
            const port = window.location.port || '';
            const protocol = window.location.protocol || 'http:';

            // Local development
            const isLocal = hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '0.0.0.0';
            if (isLocal) {
                // If the frontend is served directly by the Flask server on port 5000, use relative paths
                if (port === '5000') {
                    return '';
                }
                // If running on a standalone dev server (e.g. port 3000 or 5500), target Flask on 5000
                return `${protocol}//${hostname}:5000`;
            }

            // Production on Render / PaaS
            // If served by Render Static Site on *.onrender.com or custom domain
            if (hostname.endsWith('.onrender.com')) {
                // If this is the backend itself serving static files
                if (hostname.includes('backend') || hostname.includes('api')) {
                    return '';
                }
                // Target the dedicated Render backend web service
                return 'https://bookora-backend-t4w5.onrender.com';
            }

            // Default fallback for other hosted domains
            return '';
        }

        // Default non-browser fallback (testing)
        return 'http://localhost:5000';
    }

    /**
     * Remove trailing slashes from base URL.
     */
    function sanitizeBaseUrl(url) {
        if (!url || typeof url !== 'string') return '';
        return url.trim().replace(/\/+$/, '');
    }

    const BOOKORA_CONFIG = {
        API_URL: resolveApiUrl(),
        DEFAULT_BACKEND_PORT: 5000,
        PRODUCTION_BACKEND_URL: 'https://bookora-backend-t4w5.onrender.com',
        
        /**
         * Dynamically update the backend API URL at runtime.
         */
        setApiUrl: function (url) {
            this.API_URL = sanitizeBaseUrl(url);
        },
        
        /**
         * Get the current active backend API URL.
         */
        getApiUrl: function () {
            return this.API_URL;
        }
    };

    // =========================================================================
    // 2. CENTRALIZED BOOKORA API WRAPPER
    // =========================================================================

    const BookoraAPI = {
        /**
         * Retrieve the configured base URL without trailing slash.
         */
        getBaseUrl: function () {
            return BOOKORA_CONFIG.getApiUrl();
        },

        /**
         * Build a fully qualified target URL from a relative or absolute API path.
         * 
         * Examples:
         *   buildUrl('/api/movies') -> 'http://localhost:5000/api/movies'
         *   buildUrl('api/movies')  -> 'http://localhost:5000/api/movies'
         *   buildUrl('https://api.example.com/data') -> 'https://api.example.com/data'
         */
        buildUrl: function (path) {
            if (!path || typeof path !== 'string') return this.getBaseUrl();
            if (path.startsWith('http://') || path.startsWith('https://')) {
                return path;
            }
            const cleanPath = path.startsWith('/') ? path : '/' + path;
            const baseUrl = this.getBaseUrl();
            return baseUrl ? `${baseUrl}${cleanPath}` : cleanPath;
        },

        /**
         * Unified fetch wrapper supporting cross-origin credentials and default JSON headers.
         * 
         * Guarantees:
         *   - Uses credentials: 'include' by default for cross-origin session cookies.
         *   - Automatically adds 'Content-Type': 'application/json' for JSON request bodies.
         *   - Preserves standard fetch response signature (does NOT swallow errors).
         * 
         * @param {string} path - Relative API endpoint (e.g. '/api/movies') or full URL.
         * @param {RequestInit} [options={}] - Standard fetch options.
         * @returns {Promise<Response>} - Standard Fetch Response promise.
         */
        fetch: function (path, options) {
            const url = this.buildUrl(path);
            const mergedOptions = Object.assign({}, options);

            // Default credentials to 'include' so session cookies work cross-origin
            if (!mergedOptions.credentials) {
                mergedOptions.credentials = 'include';
            }

            // Ensure headers object exists
            mergedOptions.headers = Object.assign({}, mergedOptions.headers);

            // If a body is provided and is a stringified JSON or plain object without explicit Content-Type,
            // set Content-Type to application/json
            if (mergedOptions.body && typeof mergedOptions.body === 'string' && !mergedOptions.headers['Content-Type']) {
                // Check if string looks like JSON
                const trimmed = mergedOptions.body.trim();
                if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || 
                    (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
                    mergedOptions.headers['Content-Type'] = 'application/json';
                }
            } else if (mergedOptions.body && typeof mergedOptions.body === 'object' && 
                       !(mergedOptions.body instanceof FormData) && 
                       !(mergedOptions.body instanceof URLSearchParams) &&
                       !(mergedOptions.body instanceof Blob)) {
                mergedOptions.body = JSON.stringify(mergedOptions.body);
                mergedOptions.headers['Content-Type'] = 'application/json';
            }

            return fetch(url, mergedOptions);
        },

        /**
         * Normalize image paths returned from the database.
         * Converts legacy '/static/posters/...' to '/posters/...' and '/static/banners/...' to '/banners/...'.
         * Preserves absolute URLs and standard relative paths.
         * 
         * @param {string} path - Image path from DB or configuration.
         * @returns {string} - Clean normalized image path.
         */
        resolveImageUrl: function (path) {
            if (!path || typeof path !== 'string') return '';
            if (path.startsWith('http://') || path.startsWith('https://')) {
                return path;
            }
            if (path.startsWith('/static/')) {
                return path.substring(7); // e.g. '/static/posters/foo.jpg' -> '/posters/foo.jpg'
            }
            return path.startsWith('/') ? path : '/' + path;
        }
    };

    // =========================================================================
    // 3. CENTRALIZED ROUTER & PARAMETER PARSING HELPER
    // =========================================================================

    const BookoraRouter = {
        /**
         * Parse search query parameters from current window URL.
         * @param {string} [searchStr] - Optional search string override (for tests).
         * @returns {URLSearchParams}
         */
        getQueryParams: function (searchStr) {
            if (typeof searchStr === 'string') {
                return new URLSearchParams(searchStr);
            }
            if (typeof window !== 'undefined' && window.location) {
                returnURLSearchParamsSafe(window.location.search);
            }
            return new URLSearchParams('');
        },

        /**
         * Extract clean path segments excluding empty parts and .html extensions.
         * @param {string} [pathStr] - Optional path string override (for tests).
         * @returns {string[]}
         */
        getPathSegments: function (pathStr) {
            let pathname = '';
            if (typeof pathStr === 'string') {
                pathname = pathStr;
            } else if (typeof window !== 'undefined' && window.location) {
                pathname = window.location.pathname || '';
            }
            return pathname
                .split('/')
                .map(part => part.trim())
                .filter(part => part.length > 0);
        },

        /**
         * Extract movie slug from URL path or query string.
         * 
         * Supported formats:
         *   - /movie/chhaava
         *   - /movie/chhaava/
         *   - /movie-details.html?slug=chhaava
         *   - /shows/chhaava
         *   - /shows.html?slug=chhaava
         *   - ?slug=chhaava
         * 
         * @param {string} [urlOrSearch] - Optional override string for testing.
         * @returns {string|null}
         */
        getMovieSlug: function (urlOrSearch) {
            // 1. Check query parameter ?slug=...
            if (typeof urlOrSearch === 'string' && urlOrSearch.includes('?')) {
                const searchPart = urlOrSearch.substring(urlOrSearch.indexOf('?'));
                const params = new URLSearchParams(searchPart);
                const rawSlug = params.get('slug');
                if (rawSlug && rawSlug.trim()) {
                    try { return decodeURIComponent(rawSlug.trim()); } catch (e) { return rawSlug.trim(); }
                }
            } else if (typeof window !== 'undefined' && window.location) {
                const params = new URLSearchParams(window.location.search);
                const rawSlug = params.get('slug');
                if (rawSlug && rawSlug.trim()) {
                    try { return decodeURIComponent(rawSlug.trim()); } catch (e) { return rawSlug.trim(); }
                }
            }

            // 2. Check path segments (strip any query part before segment extraction)
            let pathOnly = urlOrSearch;
            if (typeof pathOnly === 'string' && pathOnly.includes('?')) {
                pathOnly = pathOnly.substring(0, pathOnly.indexOf('?'));
            }
            const segments = this.getPathSegments(pathOnly);
            if (segments.length === 0) return null;

            // Known non-slug entry points and system roots
            const rootPages = ['movie', 'shows', 'seats', 'profile', 'my-bookings', 'saved-movies', 
                               'index.html', 'movie-details.html', 'shows.html', 'seat-selection.html', 
                               'profile.html', 'my-bookings.html', 'saved-movies.html'];

            if (segments.length >= 2) {
                const prefix = segments[0].toLowerCase();
                if (prefix === 'movie' || prefix === 'shows' || prefix === 'movie-details.html' || prefix === 'shows.html') {
                    const candidate = segments[1];
                    if (candidate && !candidate.endsWith('.html') && !rootPages.includes(candidate.toLowerCase())) {
                        try { return decodeURIComponent(candidate); } catch (e) { return candidate; }
                    }
                }
            }

            // Check last segment if not a known root page
            const lastSegment = segments[segments.length - 1];
            if (lastSegment && !rootPages.includes(lastSegment.toLowerCase()) && !lastSegment.endsWith('.html')) {
                try { return decodeURIComponent(lastSegment); } catch (e) { return lastSegment; }
            }

            return null;
        },

        /**
         * Extract show/movie slug specifically for the shows page.
         * @param {string} [urlOrSearch] - Optional override string for testing.
         * @returns {string|null}
         */
        getShowSlug: function (urlOrSearch) {
            return this.getMovieSlug(urlOrSearch);
        },

        /**
         * Extract integer show ID for the seat selection page.
         * 
         * Supported formats:
         *   - /seats/123
         *   - /seats/123/
         *   - /seat-selection.html?show_id=123
         *   - ?show_id=123
         *   - ?id=123
         * 
         * @param {string} [urlOrSearch] - Optional override string for testing.
         * @returns {number|null}
         */
        getShowId: function (urlOrSearch) {
            // 1. Check query parameter ?show_id=... or ?id=...
            if (typeof urlOrSearch === 'string' && urlOrSearch.includes('?')) {
                const searchPart = urlOrSearch.substring(urlOrSearch.indexOf('?'));
                const params = new URLSearchParams(searchPart);
                const idStr = params.get('show_id') || params.get('id');
                if (idStr && /^\d+$/.test(idStr.trim())) {
                    return parseInt(idStr.trim(), 10);
                }
            } else if (typeof window !== 'undefined' && window.location) {
                const params = new URLSearchParams(window.location.search);
                const idStr = params.get('show_id') || params.get('id');
                if (idStr && /^\d+$/.test(idStr.trim())) {
                    return parseInt(idStr.trim(), 10);
                }
            }

            // 2. Check path segments (strip query part first)
            let pathOnly = urlOrSearch;
            if (typeof pathOnly === 'string' && pathOnly.includes('?')) {
                pathOnly = pathOnly.substring(0, pathOnly.indexOf('?'));
            }
            const segments = this.getPathSegments(pathOnly);
            if (segments.length >= 2 && (segments[0].toLowerCase() === 'seats' || segments[0].toLowerCase() === 'seat-selection.html')) {
                const candidate = segments[1];
                if (candidate && /^\d+$/.test(candidate)) {
                    return parseInt(candidate, 10);
                }
            }

            // Fallback: check if the last segment is purely numeric
            if (segments.length > 0) {
                const last = segments[segments.length - 1];
                if (/^\d+$/.test(last)) {
                    return parseInt(last, 10);
                }
            }

            return null;
        },

        /**
         * Construct standard URL for movie details page.
         */
        buildMovieUrl: function (slug) {
            if (!slug) return '/';
            return `/movie-details.html?slug=${encodeURIComponent(slug)}`;
        },

        /**
         * Construct standard URL for shows page.
         */
        buildShowsUrl: function (slug) {
            if (!slug) return '/';
            return `/shows.html?slug=${encodeURIComponent(slug)}`;
        },

        /**
         * Construct standard URL for seat selection page.
         */
        buildSeatsUrl: function (showId) {
            if (!showId) return '/';
            return `/seat-selection.html?show_id=${encodeURIComponent(showId)}`;
        },

        /**
         * Construct standard URL for general static pages.
         */
        buildPageUrl: function (page) {
            switch (page) {
                case 'home':
                    return '/index.html';
                case 'profile':
                    return '/profile.html';
                case 'my-bookings':
                case 'bookings':
                    return '/my-bookings.html';
                case 'saved-movies':
                case 'watchlist':
                    return '/saved-movies.html';
                default:
                    return page.endsWith('.html') ? `/${page}` : `/${page}.html`;
            }
        },

        /**
         * Perform browser navigation.
         */
        navigate: function (url, event) {
            if (event && typeof event.preventDefault === 'function') {
                event.preventDefault();
            }
            if (typeof window !== 'undefined' && window.location) {
                window.location.href = url;
            }
        },

        /**
         * Perform browser location replacement (no back button history entry).
         */
        replace: function (url) {
            if (typeof window !== 'undefined' && window.location) {
                window.location.replace(url);
            }
        }
    };

    /**
     * Helper for safe URLSearchParams parsing in older browser edge cases.
     */
    function returnURLSearchParamsSafe(search) {
        try {
            return new URLSearchParams(search || '');
        } catch (e) {
            return {
                get: function (name) {
                    const match = RegExp('[?&]' + name + '=([^&]*)').exec(search || '');
                    return match && decodeURIComponent(match[1].replace(/\+/g, ' '));
                }
            };
        }
    }

    // =========================================================================
    // 4. ENVIRONMENT EXPORT (BROWSER & NODE / TESTING)
    // =========================================================================

    if (typeof global !== 'undefined') {
        global.BOOKORA_CONFIG = BOOKORA_CONFIG;
        global.BookoraAPI = BookoraAPI;
        global.BookoraRouter = BookoraRouter;
    }

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            BOOKORA_CONFIG: BOOKORA_CONFIG,
            BookoraAPI: BookoraAPI,
            BookoraRouter: BookoraRouter
        };
    }

})(typeof window !== 'undefined' ? window : (typeof global !== 'undefined' ? global : this));
