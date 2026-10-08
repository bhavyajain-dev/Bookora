// ==========================================
// SIGN-IN MODAL FUNCTIONALITY
// ==========================================

console.log('signin-modal.js loading...');

// ==========================================
// AUTH STATE MANAGEMENT
// ==========================================

// Check if user is logged in
function isUserLoggedIn() {
    return localStorage.getItem('bookoraUser') !== null;
}

// Get current user data
function getCurrentUser() {
    const userData = localStorage.getItem('bookoraUser');
    return userData ? JSON.parse(userData) : null;
}

// Save user data and mark as logged in
function loginUser(userData) {
    localStorage.setItem('bookoraUser', JSON.stringify(userData));
    updateAuthUI();
    
    // Check for pending booking (seats page)
    const pendingBooking = sessionStorage.getItem('bookora_pending_booking');
    if (pendingBooking) {
        // Clear the pending booking flag
        sessionStorage.removeItem('bookora_pending_booking');
        
        // Trigger proceed to payment automatically after modal closes
        // The seat-selection page will continue the flow
        setTimeout(() => {
            if (typeof proceedToPayment === 'function') {
                proceedToPayment();
            }
        }, 100);
    }
}

// Logout user
function logoutUser() {
    // Tell the server to clear the session cookie (server-side sign-out).
    // Fire-and-forget: the local UI clears regardless of the network result.
    BookoraAPI.fetch('/api/logout', {
        method: 'POST'
    }).catch(() => { /* ignore network errors during logout */ });

    localStorage.removeItem('bookoraUser');
    updateAuthUI();
}

// Update UI based on auth state
function updateAuthUI() {
    // Every lookup here is guarded because this function runs on all seven pages,
    // and #loggedOutState / #loggedInState only exist on the four public ones
    // (home, movie details, shows, seat selection). my-bookings, profile and
    // saved-movies are logged-in-only pages: their navbar renders the profile
    // section unconditionally and has no logged-out block at all, so both lookups
    // return null there.
    //
    // Dereferencing .style on null threw a TypeError on those three pages, and
    // since updateAuthUI() is the first statement of the DOMContentLoaded handler
    // the throw aborted every statement after it - the modal was never reset to
    // its default screen, a leftover sessionStorage tempEmail was never cleared,
    // and the click-outside guard that keeps a mandatory profile-completion modal
    // from being dismissed was never attached. It also meant the two lines below
    // never ran, so the profile dropdown on those pages always showed the
    // placeholder "User" with a blank contact instead of the real values.
    const loggedOutState = document.getElementById('loggedOutState');
    const loggedInState = document.getElementById('loggedInState');
    const displayName = document.getElementById('profileDisplayName');
    const displayContact = document.getElementById('profileDisplayContact');
    const user = getCurrentUser();

    if (user) {
        // User is logged in - show profile avatar
        if (loggedOutState) loggedOutState.style.display = 'none';
        if (loggedInState) loggedInState.style.display = 'flex';

        // Update profile info in dropdown
        if (displayName) displayName.textContent = user.name || 'User';
        if (displayContact) displayContact.textContent = user.email || user.mobile || '';
    } else {
        // User is logged out - show login button
        if (loggedOutState) loggedOutState.style.display = 'flex';
        if (loggedInState) loggedInState.style.display = 'none';
    }
}

// Toggle profile dropdown
function toggleProfileDropdown() {
    // Guarded for the same reason as updateAuthUI: handleLogout() calls this
    // before showing the logout toast, so a null here would swallow the toast.
    const dropdown = document.getElementById('profileDropdown');
    if (dropdown) dropdown.classList.toggle('active');
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    const profileContainer = document.querySelector('.profile-container');
    const dropdown = document.getElementById('profileDropdown');
    
    if (dropdown && profileContainer && !profileContainer.contains(e.target)) {
        dropdown.classList.remove('active');
    }
});

// Navigate to profile page
function navigateToProfile(e) {
    if (e && typeof e.preventDefault === 'function') e.preventDefault();
    if (typeof closeMobileDrawer === 'function') closeMobileDrawer();
    window.location.href = BookoraRouter.buildPageUrl('profile');
}

// Navigate to bookings page
function navigateToBookings(e) {
    if (e && typeof e.preventDefault === 'function') e.preventDefault();
    if (typeof closeMobileDrawer === 'function') closeMobileDrawer();
    window.location.href = BookoraRouter.buildPageUrl('my-bookings');
}

// Navigate to saved movies page
function navigateToSavedMovies(e) {
    if (e && typeof e.preventDefault === 'function') e.preventDefault();
    if (typeof closeMobileDrawer === 'function') closeMobileDrawer();
    window.location.href = BookoraRouter.buildPageUrl('saved-movies');
}

