(function () {
  'use strict';

  const rawFetch = window.fetch.bind(window);
  let readyResolve;
  let ready = new Promise((resolve) => { readyResolve = resolve; });
  let authenticated = false;
  let authEnabled = true;
  let username = '';

  const style = document.createElement('style');
  style.textContent = `
    .pq-auth-overlay{position:fixed;inset:0;z-index:100000;display:grid;place-items:center;padding:20px;background:rgba(8,15,28,.68);backdrop-filter:blur(10px)}
    .pq-auth-overlay[hidden],.pq-auth-panel[hidden]{display:none!important}
    .pq-auth-card{width:min(420px,100%);padding:26px;border:1px solid var(--line,#dce3ed);border-radius:18px;background:var(--panel,#fff);color:var(--text,#182235);box-shadow:0 24px 90px #0004}
    .pq-auth-card h2{margin:0 0 8px;font-size:22px}.pq-auth-card p{margin:0 0 20px;color:var(--muted,#68758a);font-size:13px;line-height:1.5}
    .pq-auth-card form{display:grid;gap:12px}.pq-auth-card label{display:grid;gap:6px;font-size:12px;font-weight:600}
    .pq-auth-card input{box-sizing:border-box;width:100%;padding:11px 12px;border:1px solid var(--line,#dce3ed);border-radius:9px;background:var(--bg,#f7f9fc);color:inherit;font:inherit}
    .pq-auth-card button,.pq-auth-panel button{border:1px solid var(--line,#dce3ed);border-radius:9px;padding:10px 12px;background:var(--panel2,#f4f7fb);color:inherit;font:inherit;cursor:pointer}
    .pq-auth-card button[type=submit]{background:var(--accent,#3b9dff);border-color:var(--accent,#3b9dff);color:#fff;font-weight:700}
    .pq-auth-error{min-height:18px;color:#c24141;font-size:12px}
    .pq-auth-widget{display:flex;align-items:center;gap:8px;margin:0 0 18px;padding:0 2px;width:100%;box-sizing:border-box}
    .pq-auth-user-icon{display:grid;place-items:center;flex:0 0 34px;width:34px;height:34px;border:1px solid var(--line,#dce3ed);border-radius:10px;background:var(--panel2,#f4f7fb);color:var(--accent,#3b9dff)}
    .pq-auth-user-icon svg{width:17px;height:17px}
    .pq-auth-trigger{flex:1;min-width:0;text-align:left;font-size:11px;font-weight:600;padding:10px 12px}
    .pq-auth-logout-inline{display:flex;align-items:center;justify-content:center;gap:6px;white-space:nowrap;font-size:11px;padding:10px 12px}
    .pq-auth-logout-inline svg{width:14px;height:14px}
    .pq-auth-panel{position:absolute;top:calc(100% + 6px);right:0;width:220px;padding:12px;display:grid;gap:8px;border:1px solid var(--line,#dce3ed);border-radius:12px;background:var(--panel,#fff);box-shadow:0 12px 40px #0002;z-index:1000}
    .pq-auth-panel b{font-size:12px}.pq-auth-panel button{text-align:left;font-size:12px}
    .pq-auth-notice{margin-top:12px;color:var(--muted,#68758a);font-size:11px;line-height:1.5}
    .pq-auth-toast{position:fixed;z-index:100001;left:50%;bottom:24px;transform:translateX(-50%);padding:10px 14px;border:1px solid var(--line,#dce3ed);border-radius:10px;background:var(--panel,#fff);color:var(--text,#182235);box-shadow:0 8px 30px #0002;font-size:12px}
    @media(max-width:720px){
      .pq-auth-widget{position:fixed!important;top:12px!important;right:12px!important;z-index:9999!important;margin:0!important;background:var(--panel);padding:6px;border:1px solid var(--line);border-radius:10px;box-shadow:0 4px 16px #0003;width:auto!important}
    }
    @media(max-width:640px){.pq-auth-card{padding:20px}.pq-auth-panel{position:fixed;left:12px;right:12px;top:auto;bottom:calc(42px + 12px);width:auto;box-sizing:border-box}}
  `;
  document.head.appendChild(style);

  const overlay = document.createElement('div');
  overlay.className = 'pq-auth-overlay';
  overlay.id = 'pq-auth-overlay';
  overlay.hidden = true;
  overlay.innerHTML = `
    <section class="pq-auth-card" role="dialog" aria-modal="true" aria-labelledby="pq-auth-title">
      <h2 id="pq-auth-title">Вход в PQ localAgent OS</h2>
      <p>Введите системные учётные данные, чтобы открыть рабочее пространство и защищённые настройки.</p>
      <form id="pq-auth-form">
        <label>Логин<input id="pq-auth-username" name="username" autocomplete="username" value="root" required></label>
        <label>Пароль<input id="pq-auth-password" name="password" type="password" autocomplete="current-password" required autofocus></label>
        <div class="pq-auth-error" id="pq-auth-error" role="alert"></div>
        <button type="submit" id="pq-auth-submit">Войти</button>
      </form>
      <div class="pq-auth-notice">После первого входа рекомендуется сменить первоначальный пароль через меню «Доступ».</div>
    </section>`;
  document.body.appendChild(overlay);

  const widget = document.createElement('div');
  widget.className = 'pq-auth-widget';
  widget.innerHTML = `
    <span class="pq-auth-user-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"></circle><path d="M4.5 20a7.5 7.5 0 0 1 15 0"></path></svg></span>
    <button type="button" class="pq-auth-trigger btn secondary" id="pq-auth-trigger">Войти</button>
    <button type="button" class="pq-auth-logout-inline btn soft-secondary" id="pq-auth-logout" hidden aria-label="Выйти из системы" title="Выйти из системы"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 17l5-5-5-5"></path><path d="M15 12H3"></path><path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"></path></svg><span>Выйти</span></button>
    <div class="pq-auth-panel" id="pq-auth-panel" hidden>
      <b id="pq-auth-user-label">Вход выполнен</b>
      <button type="button" id="pq-auth-change">Сменить пароль</button>
    </div>`;
  const authViewport = window.matchMedia('(max-width:720px)');
  function placeAuthWidget() {
    const isMobile = authViewport.matches;
    const rightSidebar = document.querySelector('.right-sidebar');
    if (isMobile || !rightSidebar) {
      if (widget.parentElement !== document.body) document.body.appendChild(widget);
      widget.style.position = 'fixed';
      widget.style.top = '12px';
      widget.style.right = '12px';
      widget.style.zIndex = '9999';
      widget.style.width = 'auto';
    } else {
      if (widget.parentElement !== rightSidebar) rightSidebar.insertBefore(widget, rightSidebar.firstChild);
      widget.style.position = '';
      widget.style.top = '';
      widget.style.right = '';
      widget.style.zIndex = '';
      widget.style.width = '';
    }
  }
  placeAuthWidget();
  if (typeof authViewport.addEventListener === 'function') {
    authViewport.addEventListener('change', placeAuthWidget);
  } else if (typeof authViewport.addListener === 'function') {
    authViewport.addListener(placeAuthWidget);
  }

  const passwordOverlay = document.createElement('div');
  passwordOverlay.className = 'pq-auth-overlay';
  passwordOverlay.id = 'pq-password-overlay';
  passwordOverlay.hidden = true;
  passwordOverlay.innerHTML = `
    <section class="pq-auth-card" role="dialog" aria-modal="true" aria-labelledby="pq-password-title">
      <h2 id="pq-password-title">Сменить системный пароль</h2>
      <p>Новый пароль должен содержать не менее 12 символов. Он будет сохранён в виде криптографического хеша.</p>
      <form id="pq-password-form">
        <label>Новый пароль<input id="pq-new-password" type="password" autocomplete="new-password" minlength="12" required></label>
        <label>Повторите пароль<input id="pq-confirm-password" type="password" autocomplete="new-password" minlength="12" required></label>
        <div class="pq-auth-error" id="pq-password-error" role="alert"></div>
        <button type="submit" id="pq-password-submit">Сохранить пароль</button>
        <button type="button" id="pq-password-cancel">Отмена</button>
      </form>
    </section>`;
  document.body.appendChild(passwordOverlay);

  function resetReady() {
    ready = new Promise((resolve) => { readyResolve = resolve; });
  }
  function showLogin(message, forceModal) {
    passwordOverlay.hidden = true;
    widget.hidden = false;
    document.getElementById('pq-auth-trigger').textContent = 'Войти';
    document.getElementById('pq-auth-logout').hidden = true;
    document.getElementById('pq-auth-panel').hidden = true;
    overlay.hidden = !forceModal;
    const error = document.getElementById('pq-auth-error');
    if (error) error.textContent = message || '';
    if (forceModal) setTimeout(() => document.getElementById('pq-auth-password')?.focus(), 0);
  }
  function setAuthenticated(user) {
    authenticated = true;
    username = user || 'root';
    overlay.hidden = true;
    widget.hidden = false;
    document.getElementById('pq-auth-trigger').textContent = username;
    document.getElementById('pq-auth-logout').hidden = false;
    document.getElementById('pq-auth-user-label').textContent = 'Вход выполнен: ' + username;
    if (readyResolve) readyResolve();
  }
  function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'pq-auth-toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4500);
  }
  async function readJson(response) {
    try { return await response.json(); } catch (_) { return {}; }
  }

  document.getElementById('pq-auth-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = document.getElementById('pq-auth-submit');
    const error = document.getElementById('pq-auth-error');
    button.disabled = true;
    error.textContent = '';
    try {
      const response = await rawFetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: document.getElementById('pq-auth-username').value.trim(),
          password: document.getElementById('pq-auth-password').value
        })
      });
      const data = await readJson(response);
      if (!response.ok) throw new Error(data.error || 'Не удалось войти.');
      setAuthenticated(data.username);
      document.getElementById('pq-auth-password').value = '';
      if (data.must_change_password) showToast('Используется первоначальный пароль. Рекомендуется сменить его.');
    } catch (err) {
      error.textContent = err.message || 'Ошибка входа.';
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById('pq-auth-trigger').addEventListener('click', () => {
    if (!authenticated) {
      showLogin('', true);
      return;
    }
    const panel = document.getElementById('pq-auth-panel');
    panel.hidden = !panel.hidden;
  });
  document.getElementById('pq-auth-change').addEventListener('click', () => {
    document.getElementById('pq-auth-panel').hidden = true;
    document.getElementById('pq-password-error').textContent = '';
    document.getElementById('pq-new-password').value = '';
    document.getElementById('pq-confirm-password').value = '';
    passwordOverlay.hidden = false;
    document.getElementById('pq-new-password').focus();
  });
  document.getElementById('pq-password-cancel').addEventListener('click', () => { passwordOverlay.hidden = true; });
  document.getElementById('pq-password-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const next = document.getElementById('pq-new-password').value;
    const confirm = document.getElementById('pq-confirm-password').value;
    const error = document.getElementById('pq-password-error');
    if (next.length < 12) { error.textContent = 'Минимальная длина пароля — 12 символов.'; return; }
    if (next !== confirm) { error.textContent = 'Пароли не совпадают.'; return; }
    const button = document.getElementById('pq-password-submit');
    button.disabled = true;
    error.textContent = '';
    try {
      const response = await rawFetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: next })
      });
      const data = await readJson(response);
      if (!response.ok) throw new Error(data.error || 'Не удалось изменить пароль.');
      passwordOverlay.hidden = true;
      showToast('Системный пароль обновлён.');
    } catch (err) {
      error.textContent = err.message || 'Ошибка смены пароля.';
    } finally {
      button.disabled = false;
    }
  });
  document.getElementById('pq-auth-logout').addEventListener('click', async () => {
    try { await rawFetch('/api/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); } catch (_) {}
    authenticated = false;
    username = '';
    resetReady();
    document.getElementById('pq-auth-panel').hidden = true;
    showLogin('', false);
  });

  window.fetch = async function (input, init) {
    if (!authEnabled) return rawFetch(input, init);
    const rawUrl = typeof input === 'string' ? input : (input && input.url) || '';
    let url;
    try { url = new URL(rawUrl, window.location.href); } catch (_) { return rawFetch(input, init); }
    if (!url.pathname.startsWith('/api/') || ['/api/auth/status','/api/auth/login','/api/auth/logout'].includes(url.pathname)) {
      return rawFetch(input, init);
    }
    await ready;
    let response = await rawFetch(input, init);
    if (response.status === 401) {
      if (authenticated) {
        authenticated = false;
        resetReady();
        showLogin('Сеанс завершён. Войдите повторно.', true);
      }
      await ready;
      response = await rawFetch(input, init);
    }
    return response;
  };

  (async function initAuth() {
    try {
      const response = await rawFetch('/api/auth/status', { cache: 'no-store' });
      const data = await readJson(response);
      if (data.auth_enabled === false) {
        authEnabled = false;
        authenticated = false;
        username = '';
        overlay.hidden = true;
        passwordOverlay.hidden = true;
        widget.hidden = true;
        if (readyResolve) readyResolve();
        return;
      }
      if (data.authenticated) setAuthenticated(data.username);
      else showLogin('', false);
    } catch (_) {
      showLogin('Не удалось связаться с сервером авторизации.', true);
    }
  })();

  window.PQAuth = {
    get authenticated() { return authenticated; },
    get username() { return username; },
    get ready() { return ready; }
  };
})();