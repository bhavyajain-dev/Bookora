/**
 * Saved Movies Page - Display user's saved/favorite movies
 */

let currentUser = null;
let savedMovies = [];

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    loadSavedMovies();
});

// Close dropdown on page show (handles back button navigation from cache)
window.addEventListener('pageshow', () => {
    checkAuth();
    const dropdown = document.getElementById('profileDropdown');
    if (dropdown) {
        dropdown.classList.remove('active');
    }
});

// Check if user is logged in
function checkAuth() {
    const user = localStorage.getItem('bookoraUser');
    
    if (!user) {
        // Redirect to home immediately if not logged in
        BookoraRouter.replace('/');
        return;
    }
    
    currentUser = JSON.parse(user);
    updateNavbar();
}

// Update navbar with user info
function updateNavbar() {
    if (currentUser) {
        const profileNameEl = document.getElementById('profileDisplayName');
        const profileContactEl = document.getElementById('profileDisplayContact');
        
        if (profileNameEl) {
            profileNameEl.textContent = currentUser.name || 'User';
        }
        if (profileContactEl) {
            profileContactEl.textContent = currentUser.email || currentUser.phone || '';
        }
    }
}

// Load saved movies (assuming data exists in localStorage or API)
async function loadSavedMovies() {
    if (!currentUser) return;
    
    console.log('Loading saved movies for user:', currentUser.id);
    
    // Show loading state
    document.getElementById('loadingState').style.display = 'flex';
    document.getElementById('noSavedMoviesState').style.display = 'none';
    document.getElementById('savedMoviesList').style.display = 'none';
    
    try {
        // Try to fetch from API first
        // The server identifies the user from the session cookie — no user id in the URL.
        const response = await BookoraAPI.fetch('/api/saved-movies');
        const data = await response.json();
        
        console.log('API Response:', data);
        
        if (data.success && data.movies) {
            savedMovies = data.movies;
            console.log('Saved movies from API:', savedMovies);
        } else {
            // Fallback: Get from localStorage
            const localSaved = JSON.parse(localStorage.getItem('savedMovies_' + currentUser.id) || '[]');
            savedMovies = localSaved;
            console.log('Saved movies from localStorage:', savedMovies);
        }
        
        if (savedMovies.length === 0) {
            // Show no saved movies state
            document.getElementById('loadingState').style.display = 'none';
            document.getElementById('noSavedMoviesState').style.display = 'flex';
            console.log('No saved movies found');
        } else {
            // Display saved movies
            console.log('Displaying', savedMovies.length, 'saved movies');
            displaySavedMovies();
        }
    } catch (error) {
        console.error('Error loading saved movies:', error);
        // Fallback to localStorage
        const localSaved = JSON.parse(localStorage.getItem('savedMovies_' + currentUser.id) || '[]');
        savedMovies = localSaved;
        
        if (savedMovies.length === 0) {
            document.getElementById('loadingState').style.display = 'none';
            document.getElementById('noSavedMoviesState').style.display = 'flex';
        } else {
            displaySavedMovies();
        }
    }
}

// Display saved movies
function displaySavedMovies() {
    const container = document.getElementById('savedMoviesList');
    
    container.innerHTML = savedMovies.map(movie => createMovieCard(movie)).join('');
    
    // Hide loading, show grid
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('savedMoviesList').style.display = 'grid';
}

// Create movie card HTML
function createMovieCard(movie) {
    // Handle poster URL
    const posterRaw = movie.poster_url || '/posters/placeholder.svg';
    const posterUrl = (typeof BookoraAPI !== 'undefined' && BookoraAPI.resolveImageUrl) 
        ? BookoraAPI.resolveImageUrl(posterRaw) 
        : posterRaw;
    
    return `
        <div class="movie-card" onclick="navigateToMovieDetails('${movie.slug}')">
            <div class="movie-poster" style="background: #2a2520 url('${posterUrl}') center/cover;">
                <div class="rating-badge">
                    <i class="fas fa-star"></i> ${movie.certification || 'U/A'}
                </div>
            </div>
            <div class="movie-info">
                <div class="movie-title">${movie.title}</div>
                <div class="movie-language">${movie.language || 'Hindi'}</div>
            </div>
        </div>
    `;
}

// Navigate to movie details
function navigateToMovieDetails(slug) {
    window.location.href = BookoraRouter.buildMovieUrl(slug);
}

// Toggle profile dropdown
function toggleProfileDropdown() {
    const dropdown = document.getElementById('profileDropdown');
    dropdown.classList.toggle('active');
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    const profileContainer = document.querySelector('.profile-container');
    const dropdown = document.getElementById('profileDropdown');
    
    if (profileContainer && !profileContainer.contains(e.target)) {
        dropdown.classList.remove('active');
    }
});

