'use strict';
(() => {
  const root = document.documentElement;
  document.querySelectorAll('.theme-choices').forEach(panel => {
    for (const [value, name] of window.NavTheme.catalog) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'theme-choice'; button.dataset.themeChoice = value;
      button.setAttribute('aria-pressed', String(window.NavTheme.get() === value));
      button.setAttribute('aria-label', name); button.title = name;
      button.innerHTML = `<span class="theme-swatch swatch-${value}" aria-hidden="true"></span><span class="theme-name">${name}</span><span class="theme-check" aria-hidden="true">✓</span>`;
      panel.append(button);
    }
  });
  const defaults = {mode: 'theme', interval: 1440, motion: true, id: '', daily_id: '', changed: 0};
  const intervals = [0, 1, 5, 15, 60, 1440];
  function read() {
    try {
      const value = JSON.parse(localStorage.getItem('nav-background')) || {};
      return {mode: ['daily','landscape'].includes(value.mode) ? 'daily' : 'theme',
        interval: intervals.includes(value.interval) ? value.interval : 1440,
        motion: value.motion !== false, id: typeof value.id === 'string' ? value.id : '',
        daily_id: typeof value.daily_id === 'string' ? value.daily_id : '',
        changed: Number.isFinite(value.changed) ? Math.max(0, Math.min(value.changed, Date.now())) : 0};
    } catch { return {...defaults}; }
  }
  let settings = read(), catalog = [], active = false, timer, revision = 0, current = -1;
  let catalogRequest, catalogMeta = {}, pollTimer;
  const photos = [...document.querySelectorAll('.background-photo')];
  const mode = document.querySelector('#background-mode'), interval = document.querySelector('#background-interval');
  const motion = document.querySelector('#background-motion'), next = document.querySelector('#next-background');
  const credit = document.querySelector('#background-credit'), status = document.querySelector('#background-status');
  const panel = document.querySelector('#background-panel'), trigger = document.querySelector('#open-background');
  function persist() { try { localStorage.setItem('nav-background', JSON.stringify(settings)); } catch {} }
  function feedback(text = '') { status.textContent = text; status.hidden = !text; }
  function syncControls() {
    mode.value = settings.mode; interval.value = String(settings.interval); motion.checked = settings.motion;
    next.hidden = document.querySelector('#background-interval-label').hidden = settings.mode !== 'daily';
    root.dataset.motion = settings.motion ? 'on' : 'off';
  }
  function clearPhoto() {
    photos.forEach(img => { img.classList.remove('visible'); img.removeAttribute('src'); });
    root.dataset.background = 'theme'; credit.hidden = true; current = -1;
  }
  function schedule() {
    clearTimeout(timer);
    if (!active || settings.mode !== 'daily' || !settings.interval || document.hidden) return;
    // Bound the timer; a failed image is retried after a minute, never in a tight loop.
    const remaining = Math.max(1000, settings.changed + settings.interval * 60000 - Date.now());
    timer = setTimeout(() => display(true), Math.min(remaining, 86400000));
  }
  async function loadCatalog(force = false) {
    if (!catalogRequest || force) catalogRequest = fetch('/api/v1/backgrounds', {credentials:'same-origin'}).then(r => {
      if (!r.ok) throw new Error(); return r.json();
    }).then(result => {
      const data = result.data;
      const valid = data.photos.filter(p => {
        const daily = /^\d{4}-\d\d-\d\d-\d+$/.test(p.id) && p.image === `/api/v1/backgrounds/${p.id}.jpg`;
        const fallback = /^\d+$/.test(p.id) && p.image === `/static/backgrounds/${p.id}.jpg`;
        return (daily || fallback) && new URL(p.source).origin === 'https://unsplash.com';
      });
      if (!valid.length) throw new Error(); catalog = valid; catalogMeta = data;
    }).catch(error => { catalogRequest = null; throw error; });
    await catalogRequest;
  }
  function sourceStatus() {
    feedback(catalogMeta.status === 'ready' ? '' : catalogMeta.status === 'stale' ? '今日图片稍后更新，暂用上次背景' : '今日图片获取中，暂用备用背景');
  }
  function poll() {
    clearTimeout(pollTimer);
    if (!active || settings.mode !== 'daily' || document.hidden) return;
    pollTimer = setTimeout(async () => {
      try {
        const previous = catalogMeta.daily_id;
        await loadCatalog(true);
        if (previous !== catalogMeta.daily_id || current < 0) await display();
        else sourceStatus();
      } catch { feedback('图片更新暂时不可用，稍后重试'); }
      poll();
    }, 60000);
  }
  async function display(advance = false) {
    const id = ++revision;
    clearTimeout(timer); syncControls();
    if (!active || settings.mode !== 'daily') { clearPhoto(); feedback(); return; }
    next.disabled = true;
    try {
      await loadCatalog();
      if (id !== revision) return;
      let index = catalog.findIndex(p => p.id === settings.id);
      const fresh = catalogMeta.daily_id && settings.daily_id !== catalogMeta.daily_id;
      const due = settings.interval && Date.now() >= settings.changed + settings.interval * 60000;
      if (fresh) index = catalog.findIndex(p => p.id === catalogMeta.daily_id);
      else if (index < 0) index = 0;
      else if (advance || due) index = (index + 1) % catalog.length;
      const photo = catalog[index];
      if (current >= 0 && photos[current].getAttribute('src') === photo.image) { sourceStatus(); schedule(); return; }
      // Preload before replacing the previous frame; stale requests cannot change the page.
      const target = current === 0 ? 1 : 0;
      photos[target].src = photo.image;
      let timeout;
      try {
        await Promise.race([photos[target].decode(), new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error()), 12000); })]);
      } finally { clearTimeout(timeout); }
      if (id !== revision) return;
      photos[target].classList.add('visible');
      if (current >= 0) photos[current].classList.remove('visible');
      current = target; root.dataset.background = 'landscape';
      if (photo.id !== settings.id || !settings.changed || advance || due || fresh) {
        settings.id = photo.id; settings.daily_id = catalogMeta.daily_id || ''; settings.changed = Date.now(); persist();
      }
      credit.textContent = `摄影 ${photo.author} · Unsplash`; credit.href = photo.source; credit.hidden = false;
      sourceStatus(); schedule();
    } catch {
      if (id !== revision) return;
      feedback('背景暂时无法加载，请稍后再试');
      if (active && settings.mode === 'daily' && !document.hidden) timer = setTimeout(() => display(advance), 60000);
    } finally { if (id === revision) next.disabled = false; }
  }
  function close() { panel.hidden = true; trigger.setAttribute('aria-expanded', 'false'); }
  trigger.onclick = () => { const open = panel.hidden; panel.hidden = !open; trigger.setAttribute('aria-expanded', String(open)); };
  mode.onchange = () => { settings.mode = mode.value; persist(); display(); poll(); };
  interval.onchange = () => { settings.interval = Number(interval.value); settings.changed = Date.now(); persist(); schedule(); };
  motion.onchange = () => { settings.motion = motion.checked; persist(); syncControls(); };
  next.onclick = () => display(true);
  document.addEventListener('click', event => { if (!event.target.closest('.background-picker')) close(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { clearTimeout(timer); clearTimeout(pollTimer); } else if (active) { loadCatalog(true).then(() => display()).catch(() => display()); poll(); } });
  window.addEventListener('storage', event => {
    if (event.key === 'nav-background' || event.key === null) { settings = read(); display(); poll(); }
  });
  window.NavAppearance = {
    start() { active = true; display(); poll(); },
    stop() { active = false; ++revision; clearTimeout(timer); clearTimeout(pollTimer); next.disabled = false; clearPhoto(); close(); }
  };
  syncControls();
})();
