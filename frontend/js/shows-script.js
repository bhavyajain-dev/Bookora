/**
 * Shows Page - Clean Database-Driven Implementation
 * No static JSON, no fallbacks, pure MySQL data
 */

// Get movie slug from URL via BookoraRouter or fallback
const movieSlug = (typeof BookoraRouter !== 'undefined' && BookoraRouter.getShowSlug) 
    ? BookoraRouter.getShowSlug() 
    : window.location.pathname.split('/').filter(part => part.length > 0).pop();

let movieData = null;
let selectedDate = getTodayDate();

console.log('🎬 SHOWS PAGE INITIALIZED');
console.log('   → Movie slug from URL:', movieSlug);
console.log('   → Initial selected date:', selectedDate);

// ==========================================
// AUTHENTICATION CHECK
// ==========================================

function checkAuth() {
    const user = JSON.parse(localStorage.getItem('bookoraUser') || 'null');
    
    if (user) {
        // User is logged in
        document.getElementById('loggedOutState').style.display = 'none';
        document.getElementById('loggedInState').style.display = 'flex';
        
        // Update profile info
        const displayName = user.name || 'User';
        const displayContact = user.email || user.phone || '';
        
        document.getElementById('profileDisplayName').textContent = displayName;
        document.getElementById('profileDisplayContact').textContent = displayContact;
    } else {
        // User is logged out
        document.getElementById('loggedOutState').style.display = 'flex';
        document.getElementById('loggedInState').style.display = 'none';
    }
}

// Profile dropdown toggle
function toggleProfileDropdown() {
    const dropdown = document.getElementById('profileDropdown');
    dropdown.classList.toggle('active');
}

// Navigation functions
function navigateToProfile(event) {
    if (event) event.preventDefault();
    window.location.href = (typeof BookoraRouter !== 'undefined' && BookoraRouter.buildPageUrl) ? BookoraRouter.buildPageUrl('profile') : '/profile';
}

function navigateToBookings(event) {
    if (event) event.preventDefault();
    window.location.href = (typeof BookoraRouter !== 'undefined' && BookoraRouter.buildPageUrl) ? BookoraRouter.buildPageUrl('my-bookings') : '/my-bookings';
}

function navigateToSavedMovies(event) {
    if (event) event.preventDefault();
    window.location.href = (typeof BookoraRouter !== 'undefined' && BookoraRouter.buildPageUrl) ? BookoraRouter.buildPageUrl('saved-movies') : '/saved-movies';
}

// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    const profileContainer = document.querySelector('.profile-container');
    const dropdown = document.getElementById('profileDropdown');
    
    if (profileContainer && dropdown && !profileContainer.contains(e.target)) {
        dropdown.classList.remove('active');
    }
});

// ==========================================
// DATE HELPERS
// ==========================================

// Date helpers
function getTodayDate() {
    return getIndiaCalendarDate();
}

// Shows are sold on an India business calendar. `toISOString()` uses UTC and
// was one day behind in India shortly after midnight; derive the date in IST
// first, then add calendar days in UTC so a visitor's browser timezone cannot
// change the seven dates Bookora offers.
function getIndiaCalendarDate(daysFromToday = 0) {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(new Date()).reduce((values, part) => {
        if (part.type !== 'literal') values[part.type] = part.value;
        return values;
    }, {});
    const calendarDay = new Date(Date.UTC(
        Number(parts.year), Number(parts.month) - 1, Number(parts.day) + daysFromToday
    ));
    return calendarDay.toISOString().slice(0, 10);
}

function formatDateForDisplay(dateStr) {
    const date = new Date(dateStr + 'T12:00:00Z');
    const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
    const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
    
    const dayName = days[date.getUTCDay()];
    const monthName = months[date.getUTCMonth()];
    const dayNum = date.getUTCDate();
    
    return `${dayName}, ${monthName} ${dayNum}`;
}

function getNextDates(count = 7) {
    const dates = [];
    for (let i = 0; i < count; i++) {
        dates.push(getIndiaCalendarDate(i));
    }
    return dates;
}

// Convert 24-hour time to 12-hour format with AM/PM
function formatTimeTo12Hour(time24) {
    const [hours, minutes] = time24.split(':').map(Number);
    const period = hours >= 12 ? 'PM' : 'AM';
    const hours12 = hours % 12 || 12;
    return `${hours12}:${minutes.toString().padStart(2, '0')} ${period}`;
}

// ==========================================
// LOAD MOVIE DETAILS
// ==========================================

