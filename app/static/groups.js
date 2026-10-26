'use strict';
(() => {
  const $ = s => document.querySelector(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let groups = [], owners = new Map(), actions, editing = null, choices = [], selected = [], saving = false;
  const expanded = new Set(), dialog = $('#group-dialog'), form = $('#group-form');
  function entities(items) {
    const result = [], seen = new Set();
    for (const link of items) {
      const group = owners.get(link.key);
      if (!group) { result.push(link); continue; }
      if (seen.has(group.key)) continue;
      seen.add(group.key);
      result.push({...group, key:'group:'+group.key, groupKey:group.key, members:group.keys.map(key=>items.find(l=>l.key===key)).filter(Boolean)});
    }
    return result.sort((a,b)=>a.sort_order-b.sort_order || a.key.localeCompare(b.key));
  }
  const entryIcon = path => `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="${path}"/></svg>`;
  function groupCard(g) {
    const id = esc(g.groupKey), open = expanded.has(g.groupKey);
    return `<article class="link-card group-card" data-key="group:${id}" data-group="${id}"><button type="button" class="drag-handle" draggable="true" aria-label="拖动 ${esc(g.name)}" title="拖动排序">⠿</button><button type="button" class="card-main group-main" data-group-toggle="${id}" aria-expanded="${open}"><span class="site-icon">${esc(g.icon || '▦')}</span><span class="card-copy"><h3 title="${esc(g.name)}">${esc(g.name)}</h3><p>${g.members.length === g.keys.length ? g.members.length : g.members.length+' / '+g.keys.length} 个地址</p><span class="badges">${[...new Set(g.members.map(l=>l.network))].map(n=>`<span class="badge">${n==='lan'?'内网':'公网'}</span>`).join('')}<span data-group-chevron aria-hidden="true">${open?'⌃':'⌄'}</span></span></span></button><details class="menu card-menu"><summary aria-label="管理 ${esc(g.name)}">•••</summary><div class="menu-panel">${[['edit','编辑聚合'],['move','移动至分类'],['pin',g.pinned?'取消置顶':'置顶'],['up','上移'],['down','下移'],['dissolve','拆分聚合']].map(([a,label])=>`<button type="button" data-group-action="${a}" data-group-id="${id}">${label}</button>`).join('')}</div></details><div class="group-addresses" ${open?'':'hidden'}>${g.members.map(l=>`<div class="group-address" data-member="${esc(l.key)}"><a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer"><span title="${esc(l.name)}">${esc(l.name)}</span><small>${l.network==='lan'?'内网':'公网'}${l.environment==='none'?'':' · '+(l.environment==='test'?'测试':'生产')}</small></a><button type="button" data-group-entry-edit="${esc(l.key)}" title="编辑网址" aria-label="编辑 ${esc(l.name)}">${entryIcon('M14 5l5 5M4 20l4-1L20 7a2.1 2.1 0 0 0-3-3L5 16z')}</button><button type="button" data-group-detach="${esc(l.key)}" data-group-id="${id}" title="移出聚合" aria-label="将 ${esc(l.name)} 移出聚合">${entryIcon('M10 5H5v14h5M10 12h11m-4-4 4 4-4 4')}</button></div>`).join('')}</div></article>`;
  }
  function drawChoices() {
    const order = [...selected, ...choices.filter(l=>!selected.includes(l.key)).map(l=>l.key)];
    $('#group-choices').innerHTML = order.map(key=>{
      const link = choices.find(l=>l.key===key), i=selected.indexOf(key);
      return `<div class="group-choice" data-choice="${esc(key)}"><label><input type="checkbox" data-group-select="${esc(key)}" ${i>=0?'checked':''}><span>${esc(link.name)}</span></label><button type="button" data-group-order="up" data-choice="${esc(key)}" aria-label="上移 ${esc(link.name)}" ${i<=0?'disabled':''}>↑</button><button type="button" data-group-order="down" data-choice="${esc(key)}" aria-label="下移 ${esc(link.name)}" ${i<0||i===selected.length-1?'disabled':''}>↓</button></div>`;
    }).join('');
    $('#group-selected-count').textContent = `已选 ${selected.length} 个地址`;
  }
  async function open(group, keys=[]) {
    editing = group; selected = [...(group?.keys || keys)];
    const links = (await actions.api('/links')).data;
    const cid = group?.category_id || links.find(l=>l.key===keys[0])?.category_id;
    if (!cid) throw new Error('所选网址已变化，请刷新后重试');
    if (!group && selected.some(key=>owners.has(key))) throw new Error('所选网址已属于聚合，请先移出');
    choices = links.filter(l=>l.category_id===cid && (!owners.has(l.key)||owners.get(l.key).key===group?.key));
    if (selected.some(key=>!choices.some(l=>l.key===key))) throw new Error('只能聚合同一分类的网址');
    $('#group-title').textContent = group?'编辑聚合':'聚合网址';
    $('#group-name').value = group?.name || '';
    $('#group-icon').value = group?.icon || '';
    $('#group-category-name').textContent = choices[0]?.category || '';
    form.querySelector('.form-error').textContent = ''; drawChoices(); dialog.showModal(); $('#group-name').focus();
  }
  $('#group-choices').addEventListener('change',event=>{
    const input=event.target.closest('[data-group-select]');if(!input||saving)return;
    selected=selected.filter(k=>k!==input.dataset.groupSelect);if(input.checked)selected.push(input.dataset.groupSelect);drawChoices();
  });
  $('#group-choices').addEventListener('click',event=>{
    const button=event.target.closest('[data-group-order]');if(!button||saving)return;
    const i=selected.indexOf(button.dataset.choice),j=i+(button.dataset.groupOrder==='up'?-1:1);
    if(i>=0&&j>=0&&j<selected.length){[selected[i],selected[j]]=[selected[j],selected[i]];drawChoices();}
  });
  dialog.addEventListener('cancel',event=>{if(saving)event.preventDefault();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(saving)return;
    if(selected.length<(editing?1:2)){form.querySelector('.form-error').textContent=editing?'请保留至少一个网址，或拆分聚合':'请选择至少两个网址';return;}
    saving=true;form.querySelectorAll('button,input').forEach(el=>el.disabled=true);
    try{await actions.write(editing?'/groups/'+encodeURIComponent(editing.key):'/groups',editing?'PATCH':'POST',{name:$('#group-name').value,icon:$('#group-icon').value,keys:selected});dialog.close();await actions.refresh();actions.toast('聚合已保存');}
    catch(error){form.querySelector('.form-error').textContent=error.message;}
    finally{saving=false;form.querySelectorAll('button,input').forEach(el=>el.disabled=false);drawChoices();}
  });
  document.addEventListener('click',async event=>{
    try{
      const toggle=event.target.closest('[data-group-toggle]');
      if(toggle){const key=toggle.dataset.groupToggle,open=!expanded.has(key);if(open)expanded.add(key);else expanded.delete(key);toggle.setAttribute('aria-expanded',String(open));toggle.querySelector('[data-group-chevron]').textContent=open?'⌃':'⌄';toggle.closest('.group-card').querySelector('.group-addresses').hidden=!open;return;}
      const edit=event.target.closest('[data-group-entry-edit]');
      if(edit){const link=(await actions.api('/links/'+encodeURIComponent(edit.dataset.groupEntryEdit))).data;actions.edit(link);return;}
      const detach=event.target.closest('[data-group-detach]');
      if(detach){await actions.write('/groups/'+encodeURIComponent(detach.dataset.groupId)+'/members/'+encodeURIComponent(detach.dataset.groupDetach),'DELETE',{});await actions.refresh();actions.toast('已移出聚合');return;}
      const button=event.target.closest('[data-group-action]');if(!button)return;
      button.closest('details').open=false;
      const group=groups.find(g=>g.key===button.dataset.groupId);if(!group)return;
      const path='/groups/'+encodeURIComponent(group.key),action=button.dataset.groupAction;
      if(action==='edit'){await open(group);return;}
      if(action==='dissolve'){actions.confirm('拆分聚合',`拆分“${group.name}”，保留全部网址。`,async()=>{await actions.write(path,'DELETE',{});await actions.refresh();actions.toast('已拆分聚合');});return;}
      if(action==='move'){
        const targets=actions.categories().filter(c=>c.id!==group.category_id);
        if(!targets.length){actions.toast('请先添加其他分类');return;}
        actions.confirm('移动至分类',group.name,async()=>{await actions.write(path,'PATCH',{category_id:Number($('#move-target').value)});await actions.refresh();actions.toast('聚合已移动');},targets);return;
      }
      if(action==='pin')await actions.write(path,'PATCH',{pinned:!group.pinned});
      else{
        const all=entities((await actions.api('/links')).data).filter(l=>group.pinned?l.pinned:!l.pinned&&l.category_id===group.category_id),i=all.findIndex(l=>l.key==='group:'+group.key),next=i+(action==='up'?-1:1);
        if(next<0||next>=all.length)return;
        await actions.write('/cards/move','POST',{key:'group:'+group.key,before_key:all[action==='up'?next:next+1]?.key||null});
      }
      await actions.refresh();
    }catch(error){actions?.toast(error.message);}
  });
  window.NavGroups={
    init(value){actions=value;},
    set(value){groups=value;owners=new Map(groups.flatMap(g=>g.keys.map(key=>[key,g])));},
    pinned(link){return owners.get(link.key)?.pinned ?? link.pinned;},
    entities,
    render(items,renderLink){return entities(items).map(item=>item.groupKey?groupCard(item):renderLink(item)).join('');},
    async create(keys){await open(null,keys);}
  };
})();
