'use strict';
const $ = s => document.querySelector(s);
const e = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let csrf = '', categories = [], links = [], category = '', organization = '', editing = null, generation = 0, confirmAction = null;
let toastTimer;
const sectionNetworks = new Map();
let searchChoice = null, lastSearchQuery = '', lastSearchCount = 0, suggestionsWanted = false;
function localQuery() { return $('#search').value; }
function webSearch() {
  const keyword = $('#search').value.trim();
  if (!keyword) { $('#search').focus(); return; }
  const url = new URL('https://www.baidu.com/s');
  url.searchParams.set('wd', keyword);
  window.open(url.href, '_blank', 'noopener,noreferrer');
}
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 3200); }
function showLogin() { window.NavIcons.stop(); window.NavAppearance.stop(); $('#app-view').hidden = true; $('#login-view').hidden = false; document.querySelectorAll('dialog[open]').forEach(d => d.close()); }
async function api(path, options = {}) {
  const response = await fetch('/api/v1' + path, {credentials:'same-origin', ...options, headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrf, ...options.headers}});
  const data = await response.json();
  if (!response.ok) { if (response.status === 401 && path !== '/auth/login') showLogin(); throw new Error(data.error?.message || '请求未成功，请重试'); }
  return data;
}
function write(path, method, body) { return api(path, {method, body:JSON.stringify(body)}); }
function counts(c) { return categories.find(x => x.name === c)?.link_count || 0; }
function nav(visible = links) {
  const total = categories.reduce((sum, c) => sum + c.link_count, 0);
  $('#category-nav').innerHTML = `<button data-category="" class="${category === '' ? 'active' : ''}"><span class="nav-icon">▦</span>全部网址<small>${total}</small></button>` + categories.map(c => `<button draggable="true" data-cid="${c.id}" data-category="${e(c.name)}" title="拖动调整分类顺序" class="${category === c.name ? 'active' : ''}"><span class="nav-icon">▱</span>${e(c.name)}<small>${c.link_count}</small></button>`).join('');
  $('#heading').textContent = category || '全部网址'; $('#current-title').textContent = category || '全部网址';
  $('#total-count').textContent = `${visible.length} 个网址`; $('#footer-count').textContent = `共 ${total} 个网址 · ${categories.length} 个分类`;
}
function card(l) {
  const tone = [...l.name].reduce((sum, c) => sum + c.codePointAt(0), 0) % 5;
  const host = new URL(l.url).host;
  const icon = l.icon ? e(l.icon) : `<span class="site-initial">${e([...l.name][0])}</span><img data-favicon data-icon-origin="${e(new URL(l.url).origin)}" data-src="/api/v1/links/${encodeURIComponent(l.key)}/favicon" alt="" loading="lazy" decoding="async" width="26" height="26">`;
  return `<article class="link-card" data-key="${e(l.key)}" data-network="${l.network}"><button type="button" class="drag-handle" draggable="true" aria-label="拖动 ${e(l.name)}" title="拖动排序">⠿</button><a draggable="false" class="card-main" href="${e(l.url)}" target="_blank" rel="noopener noreferrer"><span class="site-icon tone-${tone}">${icon}</span><div class="card-copy"><h3 title="${e(l.name)}">${e(l.name)}</h3><p title="${e(l.description || host)}">${e(l.description || host)}</p><div class="badges">${l.organization !== '其他' ? `<span class="badge">${e(l.organization)}</span>` : ''}${l.network === 'lan' ? '<span class="badge lan">内网</span>' : ''}${l.environment !== 'none' ? `<span class="badge ${l.environment === 'test' ? 'test' : ''}">${l.environment === 'test' ? '测试' : '生产'}</span>` : ''}</div></div></a><details class="menu card-menu"><summary aria-label="管理 ${e(l.name)}">•••</summary><div class="menu-panel"><button data-action="edit" data-key="${e(l.key)}">编辑</button><button data-action="move" data-key="${e(l.key)}">移动至分类</button><button data-action="pin" data-key="${e(l.key)}">${l.pinned ? '取消置顶' : '置顶'}</button><button data-action="up" data-key="${e(l.key)}">上移</button><button data-action="down" data-key="${e(l.key)}">下移</button><button data-action="delete" data-key="${e(l.key)}" class="danger">删除</button></div></details></article>`;
}
function section(name, items, cname = '', pinned = false, source = null) {
  const id = pinned ? 'pinned' : String(source.id), selected = sectionNetworks.get(id) || '';
  const mixed = pinned ? links.some(l => window.NavGroups.pinned(l) && l.network === 'lan') && links.some(l => window.NavGroups.pinned(l) && l.network === 'public') : source.lan_count > 0 && source.public_count > 0;
  const filters = mixed ? `<div class="section-networks" role="group" aria-label="${e(name)}网络筛选">${[['','全部'],['lan','内网'],['public','公网']].map(([value,label]) => `<button type="button" data-section-id="${id}" data-section-network="${value}" aria-pressed="${selected === value}">${label}</button>`).join('')}</div>` : '';
  const empty = selected || localQuery() || $('#network-filter').value || $('#env-filter').value || organization ? '<div class="empty"><span>没有符合条件的网址</span><button data-clear-filters>清除筛选</button></div>' : `<div class="empty"><button data-add="${e(cname)}">＋ 添加网址</button></div>`;
  return `<section data-section="${id}"><div class="section-head"><span class="section-symbol">${pinned ? '☆' : '▱'}</span><h2>${e(name)}</h2><small>${items.length}</small>${filters}${!pinned ? `<div class="section-actions"><button type="button" data-batch-category="${source.id}" aria-label="批量编辑${e(cname)}" title="批量编辑"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M4 6h11M4 11h6M4 16h5M15 12l3-3 3 3-7 7-4 1 1-4z"/></svg></button><button type="button" data-sort-category="${source.id}" aria-label="${e(cname)}按名称排序" title="按名称排序">↕</button><button type="button" class="section-add" data-add="${e(cname)}" aria-label="在${e(cname)}添加网址" title="添加网址">＋</button></div>` : ''}</div>${items.length ? `<div class="grid">${window.NavGroups.render(items, card)}</div>` : empty}</section>`;
}
function render() {
  const visible = links.filter(l => { const selected = sectionNetworks.get(String(l.category_id)); return !selected || selected === l.network; });
  nav(visible.filter(l => !window.NavGroups.pinned(l) || !sectionNetworks.get('pinned') || sectionNetworks.get('pinned') === l.network));
  const filtering = localQuery() || organization || $('#network-filter').value || $('#env-filter').value;
  let html = '';
  const pinned = visible.filter(l => window.NavGroups.pinned(l) && (!sectionNetworks.get('pinned') || sectionNetworks.get('pinned') === l.network));
  if (pinned.length || (sectionNetworks.get('pinned') && links.some(l => window.NavGroups.pinned(l)))) html += section('常用置顶', pinned, '', true);
  for (const c of categories.filter(c => !category || c.name === category)) {
    const items = visible.filter(l => l.category === c.name && !window.NavGroups.pinned(l));
    if (items.length || sectionNetworks.get(String(c.id)) || !filtering) html += section(c.name, items, c.name, false, c);
  }
  if (!html) html = filtering ? '<div class="empty-results"><p>没有找到相关网址</p><button data-clear-filters>清除筛选</button></div>' : '<div class="empty-results"><p>还没有收藏</p><button id="first-category">添加分类</button></div>';
  $('#sections').innerHTML = html;
  window.NavIcons.refresh();
}
async function refresh() {
  const id = ++generation, requestedQuery = localQuery();
  $('#sections').setAttribute('aria-busy', 'true');
  try {
    const query = new URLSearchParams({q:requestedQuery, category, organization, network:$('#network-filter').value, environment:$('#env-filter').value});
    const [c, l, g] = await Promise.all([api('/categories'), api('/links?' + query), api('/groups')]);
    if (id !== generation || requestedQuery !== localQuery()) return;
    categories = c.data; links = l.data; window.NavGroups.set(g.data); lastSearchQuery = requestedQuery; lastSearchCount = links.length; $('#load-error').hidden = true; render(); updateSearchSuggestions();
  } catch (err) { $('#load-error').hidden = false; $('#load-error span').textContent = err.message; }
  finally { if (id === generation) $('#sections').setAttribute('aria-busy', 'false'); }
}
async function enter() { $('#login-view').hidden = true; $('#app-view').hidden = false; window.NavAppearance.start(); await refresh(); }
function openLink(link = null, cname = '') {
  if (!categories.length) { showCategories(); return; }
  editing = link?.key || null;
  const form = $('#link-form'); form.reset(); form.querySelector('.form-error').textContent = '';
  form.elements.category.innerHTML = categories.map(c => `<option>${e(c.name)}</option>`).join('');
  form.elements.category.value = link?.category || cname || category || categories[0].name;
  if (link) for (const [name, value] of Object.entries(link)) if (form.elements[name]) { if (name === 'pinned') form.elements[name].checked = value; else form.elements[name].value = value; }
  form.elements.key.readOnly = Boolean(link); $('#link-title').textContent = link ? '编辑网址' : '添加网址'; $('#link-dialog').showModal();
}
function confirmDialog(title, text, action, targets = null) {
  $('#confirm-title').textContent = title; $('#confirm-text').textContent = text; $('#confirm-form .form-error').textContent = '';
  $('#move-label').hidden = targets === null; $('#move-target').innerHTML = targets?.map(c => `<option value="${c.id}">${e(c.name)}</option>`).join('') || '';
  $('#confirm-submit').disabled = targets !== null && !targets.length; confirmAction = action; $('#confirm-dialog').showModal();
}
function showCategories() { renderCategories(); $('#categories-dialog .form-error').textContent = ''; if (!$('#categories-dialog').open) $('#categories-dialog').showModal(); }
function renderCategories() { $('#category-list').innerHTML = categories.map(c => `<div class="category-item" data-cid="${c.id}"><button type="button" class="category-drag" draggable="true" aria-label="拖动分类 ${e(c.name)}" title="拖动排序">⠿</button><input value="${e(c.name)}" aria-label="分类名称" maxlength="80"><small>${c.link_count}</small><button data-cat-action="save">保存</button><button data-cat-action="up" aria-label="上移${e(c.name)}">↑</button><button data-cat-action="down" aria-label="下移${e(c.name)}">↓</button><button data-cat-action="delete">删除</button></div>`).join(''); }
async function submit(form, fn) { const button = form.querySelector('[type="submit"]') || form.querySelector('button.primary'); button.disabled = true; try { await fn(); } catch (err) { (form.querySelector('.form-error') || form.closest('dialog').querySelector('.form-error')).textContent = err.message; } finally { button.disabled = false; } }
$('#login-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true; $('#login-error').textContent = '';
  try { const result = await write('/auth/login', 'POST', {username:form.elements.username.value,password:form.elements.password.value}); csrf = result.data.csrf; form.elements.password.value = ''; await enter(); } catch (err) { $('#login-error').textContent = err.message; } finally { button.disabled = false; }
});
$('#link-form').addEventListener('submit', event => { event.preventDefault(); const form = event.currentTarget; submit(form, async () => {
  const data = Object.fromEntries(new FormData(form)); data.pinned = form.elements.pinned.checked; data.sort_order = Number(data.sort_order);
  if (editing || !data.key) delete data.key;
  await write(editing ? '/links/' + encodeURIComponent(editing) : '/links', editing ? 'PATCH' : 'POST', data); $('#link-dialog').close(); await refresh(); toast('已保存');
}); });
$('#confirm-form').addEventListener('submit', event => { event.preventDefault(); submit(event.currentTarget, async () => { await confirmAction(); $('#confirm-dialog').close(); }); });
$('#category-form').addEventListener('submit', event => { event.preventDefault(); const form = event.currentTarget; submit(form, async () => { await write('/categories','POST',{name:form.elements.name.value,sort_order:(categories.at(-1)?.sort_order || 0) + 10}); form.reset(); await refresh(); renderCategories(); }); });
$('#category-list').addEventListener('click', async event => {
  const b = event.target.closest('[data-cat-action]'); if (!b) return;
  const row = b.closest('[data-cid]'), c = categories.find(c => c.id === Number(row.dataset.cid)), action = b.dataset.catAction;
  try {
    if (action === 'delete') { const targets = categories.filter(x => x.id !== c.id); confirmDialog('删除分类', c.link_count ? `“${c.name}”中有 ${c.link_count} 个网址，请选择迁入分类。` : `删除“${c.name}”？`, async () => { await write('/categories/' + c.id,'DELETE',{move_to:c.link_count ? Number($('#move-target').value) : null}); if (category === c.name) category = ''; await refresh(); renderCategories(); toast('分类已删除'); }, c.link_count ? targets : null); return; }
    if (action === 'save') { const name = row.querySelector('input').value; await write('/categories/'+c.id,'PATCH',{name,sort_order:c.sort_order}); if (category === c.name) category = name; }
    else { const index = categories.indexOf(c), other = categories[index + (action === 'up' ? -1 : 1)]; if (!other) return; const sorted = [...categories]; [sorted[index],sorted[categories.indexOf(other)]] = [other,c]; await write('/categories/reorder','POST',{ids:sorted.map(c => c.id)}); }
    await refresh(); renderCategories(); toast('已保存');
  } catch (err) { $('#categories-dialog .form-error').textContent = err.message; }
});
$('#sections').addEventListener('click', async event => {
  const network = event.target.closest('[data-section-network]');
  if (network) { const y = window.scrollY; sectionNetworks.set(network.dataset.sectionId, network.dataset.sectionNetwork); render(); window.scrollTo({top:y, behavior:'instant'}); return; }
  const sort = event.target.closest('[data-sort-category]');
  if (sort) { await sortLinks(sort, categories.find(c => c.id === Number(sort.dataset.sortCategory))); return; }
  const batch = event.target.closest('[data-batch-category]');
  if (batch) { window.NavBatch.open(categories.find(c => c.id === Number(batch.dataset.batchCategory)), {api,write,refresh,toast,confirm:confirmDialog,categories,groups:window.NavGroups}); return; }
  const add = event.target.closest('[data-add]'); if (add) { openLink(null, add.dataset.add); return; }
  if (event.target.id === 'first-category') { showCategories(); return; }
  if (event.target.closest('[data-clear-filters]')) { $('#search').value = ''; sectionNetworks.clear(); organization = ''; $('#network-filter').value = ''; $('#env-filter').value = ''; document.querySelectorAll('[data-org]').forEach(b => b.classList.toggle('active', b.dataset.org === '')); await refresh(); return; }
  const b = event.target.closest('[data-action]'); if (!b) return; const link = links.find(l => l.key === b.dataset.key); b.closest('details').open = false;
  try {
    if (b.dataset.action === 'edit') openLink(link);
    else if (b.dataset.action === 'move') {
      const targets = categories.filter(c => c.id !== link.category_id);
      if (!targets.length) { toast('请先添加其他分类'); return; }
      confirmDialog('移动至分类', link.name, async () => {
        const target = targets.find(c => c.id === Number($('#move-target').value));
        if (!target) throw new Error('请选择目标分类');
        await write('/links/' + encodeURIComponent(link.key), 'PATCH', {category: target.name});
        await refresh(); toast(`已移至「${target.name}」`);
      }, targets);
    }
    else if (b.dataset.action === 'delete') confirmDialog('删除网址', `删除“${link.name}”？`, async () => { await write('/links/'+encodeURIComponent(link.key),'DELETE',{}); await refresh(); toast('网址已删除'); });
    else if (b.dataset.action === 'pin') { await write('/links/'+encodeURIComponent(link.key),'PATCH',{pinned:!link.pinned}); await refresh(); }
    else { const all = window.NavGroups.entities((await api('/links')).data).filter(l => link.pinned ? l.pinned : !l.pinned && l.category_id === link.category_id), index = all.findIndex(l => l.key === link.key), next = index + (b.dataset.action === 'up' ? -1 : 1); if (next < 0 || next >= all.length) return; await write('/cards/move','POST',{key:link.key,before_key:all[b.dataset.action === 'up' ? next : next+1]?.key || null}); await refresh(); }
  } catch (err) { toast(err.message); }
});
// Sort the complete category contents, including items hidden by search/network filters.
const nameOrder = new Intl.Collator('zh-Hans-CN', {numeric:true, sensitivity:'base'});
async function sortLinks(button, selected = null) {
  button.disabled = true;
  try {
    const [records,groupData] = await Promise.all([api('/links' + (selected ? '?category='+encodeURIComponent(selected.name) : '')),api('/groups')]);
    window.NavGroups.set(groupData.data);
    const all = window.NavGroups.entities(records.data);
    if (all.length < 2) { toast('网址不足 2 个'); return; }
    const compare = (a,b) => nameOrder.compare(a.name,b.name) || a.key.localeCompare(b.key);
    const sorted = [...all.filter(l => l.pinned).sort(compare), ...categories.flatMap(c => all.filter(l => !l.pinned && l.category_id === c.id).sort(compare))];
    await write('/cards/reorder','POST',{keys:sorted.map(l => l.key),complete:true,category_id:selected?.id || null});
    await refresh(); toast('已按名称排序');
  } catch (err) { toast(err.message); } finally { button.disabled = false; }
}
$('#sort-links').onclick = event => sortLinks(event.currentTarget);
let dragging = null;
function cleanDrag() { document.querySelectorAll('.dragging,.drop-before,.drop-zone').forEach(node => node.classList.remove('dragging','drop-before','drop-zone')); }
document.addEventListener('dragstart', event => {
  if ($('#sections').getAttribute('aria-busy') === 'true') { event.preventDefault(); return; }
  const handle = event.target.closest('.drag-handle'), categoryHandle = event.target.closest('.category-drag,[data-category][data-cid]');
  if (handle) {
    const card = handle.closest('.link-card'); dragging = {kind:'link',key:card.dataset.key};
    event.dataTransfer.setDragImage(card, 30, 25);
    requestAnimationFrame(() => card.classList.add('dragging'));
  } else if (categoryHandle) {
    const row = categoryHandle.closest('[data-cid]'); dragging = {kind:'category',id:Number(row.dataset.cid)};
    requestAnimationFrame(() => row.classList.add('dragging'));
  } else { dragging = null; return; }
  event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', JSON.stringify(dragging));
});
document.addEventListener('dragover', event => {
  if (!dragging) return;
  const target = dragging.kind === 'link' ? event.target.closest('#sections section') : event.target.closest('#category-nav [data-cid],#category-list [data-cid]');
  if (!target) return;
  event.preventDefault(); event.dataTransfer.dropEffect = 'move'; cleanDrag();
  if (dragging.kind === 'link') {
    const card = event.target.closest('.link-card');
    (card || target).classList.add(card ? 'drop-before' : 'drop-zone');
  } else target.classList.add('drop-before');
});
document.addEventListener('drop', async event => {
  const source = dragging; dragging = null; cleanDrag();
  if (!source) return;
  try {
    if (source.kind === 'link') {
      const target = event.target.closest('#sections section'); if (!target) return;
      event.preventDefault();
      const card = event.target.closest('.link-card'), pinned = target.dataset.section === 'pinned';
      if (card?.dataset.key === source.key) return;
      await write('/cards/move','POST',{key:source.key,before_key:card?.dataset.key || null,pinned,...(pinned ? {} : {category_id:Number(target.dataset.section)})});
    } else {
      const target = event.target.closest('#category-nav [data-cid],#category-list [data-cid]'); if (!target) return;
      event.preventDefault(); const cid = Number(target.dataset.cid); if (cid === source.id) return;
      const ids = categories.map(c => c.id).filter(id => id !== source.id); ids.splice(ids.indexOf(cid),0,source.id);
      await write('/categories/reorder','POST',{ids});
    }
    await refresh(); if ($('#categories-dialog').open) renderCategories(); toast('顺序已保存');
  } catch (err) { toast(err.message); }
});
document.addEventListener('dragend', () => { dragging = null; cleanDrag(); });
$('#category-nav').addEventListener('click', event => { const b=event.target.closest('[data-category]'); if(b){category=b.dataset.category;refresh();} });
$('#org-tabs').addEventListener('click', event => { const b=event.target.closest('[data-org]'); if(b){organization=b.dataset.org;document.querySelectorAll('[data-org]').forEach(x=>x.classList.toggle('active',x===b));refresh();} });
let debounce, composing = false;
$('#search').addEventListener('compositionstart', () => { composing = true; clearTimeout(debounce); });
$('#search').addEventListener('compositionend', () => { composing = false; scheduleSearch(); });
function scheduleSearch() { clearTimeout(debounce); searchChoice = null; suggestionsWanted = true; updateSearchSuggestions(); if (!composing) debounce = setTimeout(refresh, 160); }
$('#search').addEventListener('input', scheduleSearch);
function chosenSearch() { return searchChoice || (lastSearchQuery === localQuery() && lastSearchCount === 0 ? 'web' : 'local'); }
function hideSearchSuggestions() { $('#search-suggestions').hidden = true; $('#search').setAttribute('aria-expanded','false'); $('#search').removeAttribute('aria-activedescendant'); }
function updateSearchSuggestions() {
  const query = localQuery().trim();
  if (!suggestionsWanted || !query || !$('#search-form').contains(document.activeElement)) { hideSearchSuggestions(); return; }
  const choice = chosenSearch(), ready = lastSearchQuery === localQuery();
  $('#search-local-label').textContent = ready ? `导航中查找 · ${lastSearchCount} 个网址` : '导航中查找';
  $('#search-web-label').textContent = `百度搜索“${query}”`;
  document.querySelectorAll('[data-search-choice]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.searchChoice === choice)));
  $('#search-suggestions').hidden = false; $('#search').setAttribute('aria-expanded','true');
  $('#search').setAttribute('aria-activedescendant', choice === 'web' ? 'search-web-option' : 'search-local-option');
}
function runSearch(choice) { suggestionsWanted = false; clearTimeout(debounce); hideSearchSuggestions(); if (choice === 'web') webSearch(); else refresh(); }
$('#search').addEventListener('focus', () => { suggestionsWanted = true; updateSearchSuggestions(); });
$('#search').addEventListener('keydown', event => {
  if (composing || event.isComposing) return;
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); suggestionsWanted = true; searchChoice = chosenSearch() === 'local' ? 'web' : 'local'; updateSearchSuggestions(); }
  if (event.key === 'Escape') { event.preventDefault(); suggestionsWanted = false; hideSearchSuggestions(); }
});
$('#search-suggestions').addEventListener('click', event => { const b = event.target.closest('[data-search-choice]'); if (b) runSearch(b.dataset.searchChoice); });
$('#search-form').addEventListener('focusout', () => setTimeout(() => { if (!$('#search-form').contains(document.activeElement)) hideSearchSuggestions(); }, 0));
$('#search-form').addEventListener('submit', event => {
  event.preventDefault();
  if (composing) return;
  runSearch(chosenSearch());
});
function updateThemeChoices() {
  document.querySelectorAll('[data-theme-choice]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === window.NavTheme.get()));
  });
}
document.querySelectorAll('[data-open-themes]').forEach(button => button.onclick = () => { const picker = button.closest('.theme-picker'); const panel = picker.querySelector('.theme-choices'); const open = panel.hidden; document.querySelectorAll('.theme-choices').forEach(p => p.hidden = true); document.querySelectorAll('[data-open-themes]').forEach(b => b.setAttribute('aria-expanded','false')); panel.hidden = !open; button.setAttribute('aria-expanded', String(open)); updateThemeChoices(); });
document.addEventListener('click', event => {
  const button = event.target.closest('[data-theme-choice]');
  if (button) window.NavTheme.set(button.dataset.themeChoice);
  document.querySelectorAll('.theme-picker').forEach(p => { if (!p.contains(event.target)) { p.querySelector('.theme-choices').hidden = true; p.querySelector('[data-open-themes]').setAttribute('aria-expanded','false'); } });
  if (!$('#search-form').contains(event.target)) { suggestionsWanted = false; hideSearchSuggestions(); }
});
document.addEventListener('nav-theme-change', updateThemeChoices);
document.addEventListener('keydown', event => { if (event.key === 'Escape') { document.querySelectorAll('.theme-choices').forEach(p => p.hidden = true); document.querySelectorAll('[data-open-themes]').forEach(b => b.setAttribute('aria-expanded','false')); } });
document.addEventListener('load', event => { if (event.target.matches?.('img[data-favicon]')) event.target.closest('.site-icon').classList.add('has-favicon'); }, true);
document.addEventListener('error', event => { if (event.target.matches?.('img[data-favicon]')) event.target.remove(); }, true);
$('#network-filter').onchange=refresh;$('#env-filter').onchange=refresh;$('#retry-load').onclick=refresh;
$('#add-link').onclick=()=>openLink();$('#manage-categories').onclick=showCategories;$('#mobile-categories').onclick=showCategories;
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
document.addEventListener('keydown',event=>{if(event.key==='/'&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)&&!document.querySelector('dialog[open]')&&!$('#app-view').hidden){event.preventDefault();$('#search').focus();}});
document.addEventListener('click',event=>document.querySelectorAll('details.menu[open]').forEach(d=>{if(!d.contains(event.target))d.open=false;}));
document.addEventListener('click',event=>{const b=event.target.closest('.menu-panel button');if(b)b.closest('details').open=false;});
$('#logout').onclick=async()=>{try{await write('/auth/logout','POST',{});csrf='';links=[];$('#sections').replaceChildren();showLogin();}catch(err){toast(err.message);}};
$('#export').onclick=async()=>{try{const data=await api('/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`导航-${new Date().toISOString().slice(0,10)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(err){toast(err.message);}};
$('#import').onclick=()=>$('#import-file').click();
$('#import-file').onchange=async event=>{const file=event.target.files[0];event.target.value='';if(!file)return;try{if(file.size>4*1024*1024)throw new Error('文件超过 4 MB');const data=JSON.parse(await file.text());if(![1,2].includes(data.version)||!Array.isArray(data.links)||!Array.isArray(data.categories))throw new Error('请选择本站导出的 JSON 文件');confirmDialog('导入数据',`${data.categories.length} 个分类、${data.links.length} 个网址。同一标识的记录将按文件更新，包括分类、置顶、图标和排序；其余记录保留。`,async()=>{const r=await write('/import','POST',data);await refresh();toast(`已新增 ${r.data.created} 条，更新 ${r.data.updated} 条`);});}catch(err){toast(err instanceof SyntaxError?'文件不是有效的 JSON':err.message);}};
window.NavGroups.init({api,write,refresh,toast,confirm:confirmDialog,edit:openLink,categories:()=>categories});
(async()=>{try{const r=await api('/auth/me');csrf=r.data.csrf;await enter();}catch{showLogin();}})();
