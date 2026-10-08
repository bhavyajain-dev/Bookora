/**
 * My Bookings Page - View and Cancel Bookings
 */

let currentUser = null;
let bookings = [];

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    loadBookings();
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
    
    // CRITICAL FIX: Hide Sign-In button and show profile section
    const authButtons = document.querySelector('.auth-buttons');
    const profileSection = document.querySelector('.profile-section');
    
    if (authButtons) {
        authButtons.style.display = 'none';
    }
    if (profileSection) {
        profileSection.style.display = 'block';
    }
    
    updateNavbar();
}

// Update navbar with user info
function updateNavbar() {
    if (currentUser) {
        // Update profile display in navbar dropdown
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

// Load user bookings
async function loadBookings() {
    if (!currentUser) return;
    
    // Show loading state
    document.getElementById('loadingState').style.display = 'flex';
    document.getElementById('noBookingsState').style.display = 'none';
    document.getElementById('bookingsList').style.display = 'none';
    
    try {
        // The server identifies the user from the session cookie — no user_id sent.
        const response = await BookoraAPI.fetch('/api/bookings');
        const data = await response.json();
        
        if (data.success) {
            bookings = data.bookings;
            
            if (bookings.length === 0) {
                // Show no bookings state
                document.getElementById('loadingState').style.display = 'none';
                document.getElementById('noBookingsState').style.display = 'flex';
            } else {
                // Display bookings
                displayBookings();
            }
        } else {
            console.error('Failed to load bookings:', data.message);
            document.getElementById('loadingState').style.display = 'none';
            document.getElementById('noBookingsState').style.display = 'flex';
        }
    } catch (error) {
        console.error('Error loading bookings:', error);
        document.getElementById('loadingState').style.display = 'none';
        document.getElementById('noBookingsState').style.display = 'flex';
    }
}

// Display bookings
function displayBookings() {
    const container = document.getElementById('bookingsList');
    
    container.innerHTML = bookings.map(booking => createBookingCard(booking)).join('');
    
    // Hide loading, show list
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('bookingsList').style.display = 'grid';
}

// Create booking card HTML
function createBookingCard(booking) {
    const showDateTime = new Date(`${booking.show_date} ${booking.show_time}`);
    const isPastShow = showDateTime < new Date();
    const isConfirmed = booking.status === 'CONFIRMED';
    const canCancel = isConfirmed && !isPastShow;
    
    // Format date and time
    const formattedDate = formatDate(booking.show_date);
    const formattedTime = formatTime(booking.show_time);
    
    // Format seat numbers - use seat_details if available, otherwise fallback to seat_ids
    let seatCount = 0;
    let seatLabels = '';
    
    if (booking.seat_details && booking.seat_details.length > 0) {
        seatCount = booking.seat_details.length;
        seatLabels = booking.seat_details.map(s => s.seat_label).join(', ');
    } else {
        seatCount = booking.seat_ids ? booking.seat_ids.length : 0;
        seatLabels = booking.seat_ids ? booking.seat_ids.map(id => `Seat ${id}`).join(', ') : '';
    }
    
    // Get poster URL or placeholder
    const posterRaw = booking.poster_url || '/posters/placeholder.svg';
    const posterUrl = (typeof BookoraAPI !== 'undefined' && BookoraAPI.resolveImageUrl) 
        ? BookoraAPI.resolveImageUrl(posterRaw) 
        : posterRaw;
    
    return `
        <div class="booking-card ${booking.status.toLowerCase()}" onclick="showBookingDetails(${booking.booking_id})">
            <div class="booking-card-header">
                <span class="booking-status status-${booking.status.toLowerCase()}">
                    ${booking.status}
                </span>
                <span class="booking-date">
                    <i class="fas fa-calendar-alt"></i>
                    Booked on ${formatBookingDate(booking.booking_date)}
                </span>
            </div>
            
            <div class="booking-card-content">
                <div class="booking-poster">
                    <img src="${posterUrl}" alt="${booking.movie_title}" onerror="handleImageError(this, 'poster')">
                </div>
                
                <div class="booking-details">
                    <h3 class="movie-title">${booking.movie_title}</h3>
                    
                    <div class="booking-info">
                        <div class="info-item">
                            <i class="fas fa-building"></i>
                            <span>${booking.theatre_name}</span>
                        </div>
                        
                        <div class="info-item">
                            <i class="fas fa-calendar"></i>
                            <span>${formattedDate} at ${formattedTime}</span>
                        </div>
                        
                        <div class="info-item">
                            <i class="fas fa-couch"></i>
                            <span>${seatCount} Seat${seatCount > 1 ? 's' : ''}</span>
                        </div>
                    </div>
                    
                    <div class="booking-footer">
                        <div class="booking-price">
                            <span class="price-label">Total Amount</span>
                            <span class="price-value">₹${parseFloat(booking.total_price).toFixed(2)}</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// Cancel booking
async function cancelBooking(bookingId) {
    // Show cancel confirmation modal
    window.pendingCancelBookingId = bookingId;
    const modal = document.getElementById('cancelConfirmModal');
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
    
    // Prevent closing by clicking outside or Esc
    modal.onclick = (e) => {
        if (e.target === modal) {
            e.stopPropagation();
        }
    };
}

// Close cancel confirmation modal
function closeCancelConfirmModal() {
    const modal = document.getElementById('cancelConfirmModal');
    modal.classList.remove('active');
    document.body.style.overflow = 'auto';
    window.pendingCancelBookingId = null;
}

// Confirm cancel booking
async function confirmCancelBooking() {
    const bookingId = window.pendingCancelBookingId;
    if (!bookingId) return;
    
    const button = document.getElementById('confirmCancelBtn');
    const originalText = button.textContent;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Cancelling...';
    button.disabled = true;
    
    try {
        const response = await BookoraAPI.fetch('/api/cancel-booking', {
            method: 'POST',
            body: JSON.stringify({
                booking_id: bookingId
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Close modal
            closeCancelConfirmModal();
            
            // Reload bookings to reflect the change
            await loadBookings();
            
            // Show success in content area (optional)
            showSuccessToast('Booking cancelled successfully!');
        } else {
            alert(data.message || 'Failed to cancel booking. Please try again.');
            button.textContent = originalText;
            button.disabled = false;
        }
    } catch (error) {
        console.error('Error cancelling booking:', error);
        alert('An error occurred. Please try again.');
        button.textContent = originalText;
        button.disabled = false;
    }
}

// Show booking details modal
function showBookingDetails(bookingId) {
    const booking = bookings.find(b => b.booking_id === bookingId);
    if (!booking) return;
    
    const modal = document.getElementById('bookingDetailsModal');
    const content = document.getElementById('bookingDetailsContent');
    
    // Check if can cancel
    const showDateTime = new Date(`${booking.show_date} ${booking.show_time}`);
    const isPastShow = showDateTime < new Date();
    const isConfirmed = booking.status === 'CONFIRMED';
    const canCancel = isConfirmed && !isPastShow;
    
    // Format seat details with pricing info
    const seatCount = booking.seat_ids ? booking.seat_ids.length : 0;
    let seatDetailsHTML = '';
    
    // Check if we have individual seat details with pricing
    if (booking.seat_details && Array.isArray(booking.seat_details)) {
        seatDetailsHTML = booking.seat_details.map(seat => {
            const seatType = seat.seat_type ? ` (${seat.seat_type})` : '';
            return `<div class="seat-detail-row">
                <span>${seat.seat_label}${seatType}</span>
                <span>₹${parseFloat(seat.price).toFixed(2)}</span>
            </div>`;
        }).join('');
    } else {
        // Fallback: show seat IDs with average price
        const seatLabels = booking.seat_ids ? booking.seat_ids.map(id => `Seat ${id}`).join(', ') : 'N/A';
        const avgPrice = seatCount > 0 ? (booking.total_price / seatCount).toFixed(2) : '0.00';
        seatDetailsHTML = `<div class="seat-detail-row">
            <span>${seatCount} seat${seatCount > 1 ? 's' : ''}: ${seatLabels}</span>
            <span>~₹${avgPrice} each</span>
        </div>`;
    }
    
    // Build details content
    content.innerHTML = `
        <div class="booking-detail-item">
            <span class="detail-label">Movie</span>
            <span class="detail-value">${booking.movie_title}</span>
        </div>
        <div class="booking-detail-item">
            <span class="detail-label">Venue</span>
            <span class="detail-value">${booking.theatre_name}<br><small>${booking.theatre_address || ''}</small></span>
        </div>
        <div class="booking-detail-item">
            <span class="detail-label">Show Date & Time</span>
            <span class="detail-value">${formatDate(booking.show_date)} at ${formatTime(booking.show_time)}</span>
        </div>
        <div class="booking-detail-item seats-section">
            <span class="detail-label">Seats & Pricing</span>
            <div class="seat-details-list">
                ${seatDetailsHTML}
            </div>
        </div>
        <div class="booking-detail-item">
            <span class="detail-label">Booking Status</span>
            <span class="detail-value status-${booking.status.toLowerCase()}">${booking.status}</span>
        </div>
        <div class="booking-detail-item total-item">
            <span class="detail-label">Total Amount Paid</span>
            <span class="detail-value price">₹${parseFloat(booking.total_price).toFixed(2)}</span>
        </div>
        
        ${canCancel ? `
            <div class="booking-actions-in-modal">
                <button class="btn-cancel-in-modal" onclick="event.stopPropagation(); closeBookingDetailsModal(); cancelBooking(${booking.booking_id})">
                    <i class="fas fa-times-circle"></i> Cancel Booking
                </button>
            </div>
        ` : ''}
    `;
    
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

// Close booking details modal
function closeBookingDetailsModal() {
    const modal = document.getElementById('bookingDetailsModal');
    modal.classList.remove('active');
    document.body.style.overflow = 'auto';
}

// Simple success toast (optional)
function showSuccessToast(message) {
    // Create a simple toast notification
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 100px;
        right: 20px;
        background: #4CAF50;
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        z-index: 9999;
        animation: slideIn 0.3s ease;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Format date
function formatDate(dateStr) {
    const date = new Date(dateStr);
    const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    
    return `${days[date.getDay()]}, ${months[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
}

// Format time
function formatTime(timeStr) {
    // timeStr is HH:MM:SS format
    const [hours, minutes] = timeStr.split(':');
    const hour = parseInt(hours);
    const ampm = hour >= 12 ? 'PM' : 'AM';
    const hour12 = hour % 12 || 12;
    
    return `${hour12}:${minutes} ${ampm}`;
}

// Format booking date
function formatBookingDate(dateStr) {
    const date = new Date(dateStr);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    
    return `${months[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
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