// Reusable image error fallback handler for all pages
function handleImageError(img, type = 'poster') {
    if (!img) return;
    img.onerror = null; // Prevent recursion
    img.src = type === 'banner' ? '/banners/placeholder.svg' : '/posters/placeholder.svg';
    img.classList.add('bookora-placeholder-image');
}

// ==========================================
// MOBILE DRAWER & NAVBAR CONTROLLER
// ==========================================

// Strict Deterministic State Machine
// States: 'CLOSED', 'OPENING', 'OPEN', 'CLOSING'
let mobileDrawerState = 'CLOSED';
let lastMobileDrawerTransition = 0;
let mobileDrawerCloseTimeout = null;

function isMobileDrawerOpen() {
    return mobileDrawerState === 'OPEN' || mobileDrawerState === 'OPENING';
}

function isMobileDrawerTransitioning() {
    return mobileDrawerState === 'OPENING' || mobileDrawerState === 'CLOSING';
}

function closeMobileDrawer(immediate = false) {
    if (mobileDrawerState === 'CLOSED' || mobileDrawerState === 'CLOSING') return;

    mobileDrawerState = 'CLOSING';
    lastMobileDrawerTransition = Date.now();

    const navbar = document.querySelector('.navbar-bookora');
    const navbarContent = document.getElementById('navbarContent');
    const toggler = document.querySelector('.navbar-toggler');
    const backdrop = document.getElementById('mobileNavBackdrop');

    if (toggler) {
        toggler.setAttribute('aria-expanded', 'false');
        toggler.setAttribute('aria-label', 'Open navigation');
    }
    if (navbar) {
        navbar.classList.remove('menu-open');
    }
    if (backdrop) {
        backdrop.classList.remove('active');
    }
    document.body.style.overflow = '';
    document.body.classList.remove('mobile-menu-open');

    const finishClosing = () => {
        if (navbarContent) {
            navbarContent.classList.remove('show');
            navbarContent.classList.remove('closing');
        }
        mobileDrawerState = 'CLOSED';
        lastMobileDrawerTransition = Date.now();
        mobileDrawerCloseTimeout = null;
    };

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (immediate || prefersReducedMotion || !navbarContent) {
        finishClosing();
    } else {
        navbarContent.classList.add('closing');
        mobileDrawerCloseTimeout = setTimeout(finishClosing, 200);
    }
}

function openMobileDrawer() {
    if (mobileDrawerState === 'OPEN' || mobileDrawerState === 'OPENING') return;
    const now = Date.now();
    // Guard against immediate re-opening within 300ms cooldown
    if (now - lastMobileDrawerTransition < 300) return;

    if (mobileDrawerCloseTimeout) {
        clearTimeout(mobileDrawerCloseTimeout);
        mobileDrawerCloseTimeout = null;
    }

    mobileDrawerState = 'OPENING';
    lastMobileDrawerTransition = now;

    const navbar = document.querySelector('.navbar-bookora');
    const navbarContent = document.getElementById('navbarContent');
    const toggler = document.querySelector('.navbar-toggler');
    let backdrop = document.getElementById('mobileNavBackdrop');

    if (!backdrop) {
        backdrop = document.createElement('div');
        backdrop.id = 'mobileNavBackdrop';
        backdrop.className = 'mobile-nav-backdrop';
        document.body.appendChild(backdrop);
        backdrop.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            closeMobileDrawer();
        });
    }

    if (navbarContent) {
        navbarContent.classList.remove('closing');
        navbarContent.classList.add('show');
    }
    if (navbar) {
        navbar.classList.add('menu-open');
        navbar.classList.remove('navbar-hidden');
    }
    if (toggler) {
        toggler.setAttribute('aria-expanded', 'true');
        toggler.setAttribute('aria-label', 'Close navigation');
    }
    backdrop.classList.add('active');
    document.body.style.overflow = 'hidden';
    document.body.classList.add('mobile-menu-open');

    setTimeout(() => {
        if (mobileDrawerState === 'OPENING') {
            mobileDrawerState = 'OPEN';
        }
    }, 220);
}

function toggleMobileDrawer() {
    if (isMobileDrawerOpen() || mobileDrawerState === 'CLOSING') {
        closeMobileDrawer();
    } else {
        openMobileDrawer();
    }
}

