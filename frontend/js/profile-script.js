/**
 * My Profile Page - Edit Profile Functionality
 */

let currentUser = null;
let originalName = '';
let isEditing = false;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    loadUserProfile();
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

// Load user profile data
function loadUserProfile() {
    if (!currentUser) return;
    
    document.getElementById('userName').value = currentUser.name || '';
    document.getElementById('userEmail').value = currentUser.email || 'Not provided';
    
    const phoneInput = document.getElementById('userPhone');
    const phoneLabel = document.getElementById('phoneLabel');
    const phoneReadonlyLabel = document.getElementById('phoneReadonlyLabel');
    
    if (currentUser.phone) {
        // Phone exists - make it read-only
        phoneInput.value = currentUser.phone;
        phoneInput.setAttribute('disabled', true);
        phoneReadonlyLabel.style.display = 'block';
        phoneLabel.textContent = 'Phone Number';
    } else {
        // Phone is NULL - allow adding it
        phoneInput.value = '';
        phoneInput.placeholder = 'Add your phone number';
        phoneReadonlyLabel.style.display = 'none';
        phoneLabel.textContent = 'Phone Number';
    }
    
    originalName = currentUser.name || '';
}

// Enable edit mode
function enableEdit() {
    if (isEditing) return;
    
    isEditing = true;
    
    // Enable name input
    const nameInput = document.getElementById('userName');
    nameInput.removeAttribute('readonly');
    nameInput.classList.add('editing');
    nameInput.focus();
    
    // Enable phone input ONLY if phone is NULL (not set yet)
    const phoneInput = document.getElementById('userPhone');
    const phoneLabel = document.getElementById('phoneLabel');
    
    if (!currentUser.phone) {
        phoneInput.removeAttribute('readonly');
        phoneInput.removeAttribute('disabled');
        phoneInput.classList.add('editing');
        phoneLabel.textContent = 'Add Phone Number';
    }
    
    // Hide edit button
    document.getElementById('editBtn').style.display = 'none';
    
    // Show save/cancel buttons
    document.getElementById('formActions').style.display = 'flex';
    
    // Clear any messages
    document.getElementById('messageBox').innerHTML = '';
}

// Cancel edit
function cancelEdit() {
    if (!isEditing) return;
    
    isEditing = false;
    
    // Restore original name
    document.getElementById('userName').value = originalName;
    
    // Disable name input
    const nameInput = document.getElementById('userName');
    nameInput.setAttribute('readonly', true);
    nameInput.classList.remove('editing');
    
    // Disable phone input and restore original state
    const phoneInput = document.getElementById('userPhone');
    const phoneLabel = document.getElementById('phoneLabel');
    phoneInput.setAttribute('readonly', true);
    phoneInput.classList.remove('editing');
    phoneLabel.textContent = 'Phone Number';
    
    if (!currentUser.phone) {
        phoneInput.value = '';
    } else {
        phoneInput.setAttribute('disabled', true);
    }
    
    // Show edit button
    document.getElementById('editBtn').style.display = 'inline-flex';
    
    // Hide save/cancel buttons
    document.getElementById('formActions').style.display = 'none';
    
    // Clear any messages
    document.getElementById('messageBox').innerHTML = '';
}

// Save changes
async function saveChanges() {
    const newName = document.getElementById('userName').value.trim();
    const newPhone = document.getElementById('userPhone').value.trim();
    
    // Validate name
    if (!newName) {
        showMessage('Name cannot be empty', 'error');
        return;
    }
    
    // Validate name format (letters and spaces only, 2-50 characters)
    const nameRegex = /^[A-Za-z][A-Za-z ]{1,49}$/;
    if (!nameRegex.test(newName)) {
        showMessage('Please enter a valid full name (letters only)', 'error');
        return;
    }
    
    // Check if anything changed
    const nameChanged = newName !== originalName;
    const phoneChanged = !currentUser.phone && newPhone; // Only allow adding phone if it was NULL
    
    if (!nameChanged && !phoneChanged) {
        cancelEdit();
        return;
    }
    
    // Validate phone format if being added
    if (phoneChanged) {
        const phoneRegex = /^[0-9]{10}$/;
        if (!phoneRegex.test(newPhone)) {
            showMessage('Please enter a valid 10-digit phone number', 'error');
            return;
        }
    }
    
    // Show loading
    const saveBtn = document.querySelector('.btn-save');
    const originalText = saveBtn.innerHTML;
    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    saveBtn.disabled = true;
    
    try {
        // The server identifies the user from the session cookie — no user_id sent.
        const updateData = {
            name: newName
        };

        // Only include phone if it's being added (was NULL before)
        if (phoneChanged) {
            updateData.phone = newPhone;
        }

        const response = await BookoraAPI.fetch('/api/profile/update', {
            method: 'PUT',
            body: JSON.stringify(updateData)
        });
        
        const data = await response.json();
        
        if (data.success) {
            // CRITICAL FIX: Fully replace localStorage.bookoraUser with updated data
            // This ensures navbar reflects the latest name immediately
            const updatedUser = {
                id: currentUser.id,
                email: currentUser.email,
                name: data.user.name,
                phone: data.user.phone || currentUser.phone,
                mobile: currentUser.mobile // Keep mobile if exists
            };
            
            // Replace localStorage completely (don't partially update)
            localStorage.setItem('bookoraUser', JSON.stringify(updatedUser));
            currentUser = updatedUser;
            
            // Update original name
            originalName = newName;
            
            // CRITICAL: Update navbar UI immediately without page reload
            updateNavbar();
            
            // Reload profile to reflect changes (especially phone readonly state)
            loadUserProfile();
            
            // Exit edit mode
            isEditing = false;
            const nameInput = document.getElementById('userName');
            nameInput.setAttribute('readonly', true);
            nameInput.classList.remove('editing');
            
            const phoneInput = document.getElementById('userPhone');
            phoneInput.setAttribute('readonly', true);
            phoneInput.classList.remove('editing');
            
            document.getElementById('editBtn').style.display = 'inline-flex';
            document.getElementById('formActions').style.display = 'none';
            
            // Show success message
            showMessage('Profile updated successfully!', 'success');
        } else {
            showMessage(data.message || 'Failed to update profile', 'error');
        }
    } catch (error) {
        console.error('Error updating profile:', error);
        showMessage('An error occurred. Please try again.', 'error');
    } finally {
        saveBtn.innerHTML = originalText;
        saveBtn.disabled = false;
    }
}

// Show message
function showMessage(message, type) {
    const messageBox = document.getElementById('messageBox');
    messageBox.innerHTML = `
        <div class="alert alert-${type === 'success' ? 'success' : 'danger'}">
            <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i>
            ${message}
        </div>
    `;
    
    // Auto-hide success messages after 3 seconds
    if (type === 'success') {
        setTimeout(() => {
            messageBox.innerHTML = '';
        }, 3000);
    }
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
