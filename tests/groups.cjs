/* Destructive scenarios run only against a disposable database. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');const assert=require('node:assert/strict'),fs=require('fs');
if(process.env.NAV_GROUPS_ISOLATED!=='1')throw new Error('聚合回归必须使用隔离数据库');
const base=process.env.NAV_TEST_URL,token=process.env.NAV_TEST_API_TOKEN||'preview-only-token-not-for-production-20261024',password=process.env.NAV_TEST_PASSWORD||'测试专用密码-20261024';
const checks=[],keys=['qa-group-a','qa-group-b','qa-group-c','qa-group-d'];let cats=[],group;
async function api(path,method='GET',data){const r=await fetch(base+'/api/v1'+path,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const d=await r.json();assert.ok(r.ok,r.status+' '+JSON.stringify(d));return d.data||d;}
async function check(name,fn){await fn();checks.push(name);console.log('PASS',name);}
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});const context=await b.newContext({viewport:{width:1440,height:1100}}),p=await context.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));
const groupCard=()=>p.locator('.group-card');const menu=async action=>{await groupCard().locator('summary').click();await groupCard().locator('[data-group-action='+action+']').click();};
const groupState=async()=>{const rows=await api('/groups');assert.equal(rows.length,1);return rows[0];};
try{
 for(const name of ['聚合来源','聚合目标','拖动目标'])cats.push(await api('/categories','POST',{name,sort_order:99000+cats.length}));
 for(let i=0;i<4;i++)await api('/links/upsert','POST',{key:keys[i],name:['生产公网入口','测试内网入口','第三个入口','独立网址'][i],url:'http://127.0.0.1:'+new URL(base).port+'/?entry='+i,category:cats[i===3?1:0].name,pinned:i===1,icon:'测',network:i===1?'lan':'public',environment:i===1?'test':'production',sort_order:10*i});
 await p.goto(base);await p.locator('[name=password]').fill(password);await p.locator('#login-form button').click();await p.locator('.link-card').first().waitFor();
 await check('分类批量选择两个网址创建单层聚合',async()=>{
  await p.locator('[data-batch-category="'+cats[0].id+'"]').click();
  for(const key of keys.slice(0,2))await p.locator('.batch-row[data-key="'+key+'"] [data-select]').check();
  await p.locator('#batch-operation').selectOption('group');await p.locator('#batch-apply').click();await p.locator('#group-dialog').waitFor({state:'visible'});
  await p.locator('#group-name').fill('应用聚合');await p.locator('#group-icon').fill('聚');await p.locator('#group-form button[type=submit]').click();await p.locator('#group-dialog').waitFor({state:'hidden'});await groupCard().waitFor();group=await groupState();assert.deepEqual(group.keys,keys.slice(0,2));assert.equal(await p.locator('.link-card').count(),3);
 });
 await check('展开后实际入口可访问，显示网络和环境',async()=>{await groupCard().locator('[data-group-toggle]').click();assert.equal(await groupCard().locator('.group-address:visible').count(),2);assert.equal(await groupCard().locator('.group-address').nth(1).locator('small').textContent(),'内网 · 测试');const link=groupCard().locator('.group-address a').first();assert.equal(await link.getAttribute('target'),'_blank');assert.ok((await link.getAttribute('rel')).includes('noopener'));});
 await check('修改名称与图标、添加成员、调整入口顺序并刷新保留',async()=>{
  await menu('edit');await p.locator('#group-name').fill('应用聚合改名');await p.locator('[data-group-select="'+keys[2]+'"]').check();
  await p.locator('[data-group-order=up][data-choice="'+keys[2]+'"]').click();await p.locator('[data-group-order=up][data-choice="'+keys[2]+'"]').click();
  await p.locator('#group-form button[type=submit]').click();await p.locator('#group-dialog').waitFor({state:'hidden'});await p.reload();await groupCard().waitFor();group=await groupState();assert.deepEqual(group.keys,[keys[2],keys[0],keys[1]]);assert.equal(group.name,'应用聚合改名');
 });
 await check('按聚合名、成员名和中文搜索，内外网筛选只显示匹配入口',async()=>{
  await p.locator('#search').fill('应用聚合改名');await p.waitForFunction(()=>document.querySelectorAll('.link-card').length===1);assert.equal(await groupCard().locator('.group-address').count(),3);
  await p.locator('#search').fill('测试内网入口');await p.waitForFunction(()=>document.querySelectorAll('.group-address').length===1);assert.equal(await groupCard().locator('.group-address small').textContent(),'内网 · 测试');
  await p.locator('#search').fill('');await p.locator('#network-filter').selectOption('lan');await p.waitForFunction(()=>document.querySelectorAll('.group-address').length===1);
  await p.locator('#network-filter').selectOption('');await p.waitForFunction(()=>document.querySelectorAll('.group-address').length===3);
 });
 await check('聚合整体置顶，原始入口置顶和图标保持',async()=>{await menu('pin');await p.locator('section[data-section=pinned] .group-card').waitFor();assert.equal((await api('/links/'+keys[1])).pinned,true);await menu('pin');await p.waitForFunction(()=>!document.querySelector('section[data-section=pinned] .group-card'));});
 await check('自动登记更新成员地址仍保留聚合与人工显示属性',async()=>{await api('/links/upsert','POST',{key:keys[0],name:'更新后的入口',url:base+'/?new-address=1'});await p.reload();await groupCard().waitFor();assert.equal((await groupState()).keys.length,3);assert.equal((await api('/links/'+keys[0])).icon,'测');});
 await check('编辑成员所属分类会自动移出聚合，其他成员保留',async()=>{
  await groupCard().locator('[data-group-toggle]').click();await groupCard().locator('[data-group-entry-edit="'+keys[0]+'"]').click();await p.locator('#link-form [name=category]').selectOption(cats[1].name);await p.locator('#link-form button[type=submit]').click();await p.locator('#link-dialog').waitFor({state:'hidden'});assert.deepEqual((await groupState()).keys,[keys[2],keys[1]]);
 });
 await check('移动整张聚合卡，所有成员随同移动分类',async()=>{await menu('move');await p.locator('#move-target').selectOption(String(cats[1].id));await p.locator('#confirm-submit').click();await p.locator('#confirm-dialog').waitFor({state:'hidden'});group=await groupState();assert.equal(group.category_id,cats[1].id);for(const key of group.keys)assert.equal((await api('/links/'+key)).category_id,cats[1].id);});
 await check('聚合参与分类名称排序与真实鼠标拖动',async()=>{
  await p.locator('[data-sort-category="'+cats[1].id+'"]').click();await p.waitForFunction(()=>document.body.textContent.includes('已按名称排序'));
  const section=p.locator('section[data-section="'+cats[1].id+'"]');const names=await section.locator('.card-copy h3').allTextContents();assert.deepEqual(names,[...names].sort(new Intl.Collator('zh-Hans-CN',{numeric:true}).compare));
  await groupCard().hover();await groupCard().locator('.drag-handle').dragTo(p.locator('.link-card[data-key="'+keys[3]+'"]'),{targetPosition:{x:10,y:35}});
  await p.waitForFunction(()=>document.querySelector('#sections').getAttribute('aria-busy')==='false');
  for(let i=0;i<50;i++){if((await groupState()).sort_order<(await api('/links/'+keys[3])).sort_order)break;await p.waitForTimeout(50);}
  assert.ok((await groupState()).sort_order<(await api('/links/'+keys[3])).sort_order);
  await groupCard().hover();await groupCard().locator('.drag-handle').dragTo(p.locator('section[data-section="'+cats[2].id+'"] .section-head'));
  for(let i=0;i<50;i++){if((await groupState()).category_id===cats[2].id)break;await p.waitForTimeout(50);}
  assert.equal((await groupState()).category_id,cats[2].id);
 });
 await check('移出成员后保留网址，单成员聚合可以导出恢复',async()=>{
  if(await groupCard().locator('.group-addresses').isHidden())await groupCard().locator('[data-group-toggle]').click();
  await groupCard().locator('[data-group-detach="'+keys[1]+'"]').click();await p.waitForFunction(()=>document.querySelectorAll('.group-address').length===1);assert.deepEqual((await groupState()).keys,[keys[2]]);
  const exported=await api('/export');assert.equal(exported.version,2);assert.equal(exported.groups.length,1);
  await menu('dissolve');await p.locator('#confirm-submit').click();await p.locator('#confirm-dialog').waitFor({state:'hidden'});await groupCard().waitFor({state:'detached'});assert.equal((await api('/links')).length,4);
  await p.locator('#import-file').setInputFiles({name:'group-export.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(exported))});await p.locator('#confirm-dialog').waitFor({state:'visible'});await p.locator('#confirm-submit').click();await p.locator('#confirm-dialog').waitFor({state:'hidden'});await groupCard().waitFor();assert.deepEqual((await groupState()).keys,[keys[2]]);
 });
 await check('手机磨砂主题菜单可点击，展开与弹窗无横向溢出',async()=>{
  await p.setViewportSize({width:390,height:1000});await p.evaluate(()=>window.NavTheme.set('glass'));await groupCard().locator('summary').click();for(const action of ['edit','move','pin','up','down','dissolve'])await groupCard().locator('[data-group-action='+action+']').click({trial:true});await groupCard().locator('[data-group-action=edit]').click();assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await p.locator('#group-dialog .close-dialog').first().click();
 });
 assert.deepEqual(errors,[]);fs.writeFileSync('artifacts/groups-browser-results.json',JSON.stringify({checks,errors},null,2));console.log('GROUP_CHECKS',checks.length);
}finally{await b.close();for(const key of keys){try{await api('/links/'+key,'DELETE');}catch{}}for(const cat of cats){try{await api('/categories/'+cat.id,'DELETE',{});}catch{}}}})().catch(e=>{console.error(e.stack);process.exit(1)});