function initMobileNavbar() {
    const navbar = document.querySelector('.navbar-bookora');
    if (!navbar) return;

    // Mobile scroll-hide with hysteresis & top threshold
    let lastScrollY = window.scrollY || window.pageYOffset || 0;
    let ticking = false;
    const SCROLL_THRESHOLD = 10;
    const TOP_THRESHOLD = 60;

    function handleScroll() {
        if (!ticking) {
            window.requestAnimationFrame(() => {
                const currentScrollY = window.scrollY || window.pageYOffset || 0;
                const isMenuOpen = isMobileDrawerOpen() ||
                                   isMobileDrawerTransitioning() ||
                                   document.body.classList.contains('mobile-menu-open');

                // On desktop, never hide navbar
                if (window.innerWidth > 991.98) {
                    navbar.classList.remove('navbar-hidden');
                    lastScrollY = currentScrollY;
                    ticking = false;
                    return;
                }

                // If mobile drawer is open or transitioning, do not hide navbar
                if (isMenuOpen) {
                    navbar.classList.remove('navbar-hidden');
                    lastScrollY = currentScrollY;
                    ticking = false;
                    return;
                }

                // Within top zone: always reveal
                if (currentScrollY <= TOP_THRESHOLD) {
                    navbar.classList.remove('navbar-hidden');
                } else {
                    const diff = currentScrollY - lastScrollY;
                    if (diff > SCROLL_THRESHOLD) {
                        // Scrolling DOWN: hide
                        navbar.classList.add('navbar-hidden');
                    } else if (diff < -SCROLL_THRESHOLD) {
                        // Scrolling UP: reveal
                        navbar.classList.remove('navbar-hidden');
                    }
                }

                lastScrollY = Math.max(0, currentScrollY);
                ticking = false;
            });
            ticking = true;
        }
    }

    window.addEventListener('scroll', handleScroll, { passive: true });

    // Handle toggler button clicks on mobile
    const togglers = document.querySelectorAll('.navbar-toggler');
    togglers.forEach(btn => {
        btn.addEventListener('click', (e) => {
            if (window.innerWidth > 991.98) return;
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();

            const now = Date.now();
            // Discard duplicate events / synthetic clicks during transition or cooldown
            if (isMobileDrawerTransitioning() || now - lastMobileDrawerTransition < 300) {
                return;
            }

            // If menu is open OR close X icon was clicked: dedicated CLOSE operation
            if (isMobileDrawerOpen() || e.target.closest('.navbar-toggler-close')) {
                closeMobileDrawer();
            } else {
                openMobileDrawer();
            }
        });
    });

    // Dedicated listener for the close X icon
    const closeIcons = document.querySelectorAll('.navbar-toggler-close');
    closeIcons.forEach(icon => {
        icon.addEventListener('click', (e) => {
            if (window.innerWidth > 991.98) return;
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();

            const now = Date.now();
            if (isMobileDrawerTransitioning() || now - lastMobileDrawerTransition < 300) {
                return;
            }
            closeMobileDrawer();
        });
    });

    // Close drawer when clicking nav links or buttons inside the drawer on mobile
    const drawerLinks = document.querySelectorAll('#navbarContent a, #navbarContent button');
    drawerLinks.forEach(item => {
        item.addEventListener('click', () => {
            if (window.innerWidth <= 991.98) {
                closeMobileDrawer(true);
            }
        });
    });

    // Close drawer with Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isMobileDrawerOpen()) {
            closeMobileDrawer();
        }
    });

    // Handle resize: restore desktop state if viewport grows
    window.addEventListener('resize', () => {
        if (window.innerWidth > 991.98) {
            closeMobileDrawer(true);
            navbar.classList.remove('navbar-hidden');
        }
    });
}

// Centralized, idempotent logout handler
function handleLogout(e) {
    if (e && typeof e.preventDefault === 'function') {
        e.preventDefault();
    }
    
    // Check if user is currently authenticated
    const user = getCurrentUser();
    if (!user) {
        // Already logged out: close dropdown and redirect if on a protected page
        const dropdown = document.getElementById('profileDropdown') || document.querySelector('.profile-dropdown');
        if (dropdown) dropdown.classList.remove('active');
        if (typeof closeMobileDrawer === 'function') closeMobileDrawer();
        if (window.location.pathname !== '/' && window.location.pathname !== '/index.html') {
            window.location.href = '/';
        }
        return;
    }
    
    const userName = user.name || 'User';
    
    // Clear user data from localStorage & server session
    logoutUser();
    
    // Clear temporary data
    sessionStorage.removeItem('tempEmail');
    sessionStorage.removeItem('tempMobile');
    sessionStorage.removeItem('bookora_pending_booking');
    
    // Clear OTP timer if running
    if (typeof otpTimer !== 'undefined' && otpTimer) {
        clearInterval(otpTimer);
        otpTimer = null;
    }
    
    // Close dropdown & mobile drawer
    const dropdown = document.getElementById('profileDropdown') || document.querySelector('.profile-dropdown');
    if (dropdown) {
        dropdown.classList.remove('active');
    }
    if (typeof closeMobileDrawer === 'function') {
        closeMobileDrawer();
    }
    
    // Always redirect to homepage
    if (window.location.pathname === '/' || window.location.pathname === '/index.html') {
        // Already on homepage: show toast directly and update navbar
        sessionStorage.removeItem('bookora_logout_message');
        showLogoutConfirmation(userName);
        updateAuthUI();
    } else {
        // Store message so homepage displays the toast once upon arrival
        sessionStorage.setItem('bookora_logout_message', userName);
        window.location.href = '/';
    }
    
    console.log('User logged out successfully - all state cleared');
}

