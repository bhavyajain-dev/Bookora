// Configuration & Router
const API_URL = (typeof BOOKORA_CONFIG !== 'undefined') ? BOOKORA_CONFIG.getApiUrl() : '';

// Get movie slug from BookoraRouter or fallback to URL path
const movieSlug = (typeof BookoraRouter !== 'undefined' && BookoraRouter.getMovieSlug) 
    ? BookoraRouter.getMovieSlug() 
    : window.location.pathname.split('/').filter(part => part.length > 0).pop();

console.log('Movie slug:', movieSlug);
console.log('Full pathname:', window.location.pathname);

// Global state
let currentMovie = null;
let isMovieSaved = false;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    if (!movieSlug || movieSlug === 'movie' || movieSlug === 'movie-details.html') {
        showError('Movie not found');
        return;
    }
    
    initTrailerButtons();
    loadMovieDetails();
});



// Load movie details from API
async function loadMovieDetails() {
    console.log('Loading movie details for slug:', movieSlug);
    
    try {
        const response = await (window.BookoraAPI 
            ? BookoraAPI.fetch(`/api/movies/slug/${movieSlug}`) 
            : fetch(`${API_URL}/api/movies/slug/${movieSlug}`));
        const data = await response.json();
        
        console.log('API Response:', data);
        
        if (data.success) {
            currentMovie = data.movie;
            console.log('Movie data:', currentMovie);
            displayMovieDetails(data.movie);
            initScrollHandler();
            // Check saved status asynchronously (don't block page load)
            checkSavedStatus().catch(err => console.error('Error checking saved status:', err));
        } else {
            showError(data.message || 'Movie not found');
        }
    } catch (error) {
        console.error('Error loading movie details:', error);
        showError('Unable to connect to server. Please try again later.');
    }
}

// Display movie details
function displayMovieDetails(movie) {
    // Set document title
    document.title = `${movie.title} - Bookora`;
    
    // Hero banner background
    const banner = document.getElementById('movieBanner');
    if (banner && movie.banner_url) {
        const resolvedBanner = (typeof BookoraAPI !== 'undefined' && BookoraAPI.resolveImageUrl) 
            ? BookoraAPI.resolveImageUrl(movie.banner_url) 
            : movie.banner_url;
        banner.style.backgroundImage = `url('${resolvedBanner}')`;
        banner.style.backgroundSize = 'cover';
        banner.style.backgroundPosition = 'center';
        console.log('Banner URL:', resolvedBanner);
    }
    
    // Banner Poster (LEFT ZONE)
    const posterImg = document.getElementById('bannerPoster');
    if (posterImg && movie.poster_url) {
        const resolvedPoster = (typeof BookoraAPI !== 'undefined' && BookoraAPI.resolveImageUrl) 
            ? BookoraAPI.resolveImageUrl(movie.poster_url) 
            : movie.poster_url;
        posterImg.src = resolvedPoster;
        posterImg.alt = movie.title;
        console.log('Poster URL:', resolvedPoster);
    }
    
    // Title (CENTER ZONE)
    const titleEl = document.getElementById('movieTitle');
    if (titleEl) titleEl.textContent = movie.title;
    
    // Set navbar movie title for scroll state
    const navbarTitle = document.getElementById('navbarTitleTextScrolled');
    if (navbarTitle) navbarTitle.textContent = movie.title;

    // Metadata Rows (CENTER ZONE)
    const metadataEl = document.getElementById('bannerMetadata');
    if (metadataEl) {
        const languages = Array.isArray(movie.language) ? movie.language.join(', ') : movie.language;
        const genres = Array.isArray(movie.genre) ? movie.genre.join(', ') : movie.genre;
        
        metadataEl.innerHTML = `
            <div class="metadata-row">
                <i class="fas fa-clock"></i>
                <span>${formatDuration(movie.duration)}</span>
            </div>
            <div class="metadata-row">
                <i class="fas fa-film"></i>
                <span>${genres}</span>
            </div>
            <div class="metadata-row">
                <i class="fas fa-language"></i>
                <span>${languages}</span>
            </div>
            <div class="metadata-row">
                <i class="fas fa-info-circle"></i>
                <span>${movie.certification || 'UA'}</span>
            </div>
            <div class="metadata-row">
                <i class="fas fa-calendar-alt"></i>
                <span>${formatDate(movie.release_date)}</span>
            </div>
        `;
    }
    
    // Movie info section - REMOVED (already shown in banner)
    
    // Description
    const descEl = document.getElementById('movieDescription');
    if (descEl) descEl.textContent = movie.description || 'No description available.';
    
    // Cast
    const castEl = document.getElementById('movieCast');
    if (castEl && movie.cast) {
        const castArray = Array.isArray(movie.cast) ? movie.cast : movie.cast.split(',').map(c => c.trim());
        const castHTML = castArray.map(actor => 
            `<div class="cast-item">${actor}</div>`
        ).join('');
        castEl.innerHTML = castHTML;
    }
}

