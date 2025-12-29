// Show error if present
const error = document.getElementById('error');
if (error && error.textContent.trim()) {
    error.classList.add('show');
}

// Focus password field
const passwordField = document.getElementById('password');
if (passwordField) {
    passwordField.focus();
}