// Initialize auth state on page load
document.addEventListener('DOMContentLoaded', () => {
    // Update auth UI based on localStorage
    updateAuthUI();
    initMobileNavbar();
    
    // Ensure modal is closed and reset on page load
    const modal = document.getElementById('signinModal');
    if (modal) {
        modal.classList.remove('active');
        document.body.style.overflow = ''; // Restore scroll
        
        // Clear any leftover temporary state
        sessionStorage.removeItem('tempEmail');
        
        // Reset modal to default state
        showAuthChoiceScreen();
        
        // Add click-outside prevention for profile completion
        modal.addEventListener('click', (e) => {
            // If clicking on the overlay itself (not the modal content)
            if (e.target === modal) {
                // Check if profile completion is active
                const profileCompletionForm = document.querySelector('.profile-completion-form');
                if (profileCompletionForm) {
                    // Profile completion is mandatory - prevent closing
                    showInlineError('Please enter your details to continue');
                    return;
                }
                // Otherwise, allow normal close behavior
                closeSignInModal();
            }
        });
        
        // Prevent ESC key from closing modal during profile completion
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const profileCompletionForm = document.querySelector('.profile-completion-form');
                if (profileCompletionForm) {
                    // Profile completion is mandatory - prevent closing
                    showInlineError('Please enter your details to continue');
                    e.preventDefault();
                    return;
                }
            }
        });
    }
    
    // Clear any leftover OTP timer
    if (otpTimer) {
        clearInterval(otpTimer);
        otpTimer = null;
    }
});

// ==========================================
// MODAL CONTROLS
// ==========================================

// Open modal
function openSignInModal(context = 'default') {
    console.log('openSignInModal() called with context:', context);
    
    // Clear any leftover state from previous sessions
    sessionStorage.removeItem('tempEmail');
    
    const modal = document.getElementById('signinModal');
    console.log('Modal element:', modal);
    
    if (!modal) {
        console.error('Modal element #signinModal not found!');
        return;
    }
    
    // Update modal message based on context
    const titleElement = document.getElementById('signinModalTitle');
    const subtitleElement = document.getElementById('signinModalSubtitle');
    
    if (context === 'booking') {
        if (titleElement) titleElement.textContent = 'Login to Book Tickets';
        if (subtitleElement) subtitleElement.textContent = 'Please login or sign up to book tickets';
    } else if (context === 'save') {
        if (titleElement) titleElement.textContent = 'Save Movies for Later';
        if (subtitleElement) subtitleElement.textContent = 'Please sign in to save movies to your watchlist';
    } else {
        if (titleElement) titleElement.textContent = 'Welcome to Bookora';
        if (subtitleElement) subtitleElement.textContent = 'Choose your preferred sign-in method';
    }
    
    modal.classList.add('active');
    document.body.style.overflow = 'hidden'; // Prevent background scroll
    
    console.log('Modal should be visible now');
    
    // Always reset to auth choice screen on open
    showAuthChoiceScreen();
}

// Close modal
function closeSignInModal() {
    // Prevent closing if profile completion is in progress
    const profileCompletionForm = document.querySelector('.profile-completion-form');
    if (profileCompletionForm) {
        // Show inline validation message
        showInlineError('Please enter your details to continue');
        return; // Block modal close
    }
    
    const modal = document.getElementById('signinModal');
    modal.classList.remove('active');
    document.body.style.overflow = ''; // Restore scroll
    
    // Clear timer if running
    if (otpTimer) {
        clearInterval(otpTimer);
        otpTimer = null;
    }
    
    // Clean up ALL session storage - critical for clean state
    sessionStorage.removeItem('tempEmail');
    
    // Reset modal to default auth choice screen for next open
    showAuthChoiceScreen();
}

// Handle authentication option selection (email is the only supported method)
function selectAuthMethod(method) {
    console.log(`User selected: ${method}`);
    showEmailScreen();
}

// Show email input screen
function showEmailScreen() {
    const modal = document.querySelector('.signin-modal');
    modal.innerHTML = `
        <button class="modal-close" onclick="closeSignInModal()">
            <i class="fas fa-times"></i>
        </button>
        
        <button class="modal-back" onclick="showAuthChoiceScreen()">
            <i class="fas fa-arrow-left"></i>
        </button>
        
        <div class="modal-header">
            <h2>Enter Email Address</h2>
            <p>We'll send you an OTP to verify</p>
        </div>
        
        <div class="mobile-input-container">
            <div class="email-input-wrapper">
                <i class="fas fa-envelope email-icon"></i>
                <input 
                    type="email" 
                    id="emailInput" 
                    class="email-input" 
                    placeholder="Enter your email address"
                >
            </div>
            <button class="btn-continue" onclick="sendEmailOTP()">
                Send OTP
            </button>
        </div>
        
        <div class="modal-footer">
            By continuing, you agree to our <a href="#">Terms of Service</a> and <a href="#">Privacy Policy</a>
        </div>
    `;
    
    // Focus on input and add Enter key support
    setTimeout(() => {
        const emailInput = document.getElementById('emailInput');
        if (emailInput) {
            emailInput.focus();
            emailInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    sendEmailOTP();
                }
            });
        }
    }, 100);
}

