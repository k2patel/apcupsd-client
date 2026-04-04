// Shared client-side helpers: CSRF, logout, fetch wrapper
(function () {
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const m = document.cookie.match(/(?:^|;)\s*csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  window.apiFetch = async function (url, opts = {}) {
    const method = (opts.method || 'GET').toUpperCase();
    const headers = Object.assign({ Accept: 'application/json' }, opts.headers || {});
    if (method !== 'GET' && method !== 'HEAD') {
      headers['X-CSRF-Token'] = getCsrfToken();
      if (opts.body && !(opts.body instanceof FormData) && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
      }
    }
    const resp = await fetch(url, Object.assign({ credentials: 'same-origin' }, opts, { headers }));
    if (resp.status === 401) {
      window.location.href = '/login';
      throw new Error('unauthorized');
    }
    return resp;
  };

  document.addEventListener('click', async (e) => {
    if (e.target && e.target.id === 'logout-btn') {
      await window.apiFetch('/api/logout', { method: 'POST' });
      window.location.href = '/login';
    }
  });
})();
