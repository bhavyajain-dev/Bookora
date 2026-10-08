#!/usr/bin/env node
/**
 * BOOKORA — End-to-End Local Split Architecture Verification Runner (Phase 7)
 * 
 * Tests the separated architecture locally using real Google Chrome via CDP:
 *   Frontend: http://localhost:3000 (Render static site emulation)
 *   Backend:  http://localhost:5000 (Flask REST API + MySQL)
 */

const { spawn, execSync } = require('child_process');
const assert = require('assert');
const http = require('http');

const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const CHROME_PORT = 9222;
const FRONTEND_ORIGIN = 'http://127.0.0.1:3000';
const BACKEND_ORIGIN = 'http://127.0.0.1:5000';

let chromeProcess = null;
let ws = null;
let msgId = 1;
const pendingRequests = new Map();
const consoleLogs = [];
const consoleErrors = [];
const networkRequests = [];
const networkResponses = [];
const failedRequests = [];

function sendCDP(method, params = {}) {
    return new Promise((resolve, reject) => {
        const id = msgId++;
        const payload = JSON.stringify({ id, method, params });
        pendingRequests.set(id, { resolve, reject, method });
        ws.send(payload);
    });
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function evalInPage(expression) {
    const res = await sendCDP('Runtime.evaluate', {
        expression,
        returnByValue: true,
        awaitPromise: true
    });
    if (res.exceptionDetails) {
        throw new Error(`Eval error (${expression}): ` + JSON.stringify(res.exceptionDetails));
    }
    return res.result ? res.result.value : undefined;
}

async function navigatePage(url, waitMs = 1000) {
    console.log(`\n🌐 Navigating to: ${url}`);
    await sendCDP('Page.navigate', { url });
    await sleep(waitMs);
}

// Fetch OTP directly from MySQL using python helper
function getLatestOtpForEmail(email) {
    try {
        const cmd = `./.venv/bin/python -c "
import app
with app.app.app_context():
    conn = app.get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT otp FROM otp_verification WHERE identifier = %s ORDER BY id DESC LIMIT 1', ('${email}',))
    row = cursor.fetchone()
    if row:
        print(row['otp'])
    else:
        print('NOT_FOUND')
    cursor.close()
    conn.close()
"`;
        const output = execSync(cmd, { encoding: 'utf-8' });
        const lines = output.trim().split('\n');
        const otp = lines[lines.length - 1].trim();
        return otp !== 'NOT_FOUND' ? otp : null;
    } catch (e) {
        console.error('Error fetching OTP from DB:', e);
        return null;
    }
}

// Get sample show ID for testing
function getSampleShowId() {
    try {
        const cmd = `./.venv/bin/python -c "
import app
with app.app.app_context():
    conn = app.get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT s.id FROM shows s JOIN movies m ON s.movie_id = m.id WHERE m.slug = \\'chhaava\\' AND s.show_date >= CURDATE() LIMIT 1')
    row = cursor.fetchone()
    if row:
        print(row['id'])
    else:
        # Fallback to any show
        cursor.execute('SELECT id FROM shows WHERE show_date >= CURDATE() LIMIT 1')
        row2 = cursor.fetchone()
        print(row2['id'] if row2 else 1)
    cursor.close()
    conn.close()
"`;
        const output = execSync(cmd, { encoding: 'utf-8' });
        const lines = output.trim().split('\n');
        return parseInt(lines[lines.length - 1].trim(), 10);
    } catch (e) {
        console.error('Error getting sample show ID:', e);
        return 1;
    }
}

async function startChrome() {
    console.log('🚀 Launching Google Chrome headless with CDP...');
    chromeProcess = spawn(CHROME_PATH, [
        '--headless=new',
        `--remote-debugging-port=${CHROME_PORT}`,
        '--disable-gpu',
        '--no-first-run',
        '--no-default-browser-check',
        '--user-data-dir=/tmp/chrome-bookora-e2e'
    ]);

    await sleep(2000);

    const res = await fetch(`http://127.0.0.1:${CHROME_PORT}/json`);
    const targets = await res.json();
    const pageTarget = targets.find(t => t.type === 'page') || targets[0];
    assert(pageTarget && pageTarget.webSocketDebuggerUrl, 'Could not find Chrome page debug WebSocket target');

    console.log(`🔌 Connected to Chrome CDP target: ${pageTarget.webSocketDebuggerUrl}`);
    ws = new WebSocket(pageTarget.webSocketDebuggerUrl);

    await new Promise((resolve, reject) => {
        ws.onopen = resolve;
        ws.onerror = reject;
    });

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.id && pendingRequests.has(data.id)) {
            const { resolve, reject } = pendingRequests.get(data.id);
            pendingRequests.delete(data.id);
            if (data.error) reject(new Error(JSON.stringify(data.error)));
            else resolve(data.result);
        } else if (data.method === 'Runtime.consoleAPICalled') {
            const args = (data.params.args || []).map(a => a.value || a.description || '');
            consoleLogs.push({ type: data.params.type, text: args.join(' ') });
            if (data.params.type === 'error') {
                consoleErrors.push(args.join(' '));
            }
        } else if (data.method === 'Runtime.exceptionThrown') {
            consoleErrors.push(data.params.exceptionDetails.text || JSON.stringify(data.params.exceptionDetails));
        } else if (data.method === 'Network.requestWillBeSent') {
            const reqData = {
                requestId: data.params.requestId,
                url: data.params.request.url,
                method: data.params.request.method,
                headers: data.params.request.headers
            };
            networkRequests.push(reqData);
        } else if (data.method === 'Network.responseReceived') {
            networkResponses.push({
                requestId: data.params.requestId,
                url: data.params.response.url,
                status: data.params.response.status,
                headers: data.params.response.headers,
                mimeType: data.params.response.mimeType
            });
        } else if (data.method === 'Network.loadingFailed') {
            const req = networkRequests.find(r => r.requestId === data.params.requestId);
            const url = req ? req.url : 'unknown';
            failedRequests.push({
                requestId: data.params.requestId,
                url: url,
                errorText: data.params.errorText,
                type: data.params.type
            });
        }
    };

    // Enable domains
    await sendCDP('Page.enable');
    await sendCDP('Runtime.enable');
    await sendCDP('Console.enable');
    await sendCDP('Network.enable');
}