// Format duration (minutes to hours and minutes)
function formatDuration(minutes) {
    if (!minutes) return 'N/A';
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
}

// Format date
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { 
        year: 'numeric', 
        month: 'long', 
        day: 'numeric' 
    });
}

// Show error
function showError(message) {
    console.error('Error:', message);
    alert(message);
}

// ==========================================
// SCROLL HANDLER - NAVBAR STATE MANAGEMENT
// ==========================================
function initScrollHandler() {
    const bannerHeight = document.getElementById('movieBanner')?.offsetHeight || 500;
    const navbarLogo = document.getElementById('navbarLogo');
    const navbarMenu = document.getElementById('navbarMenu');
    const navbarCity = document.getElementById('navbarCity');
    const authContainer = document.getElementById('authContainer');
    const navbarMovieTitleScrolled = document.getElementById('navbarMovieTitleScrolled');
    const navbarBookBtnScrolled = document.getElementById('navbarBookBtnScrolled');
    
    window.addEventListener('scroll', () => {
        const scrollY = window.scrollY;
        
        if (scrollY > bannerHeight - 100) {
            // SCROLLED STATE: Hide everything, show only Movie Title + Book Now
            if (navbarLogo) navbarLogo.style.display = 'none';
            if (navbarMenu) navbarMenu.style.display = 'none';
            if (navbarCity) navbarCity.style.display = 'none';
            if (authContainer) authContainer.style.display = 'none';
            if (navbarMovieTitleScrolled) navbarMovieTitleScrolled.style.display = 'block';
            if (navbarBookBtnScrolled) navbarBookBtnScrolled.style.display = 'flex';
        } else {
            // DEFAULT STATE: Show normal navbar, hide scrolled elements
            if (navbarLogo) navbarLogo.style.display = 'block';
            if (navbarMenu) navbarMenu.style.display = 'flex';
            if (navbarCity) navbarCity.style.display = 'flex';
            if (authContainer) authContainer.style.display = 'flex';
            if (navbarMovieTitleScrolled) navbarMovieTitleScrolled.style.display = 'none';
            if (navbarBookBtnScrolled) navbarBookBtnScrolled.style.display = 'none';
        }
    });
}