// Show auth choice screen (back button)
function showAuthChoiceScreen() {
    const modal = document.querySelector('.signin-modal');
    modal.innerHTML = `
        <button class="modal-close" onclick="closeSignInModal()">
            <i class="fas fa-times"></i>
        </button>
        
        <div class="modal-header">
            <h2>Welcome to Bookora</h2>
            <p>Choose your preferred sign-in method</p>
        </div>
        
        <div class="auth-options">
            <button class="auth-option-btn" onclick="selectAuthMethod('Email')">
                <i class="fas fa-envelope"></i>
                <span>Continue with Email</span>
            </button>
        </div>
        
        <div class="modal-footer">
            By continuing, you agree to our <a href="#">Terms of Service</a> and <a href="#">Privacy Policy</a>
        </div>
    `;
}

// OTP Timer variables
let otpTimer = null;
let otpSeconds = 30;
// How long the Resend button stays disabled. The server enforces its own cooldown
// (OTP_RESEND_COOLDOWN_SECONDS) and reports it as `resend_after` on a successful
// send; a hardcoded 30 here re-enabled the button before the server would accept
// another request, so every early click earned a 429. 30 remains the fallback for
// a response that does not carry the field.
let otpResendSeconds = 30;

// Send Email OTP via backend API
async function sendEmailOTP() {
    const emailInput = document.getElementById('emailInput');
    const email = emailInput.value.trim();
    
    // Simple email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
        showInlineError('Please enter a valid email address');
        emailInput.focus();
        return;
    }
    
    // Store email temporarily
    sessionStorage.setItem('tempEmail', email);
    sessionStorage.setItem('authType', 'email');
    
    // INSTANT loading state - don't wait for fetch
    const sendBtn = document.querySelector('.btn-continue');
    const originalText = sendBtn.textContent;
    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending...';
    sendBtn.style.opacity = '0.6';
    
    // Start timer to show OTP screen after 2 seconds max
    const quickTransitionTimer = setTimeout(() => {
        showEmailOTPScreen(email);
    }, 2000);
    
    try {
        // Call backend API
        const response = await BookoraAPI.fetch('/api/send-otp', {
            method: 'POST',
            body: JSON.stringify({ email: email })
        });
        
        const data = await response.json();
        
        // Clear the timer since we got response
        clearTimeout(quickTransitionTimer);
        
        if (data.success) {
            // Adopt the server's cooldown before rendering, so the countdown the
            // user sees is the one the server will actually honour.
            if (typeof data.resend_after === 'number' && data.resend_after > 0) {
                otpResendSeconds = data.resend_after;
            }
            // Show OTP screen immediately
            showEmailOTPScreen(email);
        } else {
            showInlineError(data.message || 'Failed to send OTP');
            sendBtn.disabled = false;
            sendBtn.textContent = originalText;
            sendBtn.style.opacity = '1';
        }
    } catch (error) {
        console.error('Error sending OTP:', error);
        // Clear timer on error
        clearTimeout(quickTransitionTimer);
        showInlineError('Network error. Please check if backend is running.');
        sendBtn.disabled = false;
        sendBtn.textContent = originalText;
        sendBtn.style.opacity = '1';
    }
}

// Show Email OTP verification screen
function showEmailOTPScreen(email) {
    const modal = document.querySelector('.signin-modal');
    const maskedEmail = maskEmail(email);
    
    modal.innerHTML = `
        <button class="modal-close" onclick="closeSignInModal()">
            <i class="fas fa-times"></i>
        </button>
        
        <button class="modal-back" onclick="showEmailScreen()">
            <i class="fas fa-arrow-left"></i>
        </button>
        
        <div class="modal-header">
            <h2>Verify OTP</h2>
            <p>Enter the 6-digit code sent to <strong>${maskedEmail}</strong></p>
        </div>
        
        <div class="otp-input-container">
            <div class="otp-boxes">
                <input type="text" maxlength="1" class="otp-box" data-index="0">
                <input type="text" maxlength="1" class="otp-box" data-index="1">
                <input type="text" maxlength="1" class="otp-box" data-index="2">
                <input type="text" maxlength="1" class="otp-box" data-index="3">
                <input type="text" maxlength="1" class="otp-box" data-index="4">
                <input type="text" maxlength="1" class="otp-box" data-index="5">
            </div>
            
            <div class="otp-timer">
                <span id="timerText">Resend OTP in <strong id="timerCount">30</strong>s</span>
                <button class="btn-resend" id="resendBtn" onclick="resendEmailOTP()" disabled>
                    Resend OTP
                </button>
            </div>
            
            <button class="btn-continue" onclick="verifyEmailOTP()">
                Verify & Continue
            </button>
        </div>
        
        <div class="modal-footer">
            Didn't receive the code? Check your inbox/spam folder or try a <a href="#" onclick="showEmailScreen()">different email</a>
        </div>
    `;
    
    // Initialize OTP input behavior
    initializeOTPInputs();
    
    // Start timer
    startOTPTimer();
}