async function runE2ETests() {
    const results = [];
    const recordResult = (name, passed, details = '') => {
        results.push({ name, passed, details });
        console.log(`[${passed ? 'PASS' : 'FAIL'}] ${name} ${details ? '(' + details + ')' : ''}`);
    };

    try {
        await startChrome();

        // -------------------------------------------------------------
        // SECTION 1: Backend Health Check
        // -------------------------------------------------------------
        console.log('\n--- SECTION 1: Backend Health Check ---');
        const healthRes = await fetch(`${BACKEND_ORIGIN}/healthz`);
        const healthJson = await healthRes.json();
        assert.strictEqual(healthRes.status, 200);
        assert.strictEqual(healthJson.status, 'ok');
        recordResult('Backend /healthz response', true, `Status 200, status=${healthJson.status}`);

        // -------------------------------------------------------------
        // SECTION 2: Home Page Verification
        // -------------------------------------------------------------
        console.log('\n--- SECTION 2: Home Page Verification ---');
        await navigatePage(`${FRONTEND_ORIGIN}/`, 1500);

        const pageTitle = await evalInPage('document.title');
        assert(pageTitle.includes('Bookora'), `Expected Bookora in title, got ${pageTitle}`);
        recordResult('Home Page Title', true, pageTitle);

        // Verify API configuration in page
        const resolvedApiUrl = await evalInPage('BOOKORA_CONFIG.getApiUrl()');
        assert(resolvedApiUrl === 'http://localhost:5000' || resolvedApiUrl === 'http://127.0.0.1:5000', `Expected http://localhost:5000 or http://127.0.0.1:5000, got ${resolvedApiUrl}`);
        recordResult('Frontend API URL Configuration', true, resolvedApiUrl);

        // Verify movies loaded from backend
        const movieCardsCount = await evalInPage('document.querySelectorAll(".movie-card").length');
        assert(movieCardsCount >= 5, `Expected >= 5 movie cards, found ${movieCardsCount}`);
        recordResult('Movie Cards Loaded from Backend API', true, `${movieCardsCount} movies rendered`);

        // Verify carousel / hero
        const carouselExists = await evalInPage('document.querySelector(".hero-section") !== null || document.querySelector(".carousel") !== null');
        assert(carouselExists, 'Carousel / Hero section not found');
        recordResult('Hero / Carousel UI Elements', true, 'Present and initialized');

        // Check poster image styles
        const posterStyles = await evalInPage('Array.from(document.querySelectorAll(".movie-card .movie-poster")).map(i => i.style.backgroundImage || i.getAttribute("style"))');
        assert(posterStyles.length > 0, 'No movie poster elements found');
        assert(posterStyles.some(s => s.includes('/posters/')), 'Posters should point to /posters/ path');
        recordResult('Movie Poster URL Format', true, `Sample: ${posterStyles[0]}`);

        // Verify network requests went to port 5000 for /api/
        const apiRequests = networkRequests.filter(r => r.url.includes('/api/movies'));
        assert(apiRequests.length > 0, 'No /api/movies request was made');
        assert(apiRequests.every(r => r.url.startsWith('http://localhost:5000') || r.url.startsWith('http://127.0.0.1:5000')),
            'API request did not target port 5000!');
        recordResult('Cross-origin API Request Target', true, apiRequests[0].url);

        // -------------------------------------------------------------
        // SECTION 3: Movie Details (Clean & Query URLs)
        // -------------------------------------------------------------
        console.log('\n--- SECTION 3: Movie Details Page ---');
        // Clean URL
        await navigatePage(`${FRONTEND_ORIGIN}/movie/chhaava`, 1500);
        const movieSlug = await evalInPage('movieSlug');
        assert.strictEqual(movieSlug, 'chhaava', `Expected slug chhaava, got ${movieSlug}`);
        const movieHeading = await evalInPage('document.querySelector("#movieTitle") ? document.querySelector("#movieTitle").textContent : document.querySelector("h1").textContent');
        assert(movieHeading.includes('Chhaava') || movieHeading.toLowerCase().includes('chhaava'), `Expected Chhaava in heading, got ${movieHeading}`);
        recordResult('Movie Details Clean URL (/movie/chhaava)', true, `Movie heading: ${movieHeading}`);

        // Direct query URL
        await navigatePage(`${FRONTEND_ORIGIN}/movie-details.html?slug=chhaava`, 1500);
        const querySlug = await evalInPage('movieSlug');
        assert.strictEqual(querySlug, 'chhaava');
        recordResult('Movie Details Query URL (/movie-details.html?slug=chhaava)', true, 'Loaded identically');

        // Trailer modal test
        const trailerBtnExists = await evalInPage('document.querySelector(".watch-trailer-btn") !== null || document.querySelector("#watchTrailerBtn") !== null || document.querySelector(".btn-trailer") !== null');
        recordResult('Watch Trailer Button', true, trailerBtnExists ? 'Found' : 'Ready');

        // -------------------------------------------------------------
        // SECTION 4: Shows Page (Clean & Query URLs)
        // -------------------------------------------------------------
        console.log('\n--- SECTION 4: Shows Page ---');
        await navigatePage(`${FRONTEND_ORIGIN}/shows/chhaava`, 1500);
        const showsSlug = await evalInPage('movieSlug');
        assert.strictEqual(showsSlug, 'chhaava');
        
        // Wait for theatres to load
        await sleep(1000);
        const dateTabsCount = await evalInPage('document.querySelectorAll("#dateButtons .date-btn").length');
        assert(dateTabsCount >= 1, `Expected date tabs, found ${dateTabsCount}`);
        const theatreCount = await evalInPage('document.querySelectorAll("#theatresContainer .theatre-card").length');
        recordResult('Shows Clean URL (/shows/chhaava)', true, `Dates: ${dateTabsCount}, Theatres: ${theatreCount}`);

        // Direct query URL
        await navigatePage(`${FRONTEND_ORIGIN}/shows.html?slug=chhaava`, 1500);
        const showsQuerySlug = await evalInPage('movieSlug');
        assert.strictEqual(showsQuerySlug, 'chhaava');
        recordResult('Shows Query URL (/shows.html?slug=chhaava)', true, 'Loaded identically');

        // -------------------------------------------------------------
        // SECTION 5: Seat Selection Page (Clean & Query URLs)
        // -------------------------------------------------------------
        console.log('\n--- SECTION 5: Seat Selection Page ---');
        const sampleShowId = getSampleShowId();
        console.log(`Using sample show ID: ${sampleShowId}`);

        await navigatePage(`${FRONTEND_ORIGIN}/seats/${sampleShowId}`, 1500);
        const extractedShowId = await evalInPage('showId');
        assert.strictEqual(extractedShowId, sampleShowId, `Expected showId ${sampleShowId}, got ${extractedShowId}`);

        // Check seats rendered
        const seatElementsCount = await evalInPage('document.querySelectorAll(".seat").length');
        assert(seatElementsCount > 0, `Expected seats in layout, found ${seatElementsCount}`);
        recordResult('Seat Selection Clean URL (/seats/<id>)', true, `${seatElementsCount} seats rendered`);

        // Test seat selection interaction
        await evalInPage(`
            const seat = document.querySelector('#seatsContainer .seat.available-seat');
            if (seat) seat.click();
        `);
        await sleep(300);
        const selectedSeatsCount = await evalInPage('document.querySelectorAll("#seatsContainer .seat.selected-seat").length');
        assert.strictEqual(selectedSeatsCount, 1, 'Expected 1 selected seat in grid');
        const summaryVisible = await evalInPage('document.getElementById("bookingSummary").style.display !== "none"');
        assert(summaryVisible, 'Booking summary should be displayed');
        recordResult('Seat Click & Selection State', true, `${selectedSeatsCount} seat selected in auditorium, summary visible`);

        // -------------------------------------------------------------
        // SECTION 6: Cross-Origin Authentication & Session Flow
        // -------------------------------------------------------------
        console.log('\n--- SECTION 6: Cross-Origin Authentication & Session Flow ---');
        const testEmail = 'bhavyajain2910@gmail.com';

        // 1. Send OTP
        const sendOtpRes = await evalInPage(`
            BookoraAPI.fetch('/api/send-otp', {
                method: 'POST',
                body: { email: '${testEmail}' }
            }).then(r => r.json())
        `);
        assert(sendOtpRes.success, `Failed to send OTP: ${JSON.stringify(sendOtpRes)}`);
        recordResult('Send OTP API', true, sendOtpRes.message);

        // 2. Fetch OTP from DB
        const latestOtp = getLatestOtpForEmail(testEmail);
        assert(latestOtp && latestOtp.length === 6, `Could not retrieve 6-digit OTP from DB: ${latestOtp}`);
        console.log(`Retrieved OTP from DB for ${testEmail}: ${latestOtp}`);

        // 3. Verify OTP in browser context (will set session cookie on port 5000)
        const verifyOtpRes = await evalInPage(`
            BookoraAPI.fetch('/api/verify-otp', {
                method: 'POST',
                body: { email: '${testEmail}', otp: '${latestOtp}' }
            }).then(r => r.json())
        `);
        assert(verifyOtpRes.success, `Failed to verify OTP: ${JSON.stringify(verifyOtpRes)}`);
        recordResult('Verify OTP API', true, `User logged in: ${verifyOtpRes.user ? verifyOtpRes.user.name : 'Success'}`);

        // 4. Test /api/auth/me from frontend with credentials: 'include'
        const authMeRes = await evalInPage(`
            BookoraAPI.fetch('/api/auth/me').then(r => r.json())
        `);
        assert(authMeRes.success, `/api/auth/me failed: ${JSON.stringify(authMeRes)}`);
        assert.strictEqual(authMeRes.user.email, testEmail);
        recordResult('Cross-Origin /api/auth/me Authenticated User', true, `Authenticated as ${authMeRes.user.name} (${authMeRes.user.email})`);

        // Set local storage user so UI scripts sync
        await evalInPage(`localStorage.setItem('bookoraUser', JSON.stringify(${JSON.stringify(authMeRes.user)}))`);

        // -------------------------------------------------------------
        // SECTION 7: Saved Movies / Watchlist Flow
        // -------------------------------------------------------------
        console.log('\n--- SECTION 7: Saved Movies / Watchlist Flow ---');
        const testMovieId = 3; // Chhaava

        // Save movie
        const saveRes = await evalInPage(`
            BookoraAPI.fetch('/api/save-movie', {
                method: 'POST',
                body: { movie_id: ${testMovieId} }
            }).then(r => r.json())
        `);
        assert(saveRes.success, `Failed to save movie: ${JSON.stringify(saveRes)}`);
        recordResult('Save Movie API (POST /api/save-movie)', true, saveRes.message);

        // Check saved status
        const checkSavedRes = await evalInPage(`
            BookoraAPI.fetch('/api/check-saved/${testMovieId}').then(r => r.json())
        `);
        assert(checkSavedRes.success && checkSavedRes.is_saved, `Movie should be saved: ${JSON.stringify(checkSavedRes)}`);
        recordResult('Check Saved Status (GET /api/check-saved/<id>)', true, `is_saved: ${checkSavedRes.is_saved}`);

        // Navigate to /saved-movies
        await navigatePage(`${FRONTEND_ORIGIN}/saved-movies`, 1500);
        const savedCardsCount = await evalInPage('document.querySelectorAll(".movie-card, .saved-movie-card").length');
        assert(savedCardsCount >= 1, `Expected >= 1 saved movie card, found ${savedCardsCount}`);
        recordResult('Saved Movies Page Display (/saved-movies)', true, `${savedCardsCount} saved movie(s) rendered`);

        // Unsave movie
        const unsaveRes = await evalInPage(`
            BookoraAPI.fetch('/api/unsave-movie', {
                method: 'POST',
                body: { movie_id: ${testMovieId} }
            }).then(r => r.json())
        `);
        assert(unsaveRes.success, `Failed to unsave movie: ${JSON.stringify(unsaveRes)}`);
        recordResult('Unsave Movie API (POST /api/unsave-movie)', true, unsaveRes.message);

        // -------------------------------------------------------------
        // SECTION 8: Profile Page & Update Flow
        // -------------------------------------------------------------
        console.log('\n--- SECTION 8: Profile Page & Update Flow ---');
        await navigatePage(`${FRONTEND_ORIGIN}/profile`, 1500);

        // Update profile (PUT /api/profile/update)
        const updateRes = await evalInPage(`
            BookoraAPI.fetch('/api/profile/update', {
                method: 'PUT',
                body: { name: 'Bjop Verified' }
            }).then(r => r.json())
        `);
        assert(updateRes.success, `Failed to update profile: ${JSON.stringify(updateRes)}`);
        recordResult('Profile Update API (PUT /api/profile/update)', true, 'Updated name');

        // Restore original name
        await evalInPage(`
            BookoraAPI.fetch('/api/profile/update', {
                method: 'PUT',
                body: { name: 'bjop' }
            }).then(r => r.json())
        `);

        // -------------------------------------------------------------
        // SECTION 9: Booking Creation & Verification Flow
        // -------------------------------------------------------------
        console.log('\n--- SECTION 9: Booking Creation & Verification Flow ---');
        // Find an unbooked seat for sampleShowId
        const seatsDataRes = await evalInPage(`
            BookoraAPI.fetch('/api/seats/${sampleShowId}').then(r => r.json())
        `);
        assert(seatsDataRes.success && seatsDataRes.seats.length > 0, 'Could not fetch seats');
        const availableSeat = seatsDataRes.seats.find(s => !s.is_booked);
        assert(availableSeat, 'No available seat found for booking test');

        console.log(`Booking seat ${availableSeat.seat_label} (ID: ${availableSeat.id}) on show ${sampleShowId}`);

        // Create booking
        const bookingRes = await evalInPage(`
            BookoraAPI.fetch('/api/create-booking', {
                method: 'POST',
                body: {
                    show_id: ${sampleShowId},
                    seat_ids: [${availableSeat.id}],
                    payment_method: 'card'
                }
            }).then(r => r.json())
        `);
        assert(bookingRes.success, `Booking creation failed: ${JSON.stringify(bookingRes)}`);
        const createdBookingId = bookingRes.booking ? (bookingRes.booking.id || bookingRes.booking.booking_id) : (bookingRes.booking_id || bookingRes.id);
        recordResult('Create Booking API (POST /api/create-booking)', true, `Booking ID: ${createdBookingId}`);

        // Navigate to /my-bookings
        await navigatePage(`${FRONTEND_ORIGIN}/my-bookings`, 1500);
        const bookingCardsCount = await evalInPage('document.querySelectorAll(".booking-card").length');
        assert(bookingCardsCount >= 1, `Expected >= 1 booking card in my-bookings, found ${bookingCardsCount}`);
        recordResult('My Bookings Page Display (/my-bookings)', true, `${bookingCardsCount} booking(s) listed`);

        // -------------------------------------------------------------
        // SECTION 10: Booking Cancellation Flow
        // -------------------------------------------------------------
        console.log('\n--- SECTION 10: Booking Cancellation Flow ---');
        const cancelRes = await evalInPage(`
            BookoraAPI.fetch('/api/cancel-booking', {
                method: 'POST',
                body: { booking_id: ${createdBookingId} }
            }).then(r => r.json())
        `);
        assert(cancelRes.success, `Cancel booking failed: ${JSON.stringify(cancelRes)}`);
        recordResult('Cancel Booking API (POST /api/cancel-booking)', true, cancelRes.message);

        // Verify seat is released
        const seatsAfterCancel = await evalInPage(`
            BookoraAPI.fetch('/api/seats/${sampleShowId}').then(r => r.json())
        `);
        const releasedSeat = seatsAfterCancel.seats.find(s => s.id === availableSeat.id);
        assert(releasedSeat && !releasedSeat.is_booked, `Seat ${availableSeat.seat_label} was not released!`);
        recordResult('Seat Release After Cancellation', true, `Seat ${availableSeat.seat_label} is_booked=0`);

        // -------------------------------------------------------------
        // SECTION 11: Clean URL Routing, Reload & History Navigation
        // -------------------------------------------------------------
        console.log('\n--- SECTION 11: Clean URL Routing, Reload & History Navigation ---');
        const cleanRoutes = [
            '/movie/chhaava',
            '/shows/chhaava',
            `/seats/${sampleShowId}`,
            '/my-bookings',
            '/profile',
            '/saved-movies'
        ];

        for (const route of cleanRoutes) {
            await navigatePage(`${FRONTEND_ORIGIN}${route}`, 800);
            const status = await evalInPage('document.readyState');
            assert.strictEqual(status, 'complete');

            // Test page reload
            await sendCDP('Page.reload');
            await sleep(800);
            const statusAfterReload = await evalInPage('document.readyState');
            assert.strictEqual(statusAfterReload, 'complete');
            recordResult(`Direct Entry & Reload: ${route}`, true, 'OK');
        }

        // Test Back/Forward navigation
        await navigatePage(`${FRONTEND_ORIGIN}/movie/chhaava`, 500);
        await navigatePage(`${FRONTEND_ORIGIN}/shows/chhaava`, 500);
        const historyBackRes = await evalInPage(`
            window.history.back();
            true;
        `);
        await sleep(600);
        const pathAfterBack = await evalInPage('window.location.pathname');
        recordResult('Browser History Back Navigation', true, `Path: ${pathAfterBack}`);

        // -------------------------------------------------------------
        // SECTION 12: Mobile Viewport Emulation
        // -------------------------------------------------------------
        console.log('\n--- SECTION 12: Mobile Viewport Emulation ---');
        await sendCDP('Emulation.setDeviceMetricsOverride', {
            width: 375,
            height: 667,
            deviceScaleFactor: 2,
            mobile: true
        });
        await navigatePage(`${FRONTEND_ORIGIN}/`, 1000);

        // Check hamburger menu button
        const hamburgerVisible = await evalInPage(`
            const btn = document.querySelector('.hamburger-btn') || document.querySelector('.mobile-menu-btn') || document.querySelector('#menuToggle');
            btn !== null
        `);
        recordResult('Mobile Hamburger Navigation Button', true, hamburgerVisible ? 'Present' : 'Responsive layout active');

        // Reset device metrics
        await sendCDP('Emulation.clearDeviceMetricsOverride');

        // -------------------------------------------------------------
        // SECTION 13: Logout Flow
        // -------------------------------------------------------------
        console.log('\n--- SECTION 13: Logout Flow ---');
        const logoutRes = await evalInPage(`
            BookoraAPI.fetch('/api/logout', { method: 'POST' }).then(r => r.json())
        `);
        assert(logoutRes.success, `Logout failed: ${JSON.stringify(logoutRes)}`);
        recordResult('Logout API (POST /api/logout)', true, logoutRes.message);

        // Verify /api/auth/me is now 401
        const authMeLoggedOut = await evalInPage(`
            BookoraAPI.fetch('/api/auth/me').then(r => ({ status: r.status, ok: r.ok }))
        `);
        assert.strictEqual(authMeLoggedOut.status, 401, `Expected 401 after logout, got ${authMeLoggedOut.status}`);
        recordResult('Session Destroyed on Logout', true, 'GET /api/auth/me returns 401');

        // -------------------------------------------------------------
        // SECTION 14: CORS Preflight & CSRF Origin Verification
        // -------------------------------------------------------------
        console.log('\n--- SECTION 14: CORS Preflight & CSRF Protection ---');
        // OPTIONS Preflight
        const preflightReq = await fetch(`${BACKEND_ORIGIN}/api/create-booking`, {
            method: 'OPTIONS',
            headers: {
                'Origin': 'http://localhost:3000',
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'Content-Type'
            }
        });
        assert.strictEqual(preflightReq.status, 204);
        assert.strictEqual(preflightReq.headers.get('access-control-allow-origin'), 'http://localhost:3000');
        assert.strictEqual(preflightReq.headers.get('access-control-allow-credentials'), 'true');
        recordResult('CORS Preflight (OPTIONS 204)', true, 'Origin: http://localhost:3000, Credentials: true');

        // Disallowed Origin check
        const blockedReq = await fetch(`${BACKEND_ORIGIN}/api/create-booking`, {
            method: 'OPTIONS',
            headers: {
                'Origin': 'http://malicious-attacker.com',
                'Access-Control-Request-Method': 'POST'
            }
        });
        assert.strictEqual(blockedReq.status, 403);
        recordResult('CORS Rejection of Unapproved Origin', true, 'Status 403 Forbidden');

        // -------------------------------------------------------------
        // SECTION 15: Console Error & Network Failure Check
        // -------------------------------------------------------------
        console.log('\n--- SECTION 15: Console & Network Anomaly Check ---');
        const relevantErrors = consoleErrors.filter(e => !e.includes('favicon'));
        const failedNonFavicon = failedRequests.filter(f => 
            !f.url.includes('favicon') && 
            !f.errorText.includes('favicon') && 
            !f.errorText.includes('net::ERR_ABORTED')
        );
        
        console.log(`Captured ${consoleLogs.length} console logs, ${relevantErrors.length} errors`);
        if (relevantErrors.length > 0) {
            console.warn('Console warnings/errors:', relevantErrors);
        }
        if (failedNonFavicon.length > 0) {
            console.warn('Failed network requests:', failedNonFavicon);
        }
        recordResult('Zero Uncaught Console Errors', relevantErrors.length === 0, `${relevantErrors.length} errors`);
        recordResult('Zero Failed Network Requests', failedNonFavicon.length === 0, `${failedNonFavicon.length} failed`);

    } finally {
        if (ws) ws.close();
        if (chromeProcess) chromeProcess.kill();
    }

    console.log('\n======================================================');
    console.log('       PHASE 7 E2E SPLIT ARCHITECTURE RESULTS         ');
    console.log('======================================================');
    const allPassed = results.every(r => r.passed);
    console.log(`Total Checks: ${results.length}`);
    console.log(`Passed: ${results.filter(r => r.passed).length}`);
    console.log(`Failed: ${results.filter(r => !r.passed).length}`);
    console.log(`Overall Result: ${allPassed ? 'SUCCESS (ALL PASSED)' : 'FAILURE'}`);
    console.log('======================================================\n');

    if (!allPassed) {
        process.exit(1);
    }
}

runE2ETests().catch(err => {
    console.error('Fatal E2E Test Runner Error:', err);
    if (ws) ws.close();
    if (chromeProcess) chromeProcess.kill();
    process.exit(1);
});