// ==========================================
// BOOKMARK FEATURE
// ==========================================
async function checkSavedStatus() {
    const user = JSON.parse(localStorage.getItem('bookoraUser') || 'null');
    if (!user || !currentMovie) return;
    
    try {
        // The server identifies the user from the session cookie — no user id in the URL.
        const response = await (window.BookoraAPI 
            ? BookoraAPI.fetch(`/api/check-saved/${currentMovie.id}`) 
            : fetch(`${API_URL}/api/check-saved/${currentMovie.id}`, { credentials: 'include' }));
        
        // Check if response is ok
        if (!response.ok) {
            console.warn('Saved status check failed, continuing without it');
            return;
        }
        
        const data = await response.json();
        
        if (data.success) {
            isMovieSaved = data.is_saved;
            
            if (isMovieSaved) {
                const bookmarkBtn = document.getElementById('bookmarkBtn');
                if (bookmarkBtn) {
                    bookmarkBtn.classList.add('saved');
                    const heartIcon = bookmarkBtn.querySelector('i');
                    if (heartIcon) heartIcon.className = 'fas fa-heart';
                }
            }
        }
    } catch (error) {
        // Silently fail - don't break page load
        console.warn('Could not check saved status (non-critical):', error);
    }
}

async function toggleBookmark() {
    const user = JSON.parse(localStorage.getItem('bookoraUser') || 'null');
    
    if (!user) {
        // User not logged in - open sign-in modal
        if (typeof openSignInModal === 'function') {
            openSignInModal('save');
        } else {
            alert('Please sign in to save movies to your watchlist');
        }
        return;
    }
    
    const bookmarkBtn = document.getElementById('bookmarkBtn');
    const heartIcon = bookmarkBtn?.querySelector('i');
    
    // Optimistic UI update
    isMovieSaved = !isMovieSaved;
    if (bookmarkBtn) bookmarkBtn.classList.toggle('saved', isMovieSaved);
    
    if (heartIcon) {
        heartIcon.className = isMovieSaved ? 'fas fa-heart' : 'far fa-heart';
    }
    
    try {
        const endpoint = isMovieSaved ? '/api/save-movie' : '/api/unsave-movie';
        const response = await (window.BookoraAPI 
            ? BookoraAPI.fetch(endpoint, {
                method: 'POST',
                body: JSON.stringify({ movie_id: currentMovie.id })
            })
            : fetch(`${API_URL}${endpoint}`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ movie_id: currentMovie.id })
            }));
        
        const data = await response.json();
        
        if (data.success) {
            showToast(isMovieSaved ? 'Saved to your watchlist' : 'Removed from watchlist');
        } else {
            // Revert on error
            isMovieSaved = !isMovieSaved;
            if (bookmarkBtn) bookmarkBtn.classList.toggle('saved', isMovieSaved);
            if (heartIcon) heartIcon.className = isMovieSaved ? 'fas fa-heart' : 'far fa-heart';
            showToast('Error saving movie');
        }
    } catch (error) {
        console.error('Error toggling bookmark:', error);
        // Revert on error
        isMovieSaved = !isMovieSaved;
        if (bookmarkBtn) bookmarkBtn.classList.toggle('saved', isMovieSaved);
        if (heartIcon) heartIcon.className = isMovieSaved ? 'fas fa-heart' : 'far fa-heart';
        showToast('Error saving movie');
    }
}

// ==========================================
// SHARE FEATURE - REMOVED
// ==========================================
// Share button has been removed from UI

// ==========================================
// TOAST NOTIFICATION
// ==========================================
function showToast(message) {
    const existingToast = document.querySelector('.toast-notification');
    if (existingToast) existingToast.remove();
    
    const toast = document.createElement('div');
    toast.className = 'toast-notification';
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        bottom: 30px;
        left: 50%;
        transform: translateX(-50%);
        background: rgba(212, 165, 154, 0.95);
        color: white;
        padding: 12px 24px;
        border-radius: 25px;
        font-weight: 600;
        z-index: 10000;
        animation: slideUp 0.3s ease-out;
        box-shadow: 0 4px 20px rgba(212, 165, 154, 0.4);
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideDown 0.3s ease-out';
        setTimeout(() => toast.remove(), 300);
    }, 2000);
}

// ==========================================
// TRAILER MODAL & PLAYER
// ==========================================

