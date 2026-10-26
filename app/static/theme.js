'use strict';
// Apply before the stylesheet loads to avoid flashing the wrong theme.
(() => {
  const catalog = [
    ['pine', '青松绿'], ['sky', '晴空蓝'], ['sand', '暖杏橙'], ['violet', '雾紫'],
    ['ocean', '深海蓝'], ['graphite', '石墨黑'], ['glass', '晨光磨砂'], ['paper', '手作纸笺'],
    ['aurora', '流动极光'], ['sunset', '日落奶油'], ['terminal', '荧光终端'], ['auto', '跟随系统']
  ];
  const names = catalog.map(([name]) => name);
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let selected = 'pine';
  try { selected = localStorage.getItem('nav-theme') || 'pine'; } catch {}
  function apply(value) {
    selected = names.includes(value) ? value : 'pine';
    const resolved = selected === 'auto' ? (media.matches ? 'graphite' : 'pine') : selected;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themePreference = selected;
    document.dispatchEvent(new CustomEvent('nav-theme-change', {detail: selected}));
  }
  function readTransparency() {
    try {
      const raw = localStorage.getItem('nav-card-transparency');
      if (raw === null || !raw.trim()) return null;
      const value = Number(raw);
      return Number.isFinite(value) && value >= 0 && value <= 100 ? Math.round(value) : null;
    } catch { return null; }
  }
  let transparency = readTransparency();
  function applyTransparency(value) {
    transparency = value;
    const root = document.documentElement;
    if (value === null) {
      delete root.dataset.cardTransparency;
      root.style.removeProperty('--nav-card-transparency');
    } else {
      root.dataset.cardTransparency = String(value);
      root.style.setProperty('--nav-card-transparency', String(value));
    }
    document.dispatchEvent(new CustomEvent('nav-card-transparency-change'));
  }
  function defaultTransparency() {
    const color = getComputedStyle(document.documentElement).getPropertyValue('--surface').trim();
    const alpha = /^#[0-9a-f]{6}([0-9a-f]{2})$/i.exec(color);
    return alpha ? Math.round((1 - parseInt(alpha[1], 16) / 255) * 100) : 0;
  }
  window.NavTheme = {
    catalog,
    getTransparency: () => transparency ?? defaultTransparency(),
    setTransparency(value) {
      const number = Number(value);
      const normalized = Number.isFinite(number) ? Math.round(Math.max(0, Math.min(100, number))) : null;
      applyTransparency(normalized);
      try {
        if (normalized === null) localStorage.removeItem('nav-card-transparency');
        else localStorage.setItem('nav-card-transparency', String(normalized));
      } catch {}
    },
    get: () => selected,
    set(value) {
      apply(value);
      try { localStorage.setItem('nav-theme', selected); } catch {}
    }
  };
  media.addEventListener('change', () => { if (selected === 'auto') apply(selected); });
  window.addEventListener('storage', event => {
    if (event.key === 'nav-theme' || event.key === null) apply(event.newValue || 'pine');
    if (event.key === 'nav-card-transparency' || event.key === null) applyTransparency(readTransparency());
  });
  apply(selected);
  applyTransparency(transparency);
})();
