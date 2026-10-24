'use strict';
(() => {
  const dialog = document.querySelector('#batch-dialog'), form = document.querySelector('#batch-form');
  const list = document.querySelector('#batch-list'), selectAll = document.querySelector('#batch-select-all');
  const operation = document.querySelector('#batch-operation'), target = document.querySelector('#batch-target');
  const apply = document.querySelector('#batch-apply'), save = document.querySelector('#batch-save');
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let actions, category, records = [], busy = false, generation = 0;
  const selected = () => [...list.querySelectorAll('.batch-row')].filter(row => row.querySelector('[data-select]').checked);
  function controls() {
    const count = selected().length;
    document.querySelector('#batch-selected-count').textContent = `已选 ${count}`;
    selectAll.checked = records.length > 0 && count === records.length;
    selectAll.indeterminate = count > 0 && count < records.length;
    selectAll.disabled = busy || !records.length;
    apply.disabled = busy || !count || !operation.value;
    save.disabled = busy || !count;
    target.hidden = operation.value !== 'move';
    for (const row of list.querySelectorAll('.batch-row')) {
      const checked = row.querySelector('[data-select]').checked;
      row.querySelector('[data-select]').disabled = busy;
      row.querySelectorAll('[data-field]').forEach(input => input.disabled = busy || !checked);
    }
    form.querySelectorAll('.close-dialog').forEach(button => button.disabled = busy);
  }
  async function load() {
    const id = ++generation;
    const response = await actions.api('/links?category=' + encodeURIComponent(category.name));
    if (id !== generation || !dialog.open) return;
    records = response.data;
    list.innerHTML = records.map(link => `<div class="batch-row" data-key="${escape(link.key)}"><input type="checkbox" data-select aria-label="选择 ${escape(link.name)}"><input data-field="name" value="${escape(link.name)}" aria-label="名称 ${escape(link.name)}" maxlength="120" required disabled><input data-field="url" type="url" value="${escape(link.url)}" aria-label="网址 ${escape(link.name)}" maxlength="2048" required disabled><input data-field="description" value="${escape(link.description)}" aria-label="说明 ${escape(link.name)}" maxlength="500" disabled></div>`).join('') || '<div class="batch-empty">这个分类暂无网址</div>';
    controls();
  }
  function payload() {
    return selected().map(row => {
      const original = records.find(link => link.key === row.dataset.key), item = {key: original.key};
      row.querySelectorAll('[data-field]').forEach(input => { if (input.value !== original[input.dataset.field]) item[input.dataset.field] = input.value; });
      return item;
    });
  }
  function error(err) { form.querySelector('.form-error').textContent = err.message; }
  async function commit(action, items, categoryId) {
    busy = true; controls(); form.querySelector('.form-error').textContent = '';
    try {
      await actions.write('/links/batch', 'POST', {items, operation: action, ...(categoryId ? {category_id: categoryId} : {})});
      await actions.refresh(); await load();
      actions.toast(action === 'delete' ? '所选网址已删除' : '已保存');
    } finally { busy = false; controls(); }
  }
  form.addEventListener('submit', event => {
    event.preventDefault(); if (!selected().length || busy) return;
    commit('update', payload()).catch(error);
  });
  apply.onclick = () => {
    if (!selected().length || busy || !operation.value) return;
    const action = operation.value, items = action === 'delete' ? payload().map(({key}) => ({key})) : payload(), categoryId = Number(target.value);
    if (action !== 'delete' && !form.reportValidity()) return;
    if (action === 'move' && !categoryId) { error(new Error('请选择目标分类')); return; }
    if (action === 'delete') {
      actions.confirm('删除所选网址', `删除所选的 ${items.length} 个网址？`, () => commit(action, items));
    } else commit(action, items, action === 'move' ? categoryId : null).catch(error);
  };
  selectAll.onchange = () => { list.querySelectorAll('[data-select]').forEach(input => input.checked = selectAll.checked); controls(); };
  list.addEventListener('change', controls);
  operation.onchange = controls;
  dialog.addEventListener('close', () => { ++generation; });
  window.NavBatch = {
    async open(value, dependencies) {
      category = value; actions = dependencies; records = []; operation.value = ''; form.querySelector('.form-error').textContent = '';
      document.querySelector('#batch-category').textContent = value.name;
      target.innerHTML = '<option value="">选择分类</option>' + dependencies.categories.filter(c => c.id !== value.id).map(c => `<option value="${c.id}">${escape(c.name)}</option>`).join('');
      list.innerHTML = '<div class="batch-empty">正在加载…</div>'; controls(); dialog.showModal();
      try { await load(); } catch (err) { error(err); }
    }
  };
})();