// Extract YouTube video ID from any standard YouTube URL
function extractYouTubeVideoId(url) {
    if (!url || typeof url !== 'string') return null;
    const cleanUrl = url.trim();
    const regExp = /(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=|shorts\/))([\w-]{11})/i;
    const match = cleanUrl.match(regExp);
    return (match && match[1]) ? match[1] : null;
}

// Open trailer modal with in-app embed player or graceful fallback
function openTrailer() {
    if (!currentMovie || !currentMovie.trailer_url) {
        showToast('Trailer is currently unavailable for this movie');
        return;
    }
    
    const trailerUrl = (currentMovie.trailer_url || '').trim();
    const videoId = extractYouTubeVideoId(trailerUrl);
    
    if (!videoId) {
        if (/^https?:\/\//i.test(trailerUrl)) {
            window.open(trailerUrl, '_blank', 'noopener,noreferrer');
            return;
        }
        showToast('Trailer is currently unavailable for this movie');
        return;
    }
    
    const modal = document.getElementById('trailerModal');
    const iframe = document.getElementById('trailerIframe');
    const titleEl = document.getElementById('trailerMovieTitle');
    const extLink = document.getElementById('trailerExternalLink');
    
    if (modal && iframe) {
        // Mobile-friendly embed URL:
        // playsinline=1 allows iOS WebKit to play video inline
        // autoplay=1 starts playback on user intent
        // rel=0 restricts related videos to current channel
        const embedUrl = `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&playsinline=1&rel=0&modestbranding=1`;
        iframe.src = embedUrl;
        
        if (titleEl) {
            titleEl.textContent = `${currentMovie.title || 'Movie'} — Official Trailer`;
        }
        if (extLink) {
            extLink.href = `https://www.youtube.com/watch?v=${videoId}`;
        }
        
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    } else {
        // Fallback if modal DOM is not present
        window.open(`https://www.youtube.com/watch?v=${videoId}`, '_blank', 'noopener,noreferrer');
    }
}

// Close trailer modal and terminate audio/video playback
function closeTrailerModal(event) {
    if (event && event.preventDefault) {
        event.preventDefault();
    }
    const modal = document.getElementById('trailerModal');
    const iframe = document.getElementById('trailerIframe');
    
    if (iframe) {
        iframe.src = '';
    }
    if (modal) {
        modal.classList.remove('active');
    }
    document.body.style.overflow = 'auto';
}

// Initialize trailer buttons with touch & click listeners
function initTrailerButtons() {
    const trailerBtn = document.getElementById('trailerBtn');
    const trailerBadge = document.getElementById('trailerBadge');
    
    if (trailerBtn) {
        trailerBtn.addEventListener('click', (e) => {
            e.preventDefault();
            openTrailer();
        });
    }
    if (trailerBadge) {
        trailerBadge.addEventListener('click', (e) => {
            e.preventDefault();
            openTrailer();
        });
    }
}

// Handle Book Now - NO LOGIN REQUIRED (BookMyShow-style flow)
function handleBookNow() {
    // Navigate directly to shows page - login required only at payment
    if (currentMovie && currentMovie.slug) {
        const targetSlug = currentMovie.slug;
        const targetUrl = (typeof BookoraRouter !== 'undefined' && BookoraRouter.buildShowsUrl) 
            ? BookoraRouter.buildShowsUrl(targetSlug) 
            : `/shows/${targetSlug}`;
        console.log('Navigating to shows page:', targetUrl);
        window.location.href = targetUrl;
    } else if (currentMovie && currentMovie.id) {
        const targetId = currentMovie.id;
        const targetUrl = (typeof BookoraRouter !== 'undefined' && BookoraRouter.buildShowsUrl) 
            ? BookoraRouter.buildShowsUrl(targetId) 
            : `/shows/${targetId}`;
        console.log('Navigating to shows page with ID:', targetUrl);
        window.location.href = targetUrl;
    } else {
        console.error('No movie data available:', currentMovie);
        alert('Movie information not available');
    }
}