// Mask email for privacy
function maskEmail(email) {
    const [localPart, domain] = email.split('@');
    if (localPart.length <= 3) {
        return `${localPart[0]}***@${domain}`;
    }
    const visibleStart = localPart.substring(0, 2);
    const visibleEnd = localPart.substring(localPart.length - 1);
    return `${visibleStart}***${visibleEnd}@${domain}`;
}

// Initialize OTP input boxes behavior
function initializeOTPInputs() {
    const otpBoxes = document.querySelectorAll('.otp-box');
    
    otpBoxes.forEach((box, index) => {
        // Auto-focus next box on input
        box.addEventListener('input', (e) => {
            const value = e.target.value;
            
            // Only allow digits
            if (!/^\d$/.test(value) && value !== '') {
                e.target.value = '';
                return;
            }
            
            // Move to next box
            if (value && index < otpBoxes.length - 1) {
                otpBoxes[index + 1].focus();
            }
            
            // Auto-submit when all 6 digits are entered
            if (index === otpBoxes.length - 1 && value) {
                const otp = Array.from(otpBoxes).map(b => b.value).join('');
                if (otp.length === 6) {
                    // Small delay for better UX
                    setTimeout(() => {
                        const verifyBtn = document.querySelector('.btn-continue');
                        if (verifyBtn) verifyBtn.click();
                    }, 200);
                }
            }
        });
        
        // Handle backspace
        box.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && !e.target.value && index > 0) {
                otpBoxes[index - 1].focus();
            }
            
            // Handle Enter key - submit OTP
            if (e.key === 'Enter') {
                e.preventDefault();
                const verifyBtn = document.querySelector('.btn-continue');
                if (verifyBtn) verifyBtn.click();
            }
        });
        
        // Prevent non-numeric input
        box.addEventListener('keypress', (e) => {
            if (!/^\d$/.test(e.key) && e.key !== 'Enter') {
                e.preventDefault();
            }
        });
        
        // Handle paste
        box.addEventListener('paste', (e) => {
            e.preventDefault();
            const pastedData = e.clipboardData.getData('text').replace(/\D/g, '');
            
            if (pastedData.length === 6) {
                otpBoxes.forEach((b, i) => {
                    b.value = pastedData[i] || '';
                });
                otpBoxes[5].focus();
                // Auto-submit after paste
                setTimeout(() => {
                    const verifyBtn = document.querySelector('.btn-continue');
                    if (verifyBtn) verifyBtn.click();
                }, 200);
            }
        });
    });
    
    // Focus first box
    otpBoxes[0].focus();
}

// Start OTP timer
function startOTPTimer() {
    otpSeconds = otpResendSeconds;
    const timerCount = document.getElementById('timerCount');
    const timerText = document.getElementById('timerText');
    const resendBtn = document.getElementById('resendBtn');

    if (!timerCount || !timerText || !resendBtn) return;

    if (otpTimer) clearInterval(otpTimer);
    timerCount.textContent = otpSeconds;
    resendBtn.disabled = true;
    timerText.style.display = 'block';
    
    otpTimer = setInterval(() => {
        otpSeconds--;
        timerCount.textContent = otpSeconds;
        
        if (otpSeconds <= 0) {
            clearInterval(otpTimer);
            timerText.style.display = 'none';
            resendBtn.disabled = false;
        }
    }, 1000);
}

// Resend Email OTP via backend API
async function resendEmailOTP() {
    const email = sessionStorage.getItem('tempEmail');
    
    const resendBtn = document.getElementById('resendBtn');
    resendBtn.disabled = true;
    resendBtn.textContent = 'Sending...';
    
    try {
        const response = await BookoraAPI.fetch('/api/send-otp', {
            method: 'POST',
            body: JSON.stringify({ email: email })
        });
        
        const data = await response.json();
        
        if (data.success) {
            if (typeof data.resend_after === 'number' && data.resend_after > 0) {
                otpResendSeconds = data.resend_after;
            }
            // Clear all OTP boxes
            document.querySelectorAll('.otp-box').forEach(box => box.value = '');
            document.querySelectorAll('.otp-box')[0].focus();
            
            // Restart timer
            startOTPTimer();
            
            resendBtn.textContent = 'OTP Sent!';
            setTimeout(() => {
                resendBtn.textContent = 'Resend OTP';
            }, 2000);
        } else {
            showInlineError(data.message || 'Failed to resend OTP');
            resendBtn.disabled = false;
            resendBtn.textContent = 'Resend OTP';
        }
    } catch (error) {
        console.error('Error resending OTP:', error);
        showInlineError('Network error. Please try again.');
        resendBtn.disabled = false;
        resendBtn.textContent = 'Resend OTP';
    }
}

