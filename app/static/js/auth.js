// Login and first-run setup handlers. Kept external so CSP can block inline JS.
(function () {
  async function parseError(resp, fallback) {
    const err = await resp.json().catch(() => ({}));
    return err.detail || fallback;
  }

  function showError(id, message) {
    const errBox = document.getElementById(id);
    if (!errBox) return;
    errBox.textContent = message;
    errBox.hidden = false;
  }

  const loginForm = document.getElementById('login-form');
  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const errBox = document.getElementById('login-error');
      if (errBox) errBox.hidden = true;
      const resp = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: document.getElementById('username').value,
          password: document.getElementById('password').value,
        }),
      });
      if (resp.ok) {
        window.location.href = '/';
      } else {
        showError('login-error', await parseError(resp, 'Login failed'));
      }
    });
  }

  const setupForm = document.getElementById('setup-form');
  if (setupForm) {
    setupForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const errBox = document.getElementById('setup-error');
      if (errBox) errBox.hidden = true;
      const pw = document.getElementById('password').value;
      const pw2 = document.getElementById('password2').value;
      if (pw !== pw2) {
        showError('setup-error', 'Passwords do not match');
        return;
      }
      const resp = await fetch('/api/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: document.getElementById('username').value,
          password: pw,
        }),
      });
      if (resp.ok) {
        window.location.href = '/';
      } else {
        showError('setup-error', await parseError(resp, 'Setup failed'));
      }
    });
  }
})();
