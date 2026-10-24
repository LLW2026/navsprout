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
  window.NavTheme = {
    catalog,
    get: () => selected,
    set(value) {
      apply(value);
      try { localStorage.setItem('nav-theme', selected); } catch {}
    }
  };
  media.addEventListener('change', () => { if (selected === 'auto') apply(selected); });
  window.addEventListener('storage', event => {
    if (event.key === 'nav-theme' || event.key === null) apply(event.newValue || 'pine');
  });
  apply(selected);
})();
