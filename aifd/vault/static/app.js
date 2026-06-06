// aifd vault watch — single-page SPA (vanilla JS, no build step).
// Routes between three views: list / detail / webhooks. Hash-based.

(function () {
  'use strict';

  const state = {
    findings: [],
    total: 0,
    page: 0,
    pageSize: 50,
    filterStatus: 'new',
    filterCategory: '',
  };

  // ---------- routing ----------

  function showView(name) {
    document.querySelectorAll('.view').forEach((el) => el.classList.add('hidden'));
    document.querySelectorAll('.nav-link').forEach((el) => el.classList.remove('active'));
    const target = document.getElementById(name + '-view');
    if (target) target.classList.remove('hidden');
    const nav = document.querySelector(`.nav-link[data-view="${name}"]`);
    if (nav) nav.classList.add('active');
  }

  function handleHashChange() {
    const hash = (location.hash || '#list').slice(1);
    if (hash.startsWith('event/')) {
      const fp = hash.slice('event/'.length);
      loadDetail(fp);
    } else if (hash === 'webhooks') {
      showView('webhooks');
      loadWebhooks();
    } else {
      showView('list');
      loadFindings();
    }
  }

  // ---------- list view ----------

  function buildListQuery() {
    const params = new URLSearchParams();
    if (state.filterStatus) params.set('status', state.filterStatus);
    if (state.filterCategory) params.set('category', state.filterCategory);
    params.set('limit', state.pageSize);
    params.set('offset', state.page * state.pageSize);
    return params.toString();
  }

  async function loadFindings() {
    const tbody = document.getElementById('findings-body');
    tbody.innerHTML = '<tr><td colspan="6" class="empty">Loading…</td></tr>';
    try {
      const resp = await fetch('/events?' + buildListQuery());
      const data = await resp.json();
      state.findings = data.findings || [];
      state.total = data.total || 0;
      renderFindings();
    } catch (err) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">Error: ' + err.message + '</td></tr>';
    }
  }

  function renderFindings() {
    const tbody = document.getElementById('findings-body');
    document.getElementById('total-count').textContent =
      state.total + ' total · showing ' + state.findings.length;
    document.getElementById('page-info').textContent =
      'Page ' + (state.page + 1) + ' of ' +
      Math.max(1, Math.ceil(state.total / state.pageSize));
    document.getElementById('prev-page').disabled = state.page === 0;
    document.getElementById('next-page').disabled =
      (state.page + 1) * state.pageSize >= state.total;

    if (state.findings.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">No findings match current filters.</td></tr>';
      return;
    }
    tbody.innerHTML = state.findings.map(function (f) {
      return '<tr class="clickable" data-fp="' + escapeAttr(f.fingerprint) + '">' +
        '<td><span class="status-badge status-' + escapeAttr(f.status) + '">' +
        escapeText(f.status) + '</span></td>' +
        '<td>' + escapeText(f.category) + '</td>' +
        '<td><code>' + escapeText(f.snippet_redacted) + '</code></td>' +
        '<td class="num">' + f.count + '</td>' +
        '<td>' + escapeText((f.last_seen || '').slice(0, 19)) + '</td>' +
        '<td class="fingerprint">' + escapeText(f.fingerprint) + '</td>' +
        '</tr>';
    }).join('');
    tbody.querySelectorAll('tr.clickable').forEach(function (tr) {
      tr.addEventListener('click', function () {
        location.hash = 'event/' + tr.getAttribute('data-fp');
      });
    });
  }

  // ---------- detail view ----------

  async function loadDetail(fingerprint) {
    showView('detail');
    const body = document.getElementById('detail-body');
    body.innerHTML = 'Loading…';
    try {
      const resp = await fetch('/events/' + encodeURIComponent(fingerprint));
      if (resp.status === 404) {
        body.innerHTML = '<p>Not found.</p>';
        return;
      }
      const data = await resp.json();
      renderDetail(data);
    } catch (err) {
      body.innerHTML = '<p>Error: ' + err.message + '</p>';
    }
  }

  function renderDetail(data) {
    const f = data.finding;
    const pb = data.playbook || {};
    const lang = navigator.language && navigator.language.startsWith('zh') ? 'zh' : 'en';
    const instruction = (pb.instruction && (pb.instruction[lang] || pb.instruction.en)) || '';

    const body = document.getElementById('detail-body');
    body.innerHTML = '' +
      '<h2>' +
      '<span class="status-badge status-' + escapeAttr(f.status) + '">' + escapeText(f.status) + '</span> ' +
      escapeText(f.category) +
      '</h2>' +
      '<p><strong>Snippet:</strong> <code>' + escapeText(f.snippet_redacted) + '</code></p>' +
      '<p><strong>Fingerprint:</strong> <code>' + escapeText(f.fingerprint) + '</code></p>' +
      '<p><strong>Count:</strong> ' + f.count + ' · ' +
      '<strong>First seen:</strong> ' + escapeText((f.first_seen || '').slice(0, 19)) + ' · ' +
      '<strong>Last seen:</strong> ' + escapeText((f.last_seen || '').slice(0, 19)) + '</p>' +
      (f.notes ? '<p><strong>Notes:</strong> ' + escapeText(f.notes) + '</p>' : '') +
      '<div class="actions">' +
      '<button class="ack" data-action="ack">Ack</button>' +
      '<button class="mute" data-action="mute-24h">Mute 24h</button>' +
      '<button class="mute" data-action="mute">Mute forever</button>' +
      '<button class="resolve" data-action="resolve">Resolve</button>' +
      '</div>' +
      '<div class="playbook">' +
      '<h3>🔧 Rotation playbook' +
      (pb.severity ? ' · <span class="status-badge">' + escapeText(pb.severity) + '</span>' : '') +
      '</h3>' +
      (pb.vendor_dashboard ?
        '<a href="' + escapeAttr(pb.vendor_dashboard) + '" target="_blank" rel="noopener">→ ' +
        escapeText(pb.vendor_dashboard) + '</a>' : '') +
      '<pre>' + escapeText(instruction) + '</pre>' +
      '</div>' +
      '<div class="occurrences">' +
      '<h3>Occurrences (' + (data.occurrences || []).length + ')</h3>' +
      '<ul>' +
      (data.occurrences || []).map(function (o) {
        return '<li>' + escapeText((o.seen_at || '').slice(0, 19)) + ' · ' +
          escapeText(o.file_basename) + ':' + o.line + '</li>';
      }).join('') +
      '</ul>' +
      '</div>';

    body.querySelectorAll('button[data-action]').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const action = btn.getAttribute('data-action');
        await mutateFinding(f.fingerprint, action);
        await loadDetail(f.fingerprint);
      });
    });
  }

  async function mutateFinding(fp, action) {
    const enc = encodeURIComponent(fp);
    if (action === 'ack') {
      await fetch('/events/' + enc + '/ack', { method: 'POST' });
    } else if (action === 'resolve') {
      await fetch('/events/' + enc + '/resolve', { method: 'POST' });
    } else if (action === 'mute') {
      await fetch('/events/' + enc + '/mute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
    } else if (action === 'mute-24h') {
      await fetch('/events/' + enc + '/mute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hours: 24 }),
      });
    }
  }

  // ---------- webhooks view ----------

  async function loadWebhooks() {
    const div = document.getElementById('webhooks-list');
    div.innerHTML = 'Loading…';
    try {
      const resp = await fetch('/webhooks');
      const data = await resp.json();
      renderWebhooks(data.webhooks || []);
    } catch (err) {
      div.innerHTML = '<p>Error: ' + err.message + '</p>';
    }
  }

  function renderWebhooks(webhooks) {
    const div = document.getElementById('webhooks-list');
    if (webhooks.length === 0) {
      div.innerHTML = '<p>No webhooks configured. Add one below.</p>';
      return;
    }
    div.innerHTML = webhooks.map(function (w) {
      return '<div class="webhook-card" data-id="' + escapeAttr(w.id) + '">' +
        '<div class="webhook-header">' +
        '<span class="webhook-id">' + escapeText(w.id) + '</span>' +
        '<span class="status-badge status-' + (w.enabled ? 'resolved' : 'muted') + '">' +
        (w.enabled ? 'ENABLED' : 'DISABLED') + '</span>' +
        '</div>' +
        '<div class="webhook-url">' + escapeText(w.url) + '</div>' +
        '<div>on: ' + escapeText((w.on || []).join(', ')) +
        ' · payload: ' + escapeText(w.payload_format) +
        ' · lang: ' + escapeText(w.lang) + '</div>' +
        '<div class="webhook-actions">' +
        '<button data-action="test">Test</button>' +
        (w.enabled ?
          '<button data-action="disable">Disable</button>' :
          '<button data-action="enable">Enable</button>') +
        '<button data-action="delete">Delete</button>' +
        '</div>' +
        '</div>';
    }).join('');
    div.querySelectorAll('.webhook-card').forEach(function (card) {
      const wid = card.getAttribute('data-id');
      card.querySelectorAll('button[data-action]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
          const action = btn.getAttribute('data-action');
          await webhookAction(wid, action);
        });
      });
    });
  }

  async function webhookAction(wid, action) {
    const encId = encodeURIComponent(wid);
    if (action === 'delete') {
      if (!confirm('Delete webhook ' + wid + '?')) return;
      await fetch('/webhooks/' + encId, { method: 'DELETE' });
    } else if (action === 'test') {
      const resp = await fetch('/webhooks/' + encId + '/test', { method: 'POST' });
      const data = await resp.json();
      alert((data.ok ? '✓ Test OK' : '✗ Test failed') + ': ' + (data.message || ''));
    } else if (action === 'enable' || action === 'disable') {
      await fetch('/webhooks/' + encId + '/' + action, { method: 'POST' });
    }
    await loadWebhooks();
  }

  function setupAddWebhookForm() {
    document.getElementById('add-webhook-form').addEventListener('submit', async function (e) {
      e.preventDefault();
      const form = e.target;
      const fd = new FormData(form);
      const cats = (fd.get('categories') || '').toString().trim();
      const body = {
        id: (fd.get('id') || '').toString().trim() || undefined,
        url: fd.get('url'),
        on: [fd.get('on')],
        filter_categories: cats ? cats.split(',').map(function (s) { return s.trim(); }) : [],
        payload_format: fd.get('payload_format'),
        lang: fd.get('lang'),
      };
      const resp = await fetch('/webhooks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (resp.status >= 400) {
        alert('Error: ' + (data.error || resp.status));
        return;
      }
      form.reset();
      await loadWebhooks();
    });
  }

  // ---------- utility ----------

  function escapeText(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
  function escapeAttr(s) {
    return escapeText(s).replace(/"/g, '&quot;');
  }

  // ---------- wire-up ----------

  function init() {
    document.getElementById('filter-status').addEventListener('change', function (e) {
      state.filterStatus = e.target.value;
      state.page = 0;
      loadFindings();
    });
    document.getElementById('filter-category').addEventListener('change', function (e) {
      state.filterCategory = e.target.value;
      state.page = 0;
      loadFindings();
    });
    document.getElementById('refresh-btn').addEventListener('click', loadFindings);
    document.getElementById('prev-page').addEventListener('click', function () {
      if (state.page > 0) { state.page -= 1; loadFindings(); }
    });
    document.getElementById('next-page').addEventListener('click', function () {
      state.page += 1; loadFindings();
    });
    setupAddWebhookForm();

    document.querySelectorAll('.nav-link, .back-btn').forEach(function (el) {
      el.addEventListener('click', function (e) {
        const target = el.getAttribute('data-view');
        if (target) {
          e.preventDefault();
          if (target === 'list') location.hash = 'list';
          else if (target === 'webhooks') location.hash = 'webhooks';
        }
      });
    });

    window.addEventListener('hashchange', handleHashChange);
    handleHashChange();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