// ==========================================
// EMAIL OTP FUNCTIONS
// ==========================================

// Verify Email OTP via backend API
async function verifyEmailOTP() {
    const otpBoxes = document.querySelectorAll('.otp-box');
    const otp = Array.from(otpBoxes).map(box => box.value).join('');
    
    if (otp.length !== 6) {
        showInlineError('Please enter complete 6-digit OTP');
        return;
    }
    
    // Clear timer
    if (otpTimer) {
        clearInterval(otpTimer);
    }
    
    const email = sessionStorage.getItem('tempEmail');
    
    // Show verifying animation
    showVerifyingState();
    
    try {
        const response = await BookoraAPI.fetch('/api/verify-otp', {
            method: 'POST',
            body: JSON.stringify({ email: email, otp: otp, type: 'email' })
        });
        
        const data = await response.json();
        
        console.log('OTP Verification Response:', data);
        
        if (data.success) {
            if (!data.userExists) {
                // New user - show success animation first, then profile completion
                showSuccessState('OTP Verified!', 'Setting up your profile...');
                setTimeout(() => {
                    showProfileCompletionScreen('email');
                }, 2500);
            } else {
                // Existing user - show personalized welcome message
                const userData = {
                    id: data.user.id,
                    name: data.user.name || 'User',
                    email: data.user.email,
                    phone: data.user.phone,
                    role: data.user.role || 'user',
                    loginMethod: 'email'
                };
                
                // Show personalized welcome with 2.5 second success state
                showSuccessState(
                    `Welcome back, ${userData.name}!`,
                    'Great to see you again. Loading your experience...'
                );
                
                setTimeout(() => {
                    loginUser(userData);
                    sessionStorage.removeItem('tempEmail');
                    closeSignInModal();
                    console.log('Existing user logged in:', userData);
                }, 2500); // 2.5 second personalized welcome
            }
        } else {
            // Show error and go back to OTP screen
            showEmailOTPScreen(email);
            setTimeout(() => {
                showInlineError(data.message || 'Invalid or expired OTP');
            }, 100);
        }
    } catch (error) {
        console.error('Error verifying OTP:', error);
        showEmailOTPScreen(email);
        setTimeout(() => {
            showInlineError('Network error. Please try again.');
        }, 100);
    }
}

// Show profile completion screen
function showProfileCompletionScreen(loginMethod) {
    const modal = document.querySelector('.signin-modal');

    modal.innerHTML = `
        <div class="modal-header">
            <h2>Welcome to BOOKORA!</h2>
            <p>Just one more step to get started</p>
        </div>
        
        <form class="profile-completion-form" onsubmit="event.preventDefault(); submitProfileCompletion('${loginMethod}');">
            <div class="form-group">
                <label class="form-label">Full Name <span class="required">*</span></label>
                <input 
                    type="text" 
                    id="profileName" 
                    class="form-input" 
                    placeholder="Enter your full name"
                    required
                    autocomplete="name"
                >
            </div>
            
            ${loginMethod === 'email' ? `
            <div class="form-group">
                <label class="form-label">Mobile Number <span class="optional">(Optional)</span></label>
                <div class="phone-input-wrapper">
                    <span class="country-prefix">+91</span>
                    <input 
                        type="tel" 
                        id="profileMobile" 
                        class="form-input" 
                        placeholder="Enter 10-digit mobile number"
                        maxlength="10"
                        autocomplete="tel"
                    >
                </div>
            </div>
            ` : ''}

            <button type="submit" class="btn-primary-bookora">
                Complete Profile
            </button>
        </form>
        
        <div class="modal-footer">
            We'll use these details for booking confirmations
        </div>
    `;
    
    setTimeout(() => {
        const nameInput = document.getElementById('profileName');
        if (nameInput) nameInput.focus();
    }, 100);
}

// Submit profile completion via backend API
async function submitProfileCompletion(loginMethod) {
    const name = document.getElementById('profileName').value.trim();
    
    if (!name) {
        showInlineError('Please enter your full name');
        document.getElementById('profileName').focus();
        return;
    }
    
    // Validate name format (letters and spaces only, 2-50 characters)
    const nameRegex = /^[A-Za-z][A-Za-z ]{1,49}$/;
    if (!nameRegex.test(name)) {
        showInlineError('Please enter a valid full name (letters only)');
        document.getElementById('profileName').focus();
        return;
    }
    
    // Email is the only supported sign-in method
    const email = sessionStorage.getItem('tempEmail');
    let phone = null;
    const primary_contact_type = 'email';

    // Optionally collect a secondary contact (mobile number)
    const mobileInput = document.getElementById('profileMobile');
    if (mobileInput && mobileInput.value) {
        const mobile = mobileInput.value.trim();
        if (mobile.length > 0) {
            if (mobile.length === 10 && /^\d{10}$/.test(mobile)) {
                phone = `+91${mobile}`;
            } else {
                // Invalid mobile format - show error
                showInlineError('Mobile number must be exactly 10 digits');
                mobileInput.focus();
                return;
            }
        }
    }

    // Save to backend
    saveUserProfile(name, email, phone, primary_contact_type);
}