// Load movie details
async function loadMovie() {
    try {
        console.log('\n📡 LOADING MOVIE DATA...');
        console.log('   → Fetching from:', `/api/movies/slug/${movieSlug}`);
        
        const response = await (window.BookoraAPI 
            ? BookoraAPI.fetch(`/api/movies/slug/${movieSlug}`) 
            : fetch(`/api/movies/slug/${movieSlug}`));
        const data = await response.json();
        
        console.log('   → API Response:', data);
        
        if (!data.success) {
            throw new Error(data.message);
        }
        
        movieData = data.movie;
        
        console.log('   ✅ Movie loaded:', {
            id: movieData.id,
            title: movieData.title,
            slug: movieData.slug
        });
        
        // Update UI
        document.getElementById('movieTitle').textContent = movieData.title;
        document.getElementById('movieDetails').textContent = 
            `${movieData.language} • ${movieData.duration} min • ${movieData.certification}`;
        
        document.title = `${movieData.title} - Select Show - Bookora`;
        
    } catch (error) {
        console.error('❌ Error loading movie:', error);
        document.getElementById('movieTitle').textContent = 'Error Loading Movie';
        document.getElementById('movieDetails').textContent = error.message;
    }
}

// ==========================================
// RENDER DATE BUTTONS
// ==========================================

// Render date buttons
function renderDateButtons() {
    const container = document.getElementById('dateButtons');
    const dates = getNextDates(7);
    
    container.innerHTML = dates.map(date => `
        <button 
            class="date-btn ${date === selectedDate ? 'active' : ''}"
            onclick="selectDate('${date}')"
        >
            ${formatDateForDisplay(date)}
        </button>
    `).join('');
}

// Select date
function selectDate(date) {
    selectedDate = date;
    renderDateButtons();
    loadShows();
}

// ==========================================
// LOAD SHOWS
// ==========================================

// Load shows
async function loadShows() {
    const container = document.getElementById('theatresContainer');
    container.innerHTML = `
        <div class="bookora-loader-wrapper" style="min-height: 250px;">
            <div class="bookora-spinner"></div>
            <div class="bookora-loader-text">Finding available theatres and showtimes...</div>
        </div>
    `;
    
    try {
        const slug = (movieData && movieData.slug) || movieSlug;
        console.log('\n🎭 LOADING SHOWS...');
        console.log('   → Movie Slug:', slug);
        console.log('   → Selected Date:', selectedDate);
        
        // Use slug parameter (backend will resolve to ID)
        const apiUrl = `/api/shows?slug=${encodeURIComponent(slug)}&date=${encodeURIComponent(selectedDate)}`;
        console.log('   → Fetching from:', apiUrl);
        
        const response = await (window.BookoraAPI ? BookoraAPI.fetch(apiUrl) : fetch(apiUrl));
        const data = await response.json();
        
        console.log('   → API Response:', data);
        
        if (!data.success) {
            throw new Error(data.message);
        }
        
        if (!data.theatres || data.theatres.length === 0) {
            console.log('   ⚠️  No shows available for this date');
            container.innerHTML = `
                <div class="no-shows">
                    <h3>No Shows Available</h3>
                    <p>There are no shows scheduled for this date. Please select another date.</p>
                </div>
            `;
            return;
        }
        
        console.log(`   ✅ Received ${data.theatres.length} theatres with shows:`);
        data.theatres.forEach(theatre => {
            console.log(`      → ${theatre.name}: ${theatre.shows.length} shows`);
        });
        
        // Render theatres
        container.innerHTML = data.theatres.map(theatre => `
            <div class="theatre-card">
                <div class="theatre-name">${theatre.name}</div>
                <div class="theatre-location">${theatre.address}</div>
                <div class="showtimes">
                    ${theatre.shows.map(show => {
                        // The API excludes started shows using India business
                        // time; it remains authoritative if a show starts after
                        // this response but before the user chooses it.
                        const isExpired = false;
                        const isSoldOut = show.available_seats === 0;
                        const isDisabled = isExpired || isSoldOut;
                        
                        // Format time to 12-hour format
                        const formattedTime = formatTimeTo12Hour(show.time);
                        
                        return `
                        <button 
                            class="showtime-btn ${isExpired ? 'show-expired' : ''} ${isSoldOut ? 'disabled' : ''}"
                            onclick="selectShow(${show.show_id})"
                            ${isDisabled ? 'disabled' : ''}
                        >
                            <div>${formattedTime}</div>
                            <div class="seats-info">
                                ${isExpired 
                                    ? '<small class="booking-closed">Booking Closed</small>' 
                                    : `${show.available_seats} seats`
                                }
                            </div>
                        </button>
                        `;
                    }).join('')}
                </div>
            </div>
        `).join('');
        
        console.log('   ✅ Shows rendered successfully\n');
        
    } catch (error) {
        console.error('❌ Error loading shows:', error);
        container.innerHTML = `<div class="error-msg">Error loading shows: ${error.message}</div>`;
    }
}

// ==========================================
// SELECT SHOW
// ==========================================

// Select show - navigate to seats page
function selectShow(showId) {
    if (typeof BookoraRouter !== 'undefined' && BookoraRouter.buildSeatsUrl) {
        window.location.href = BookoraRouter.buildSeatsUrl(showId);
    } else {
        window.location.href = `/seats/${showId}`;
    }
}

// ==========================================
// INITIALIZE
// ==========================================

// Check auth state on page load
checkAuth();

// Render date buttons immediately
renderDateButtons();

// Load movie metadata and shows in parallel for optimal responsiveness
Promise.all([loadMovie(), loadShows()]);