async function saveUserProfile(name, email, phone, primary_contact_type) {
    const submitBtn = document.querySelector('.btn-primary-bookora');
    if (!submitBtn) {
        console.error('Submit button not found');
        return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving...';
    
    try {
        const response = await BookoraAPI.fetch('/api/complete-profile', {
            method: 'POST',
            body: JSON.stringify({
                name: name,
                email: email,
                phone: phone,
                primaryContact: primary_contact_type
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            console.log('Profile saved successfully');
            
            showSuccessState('Welcome to BOOKORA!', `Hi ${name}! Let's find you a movie...`);
            
            setTimeout(() => {
                loginUser(data.user);
                sessionStorage.clear(); // Clear all temp data
                closeSignInModal();
            }, 2500);
        } else {
            showInlineError(data.message || 'Failed to save profile');
            submitBtn.disabled = false;
            submitBtn.textContent = 'Complete Profile';
        }
    } catch (error) {
        console.error('Profile save error:', error);
        showInlineError('Cannot connect to server');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Complete Profile';
    }
}

// Show inline error message (replaces alert for better UX)
function showInlineError(message) {
    // Remove existing error if any
    const existingError = document.querySelector('.inline-error');
    if (existingError) existingError.remove();
    
    const errorDiv = document.createElement('div');
    errorDiv.className = 'inline-error';
    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${message}`;
    
    const modalHeader = document.querySelector('.modal-header');
    if (modalHeader) {
        modalHeader.insertAdjacentElement('afterend', errorDiv);
        
        // Auto-remove after 3 seconds
        setTimeout(() => {
            errorDiv.classList.add('fade-out');
            setTimeout(() => errorDiv.remove(), 300);
        }, 3000);
    }
}

// Show verifying state with animation
function showVerifyingState() {
    const modal = document.querySelector('.signin-modal');
    modal.classList.add('screen-transition');
    
    modal.innerHTML = `
        <div class="verifying-container">
            <div class="verifying-spinner">
                <div class="spinner-ring"></div>
                <i class="fas fa-shield-alt spinner-icon"></i>
            </div>
            <h3>Verifying...</h3>
            <p>Please wait a moment</p>
        </div>
    `;
    
    setTimeout(() => modal.classList.remove('screen-transition'), 50);
}

// Show success state with custom message (smooth transition)
function showSuccessState(title, subtitle) {
    const modal = document.querySelector('.signin-modal');
    modal.classList.add('screen-transition');
    
    modal.innerHTML = `
        <div class="success-container">
            <div class="success-icon-wrapper">
                <div class="success-circle">
                    <i class="fas fa-check success-checkmark"></i>
                </div>
                <div class="success-ripple"></div>
                <div class="success-ripple delay-1"></div>
                <div class="success-ripple delay-2"></div>
            </div>
            <h2>${title}</h2>
            <p class="success-subtitle">${subtitle}</p>
        </div>
    `;
    
    setTimeout(() => modal.classList.remove('screen-transition'), 50);
}

// Show logout confirmation toast (non-blocking feedback)
function showLogoutConfirmation(userName) {
    // Remove any existing toast
    const existingToast = document.querySelector('.logout-toast');
    if (existingToast) existingToast.remove();
    
    // Create toast element
    const toast = document.createElement('div');
    toast.className = 'logout-toast';
    toast.innerHTML = `
        <div class="toast-icon">
            <i class="fas fa-check-circle"></i>
        </div>
        <div class="toast-content">
            <div class="toast-title">You've been logged out</div>
            <div class="toast-message">See you soon, ${userName}!</div>
        </div>
    `;
    
    // Add to body
    document.body.appendChild(toast);
    
    // Trigger animation after DOM insertion
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);
    
    // Remove after 3.5 seconds (visible for 3 seconds)
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 500); // Wait for fade-out animation
    }, 3500);
}

// Close modal when clicking outside
document.addEventListener('click', (e) => {
    const modal = document.getElementById('signinModal');
    if (modal && e.target === modal) {
        closeSignInModal();
    }
});

// Close modal with Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeSignInModal();
    }
});

// Sync auth UI when navigating with browser back/forward cache
window.addEventListener('pageshow', () => {
    updateAuthUI();
});

console.log('signin-modal.js loaded completely');
console.log('openSignInModal is:', typeof openSignInModal);

