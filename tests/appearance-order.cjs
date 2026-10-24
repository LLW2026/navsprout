/* Real browser/API acceptance. Only disposable categories/links are reordered. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.resolve(__dirname,'..');
const isolated = process.env.NAV_ORDER_ISOLATED === '1';
const vars = isolated ? {NAV_USERNAME:'admin', NAV_API_TOKEN:process.env.NAV_TEST_API_TOKEN || 'preview-only-token-not-for-production-20261024'} : Object.fromEntries(fs.readFileSync(path.join(root,'.env'),'utf8').split('\n').filter(l=>l&&!l.startsWith('#')).map(l=>{const i=l.indexOf('=');return [l.slice(0,i),l.slice(i+1).replace(/^'|'$/g,'')];}));
const password = isolated ? (process.env.NAV_TEST_PASSWORD || '测试专用密码-20261024') : fs.readFileSync(path.join(process.env.HOME,'.config/navsprout/admin-password.txt'),'utf8').trim();
const base = process.env.NAV_TEST_URL || 'http://192.168.1.10:8866';
const prefix = '排序验收'+Date.now(), keys = [0,1,2,3,4].map(i=>'qa-order-'+Date.now()+'-'+i);
const artifact = suffix => path.join(root,'artifacts',(process.env.NAV_TEST_ARTIFACT_PREFIX || 'appearance-order')+suffix);
const checks=[], errors=[], cats=[], externalRequests=[];
async function api(route,method='GET',body) {
 const r=await fetch(base+'/api/v1'+route,{method,headers:{Authorization:'Bearer '+vars.NAV_API_TOKEN,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await r.json(); assert.ok(r.ok,'API '+r.status+' '+JSON.stringify(data));return data.data || data;
}
async function snapshot(){const data=await api('/export');delete data.exported_at;return data;}
async function check(name,fn){await fn();checks.push(name);console.log('PASS',name);}
async function until(fn){for(let i=0;i<100;i++){if(await fn())return;await new Promise(r=>setTimeout(r,50));}throw new Error('等待保存结果超时');}
(async()=>{
 const before=await snapshot();
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}), page=await context.newPage();
 page.on('pageerror',error=>errors.push(error.message));page.on('request',r=>{if(new URL(r.url()).origin!==new URL(base).origin)externalRequests.push(r.url());});
 await page.clock.install();
 await page.addInitScript(()=>{window.__dragEvents=[];for(const name of ['dragstart','drop','dragend'])document.addEventListener(name,event=>window.__dragEvents.push({type:event.type,tag:event.target.tagName,cls:event.target.className,key:event.target.closest('[data-key]')?.dataset.key,section:event.target.closest('[data-section]')?.dataset.section}),true);});
 const card=i=>page.locator('.link-card[data-key="'+keys[i]+'"]');
 try {
  const maxOrder=Math.max(-10,...before.categories.map(c=>c.sort_order));
  for(let i=0;i<2;i++)cats.push(await api('/categories','POST',{name:prefix+'-'+i,sort_order:maxOrder+(i+1)*10}));
  const names=['香蕉10','苹果10','苹果2','阿尔法','测试归档'];
  for(let i=0;i<5;i++)await api('/links','POST',{key:keys[i],name:names[i],url:'https://example.com/qa-order/'+i,category:cats[0].name,sort_order:i*10,icon:'◆',network:i===4?'lan':'public'});
  await page.goto(base);await page.locator('#login-view').waitFor({state:'visible'});
  await page.locator('[name=password]').fill(password);await page.locator('#login-form button').click();
  await page.locator('#category-nav [data-cid="'+cats[0].id+'"]').waitFor();
  await page.locator('#category-nav [data-cid="'+cats[0].id+'"]').click();await card(4).waitFor();
  await check('登录和侧栏标题使用本站 favicon',async()=>{
   assert.equal(await page.locator('.brand .brand-mark').getAttribute('src'),'/favicon.ico');
   assert.ok(await page.locator('.brand .brand-mark').evaluate(img=>img.complete&&img.naturalWidth>0));
  });
  await check('全局排序收进设置菜单，每个分类有批量编辑与排序图标',async()=>{
   assert.equal(await page.locator('#sort-links').isVisible(),false);
   await page.locator('.top-actions summary[aria-label="设置"]').click();await page.locator('#sort-links').waitFor({state:'visible'});
   if(isolated){await page.locator('#sort-links').click();await page.waitForFunction(()=>!document.querySelector('#sort-links').disabled);assert.equal((await api('/links'))[0].key,keys[3]);}
   else await page.locator('.top-actions summary[aria-label="设置"]').click();
   for(const c of cats){const section=page.locator('section[data-section="'+c.id+'"]');if(await section.count()){assert.equal(await section.locator('[data-batch-category]').count(),1);assert.equal(await section.locator('[data-sort-category]').count(),1);assert.equal(await section.locator('.section-add').count(),1);}}
  });
  await check('列表刷新期间取消旧卡片拖动，保存结果保持完整',async()=>{
   const orderBefore=(await api('/links?category='+encodeURIComponent(cats[0].name))).map(l=>l.key);
   let release;const gate=new Promise(resolve=>release=resolve);
   await page.route('**/api/v1/links?*',async route=>{await gate;await route.continue();},{times:1});
   await page.locator('#category-nav [data-cid="'+cats[0].id+'"]').click();await page.locator('#sections[aria-busy=true]').waitFor();
   try {await card(0).hover();await card(0).locator('.drag-handle').dragTo(card(3));}finally{release();}
   await page.locator('#sections[aria-busy=false]').waitFor();
   assert.deepEqual((await api('/links?category='+encodeURIComponent(cats[0].name))).map(l=>l.key),orderBefore);
  });
  await check('一键按中文名称与数字顺序排序，刷新保留',async()=>{
   await page.locator('[data-sort-category="'+cats[0].id+'"]').click();
   await until(async()=> (await api('/links?category='+encodeURIComponent(cats[0].name))).map(l=>l.key).join() === [keys[3],keys[4],keys[2],keys[1],keys[0]].join());
   await page.reload();await card(0).waitFor();
   assert.deepEqual(await page.locator('section[data-section="'+cats[0].id+'"] .link-card').evaluateAll(nodes=>nodes.map(n=>n.dataset.key)),[keys[3],keys[4],keys[2],keys[1],keys[0]]);
  });
  await check('原生鼠标拖动卡片排序并真实写库',async()=>{
   await card(0).hover();await card(0).locator('.drag-handle').dragTo(card(3),{targetPosition:{x:8,y:40}});
   await until(async()=> (await api('/links?category='+encodeURIComponent(cats[0].name)))[0].key===keys[0]);
   await page.reload();await card(0).waitFor();assert.equal(await page.locator('section[data-section="'+cats[0].id+'"] .link-card').first().getAttribute('data-key'),keys[0]);
  });
  await check('筛选后拖动保留隐藏网址及其相对位置',async()=>{
   await page.locator('section[data-section="'+cats[0].id+'"] [data-section-network=public]').click();await card(4).waitFor({state:'hidden'});
   await card(1).hover();await card(1).locator('.drag-handle').dragTo(card(2),{targetPosition:{x:8,y:40}});
   await until(async()=> (await api('/links?category='+encodeURIComponent(cats[0].name))).map(l=>l.key).join()===[keys[0],keys[3],keys[4],keys[1],keys[2]].join());
   await page.locator('#sections[aria-busy=false]').waitFor();await page.locator('section[data-section="'+cats[0].id+'"] [data-section-network=""]').click();await card(4).waitFor();
  });
  await check('拖入空分类自动移动分类，保留图标和记录标识',async()=>{
   await page.locator('#category-nav [data-category=""]').click();await page.locator('#sections[aria-busy=false]').waitFor();await page.locator('section[data-section="'+cats[1].id+'"]').waitFor();
   const target=page.locator('section[data-section="'+cats[1].id+'"] .empty');
   await target.scrollIntoViewIfNeeded();await card(2).hover();
   const start=await card(2).locator('.drag-handle').boundingBox(),end=await target.boundingBox();
   await page.mouse.move(start.x+start.width/2,start.y+start.height/2);await page.mouse.down();
   await page.mouse.move(start.x+start.width/2+12,start.y+start.height/2+4,{steps:4});
   await page.mouse.move(end.x+end.width/2,end.y+end.height/2,{steps:18});await page.mouse.up();
   await until(async()=> (await api('/links/'+keys[2])).category_id===cats[1].id);
   assert.equal((await api('/links/'+keys[2])).icon,'◆');
   await page.locator('section[data-section="'+cats[1].id+'"] .link-card[data-key="'+keys[2]+'"]').waitFor();
  });
  await check('拖动分类顺序并刷新保留',async()=>{
   const first=page.locator('#category-nav [data-cid="'+cats[0].id+'"]'),second=page.locator('#category-nav [data-cid="'+cats[1].id+'"]');
   await second.dragTo(first);
   await until(async()=> (await api('/categories')).filter(c=>cats.some(q=>q.id===c.id))[0].id===cats[1].id);
   await page.reload();await page.locator('.link-card').first().waitFor();
   assert.deepEqual((await api('/categories')).filter(c=>cats.some(q=>q.id===c.id)).map(c=>c.id),[cats[1].id,cats[0].id]);
  });
  await check('分类排序按钮只整理当前分类',async()=>{
   const other=await api('/links/'+keys[2]);await page.locator('[data-sort-category="'+cats[0].id+'"]').click();
   await until(async()=> (await api('/links?category='+encodeURIComponent(cats[0].name))).map(l=>l.key).join()===[keys[3],keys[4],keys[1],keys[0]].join());
   assert.deepEqual(await api('/links/'+keys[2]),other);
  });
  const batchRow=i=>page.locator('#batch-list .batch-row[data-key="'+keys[i]+'"]');
  async function chooseBatch(indices){for(const i of indices)await batchRow(i).locator('[data-select]').check();}
  await check('批量编辑名称、网址和说明实际保存并回读',async()=>{
   await page.locator('[data-batch-category="'+cats[0].id+'"]').click();await batchRow(0).waitFor();await chooseBatch([0]);
   await batchRow(0).locator('[data-field=name]').fill('批量修改网站');await batchRow(0).locator('[data-field=url]').fill('https://example.com/qa-batch-updated');await batchRow(0).locator('[data-field=description]').fill('批量修改中文说明');
   await page.locator('#batch-save').click();await until(async()=> (await api('/links/'+keys[0])).description==='批量修改中文说明');
   const saved=await api('/links/'+keys[0]);assert.equal(saved.name,'批量修改网站');assert.equal(saved.url,'https://example.com/qa-batch-updated');assert.equal(saved.icon,'◆');await page.waitForFunction(()=>document.querySelectorAll('#batch-list [data-select]:checked').length===0);
  });
  await check('多选置顶、取消置顶及移动分类均保存到后端',async()=>{
   for(const [operation,pinned] of [['pin',true],['unpin',false]]){
    await chooseBatch([0,1]);await page.locator('#batch-operation').selectOption(operation);await page.locator('#batch-apply').click();
    await until(async()=> (await api('/links/'+keys[0])).pinned===pinned&&(await api('/links/'+keys[1])).pinned===pinned);
    await page.waitForFunction(()=>document.querySelectorAll('#batch-list [data-select]:checked').length===0);
   }
   await chooseBatch([0,1]);await page.locator('#batch-operation').selectOption('move');await page.locator('#batch-target').selectOption(String(cats[1].id));await page.locator('#batch-apply').click();
   await until(async()=> (await api('/links/'+keys[0])).category_id===cats[1].id&&(await api('/links/'+keys[1])).category_id===cats[1].id);
   await batchRow(0).waitFor({state:'hidden'});await page.locator('#batch-dialog .close-dialog').first().click();
  });
  await check('批量删除二次确认，仅删除勾选网址，手机编辑布局可用',async()=>{
   await page.locator('[data-batch-category="'+cats[1].id+'"]').click();await batchRow(0).waitFor();await chooseBatch([0,1]);
   await page.locator('#batch-operation').selectOption('delete');await page.locator('#batch-apply').click();await page.locator('#confirm-dialog').waitFor({state:'visible'});
   assert.equal((await api('/links?category='+encodeURIComponent(cats[1].name))).length,3);
   await page.locator('#confirm-submit').click();await page.locator('#confirm-dialog').waitFor({state:'hidden'});await batchRow(0).waitFor({state:'hidden'});
   assert.deepEqual((await api('/links?category='+encodeURIComponent(cats[1].name))).map(l=>l.key),[keys[2]]);
   await page.setViewportSize({width:320,height:844});assert.equal(await page.locator('#batch-dialog').evaluate(d=>d.scrollWidth<=d.clientWidth),true);
   await page.screenshot({path:artifact('-batch-mobile.png')});await page.locator('#batch-dialog .close-dialog').first().click();await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>scrollTo(0,0));
  });
  await check('新增五种主题有不同材质、标签和背景动效',async()=>{
   const appearances=[];
   for(const theme of ['glass','paper','aurora','sunset','terminal']){
    const picker=page.locator('.top-actions .theme-picker');if(await picker.locator('.theme-choices').isHidden())await picker.locator('[data-open-themes]').click();
    await picker.locator('[data-theme-choice='+theme+']').click();
    assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
    appearances.push(await page.evaluate(()=>{const c=getComputedStyle(document.querySelector('.link-card')),b=getComputedStyle(document.querySelector('.badge')),a=getComputedStyle(document.querySelector('.ambient-light'),'::after');return [c.borderRadius,c.borderStyle,c.backdropFilter,b.borderRadius,b.boxShadow,a.animationName];}));
    await page.screenshot({path:artifact('-'+theme+'.png')});
   }
   assert.equal(new Set(appearances.map(a=>JSON.stringify(a))).size,5);
   assert.ok(appearances[2][5].includes('aurora-drift'));assert.equal(appearances[1][3],'2px');assert.ok(appearances[4][1].includes('dashed'));
  });
  await check('服务器背景目录与图片实际加载，来源可查，切换及刷新保留',async()=>{
   await page.locator('#open-background').click();await page.locator('#background-mode').selectOption('daily');
   await page.waitForFunction(()=>document.documentElement.dataset.background==='landscape');
   let first=await page.locator('.background-photo.visible').getAttribute('src');
   assert.ok(await page.locator('.background-photo.visible').evaluate(img=>img.complete&&img.naturalWidth===1600));
   assert.ok((await page.locator('#background-credit').getAttribute('href')).startsWith('https://unsplash.com/photos/'));
   await page.locator('#next-background').click();await page.waitForFunction(src=>document.querySelector('.background-photo.visible').getAttribute('src')!==src,first);
   const second=await page.locator('.background-photo.visible').getAttribute('src');
   await page.reload();await page.waitForFunction(()=>document.documentElement.dataset.background==='landscape');assert.equal(await page.locator('.background-photo.visible').getAttribute('src'),second);
   const manifest=(await (await page.request.get(base+'/api/v1/backgrounds')).json()).data;assert.ok(manifest.photos.length>=8);if(!isolated){assert.equal(manifest.status,'ready');assert.ok(manifest.daily_id);assert.ok(manifest.photos[0].downloaded_at);}
   for(const photo of manifest.photos.slice(0,9)){const image=await page.request.get(base+photo.image);assert.equal(image.status(),200);assert.ok((await image.body()).length>20000);}
  });
  await check('自动轮播按时切换，关闭后停止，并在跨标签页同步',async()=>{
   await page.locator('#open-background').click();await page.locator('#background-interval').selectOption('1');
   const prior=await page.locator('.background-photo.visible').getAttribute('src');
   await page.clock.fastForward(61000);
   await page.waitForFunction(src=>document.querySelector('.background-photo.visible').getAttribute('src')!==src,prior);
   const second=await context.newPage();await second.goto(base);await second.waitForFunction(()=>document.documentElement.dataset.background==='landscape');
   await page.locator('#background-mode').selectOption('theme');await page.waitForFunction(()=>document.documentElement.dataset.background==='theme');
   await second.waitForFunction(()=>document.documentElement.dataset.background==='theme');
   await page.clock.fastForward(65000);assert.equal(await page.locator('.background-photo.visible').count(),0);await second.close();
  });
  await check('页面检测到服务器新图后自动切换（受控接口跨日场景）',async()=>{
   const meta=(await (await page.request.get(base+'/api/v1/backgrounds')).json()).data;
   const bytes=await (await page.request.get(base+meta.photos[0].image)).body();
   const incoming={...meta.photos[0],id:'2099-01-01-999999',image:'/api/v1/backgrounds/2099-01-01-999999.jpg'};
   await page.route('**/api/v1/backgrounds',route=>route.fulfill({json:{data:{...meta,daily_id:incoming.id,status:'ready',photos:[incoming,...meta.photos]}}}));
   await page.route('**/api/v1/backgrounds/2099-01-01-999999.jpg',route=>route.fulfill({body:bytes,contentType:'image/jpeg'}));
   await page.locator('#background-mode').selectOption('daily');await page.clock.fastForward(61000);
   await page.waitForFunction(src=>document.querySelector('.background-photo.visible')?.getAttribute('src')===src,incoming.image);
   await page.locator('#background-mode').selectOption('theme');await page.unroute('**/api/v1/backgrounds');await page.unroute('**/api/v1/backgrounds/2099-01-01-999999.jpg');await page.reload();await page.locator('.link-card').first().waitFor();await page.locator('#open-background').click();
  });
  await check('关闭动效与系统减少动态效果均生效',async()=>{
   await page.evaluate(()=>window.NavTheme.set('aurora'));
   await page.locator('#background-motion').uncheck();assert.equal(await page.evaluate(()=>getComputedStyle(document.querySelector('.ambient-light'),'::after').animationName),'none');
   await page.locator('#background-motion').check();await page.emulateMedia({reducedMotion:'reduce'});
   assert.equal(await page.evaluate(()=>getComputedStyle(document.querySelector('.ambient-light'),'::after').animationName),'none');await page.emulateMedia({reducedMotion:'no-preference'});
  });
  await check('图片失败保留主题背景，可重试恢复且不向第三方发请求',async()=>{
   await page.route(/\/(?:static\/backgrounds|api\/v1\/backgrounds)\/[^/]+\.jpg$/,route=>route.abort());
   await page.locator('#background-mode').selectOption('daily');await page.locator('#background-status').waitFor({state:'visible'});
   assert.equal(await page.locator('html').getAttribute('data-background'),'theme');
   await page.unroute(/\/(?:static\/backgrounds|api\/v1\/backgrounds)\/[^/]+\.jpg$/);await page.locator('#next-background').click();
   await page.waitForFunction(()=>document.documentElement.dataset.background==='landscape');
   await page.locator('#background-mode').selectOption('theme');assert.deepEqual(externalRequests,[]);
  });
  await check('320 与 390 手机布局可使用全部主题及背景设置',async()=>{
   for(const width of [320,390]){
    await page.setViewportSize({width,height:844});await page.locator('#open-background').click();
    const picker=page.locator('.top-actions .theme-picker');await picker.locator('[data-open-themes]').click();
    const rect=await picker.locator('.theme-choices').boundingBox();assert.ok(rect.x>=0 && rect.x+rect.width<=width);
    assert.equal(await picker.locator('[data-theme-choice]').count(),12);await picker.locator('[data-theme-choice=glass]').click();
    await page.keyboard.press('Escape');await page.locator('#open-background').click();const panel=await page.locator('#background-panel').boundingBox();assert.ok(panel.x>=0&&panel.x+panel.width<=width);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:artifact('-mobile-'+width+'.png')});await page.keyboard.press('Escape');
   }
  });
  assert.deepEqual(errors,[]);
 } catch(error) { await page.screenshot({path:artifact('-failure.png')}).catch(()=>{}); console.error('UI_STATUS',await page.locator('#toast').textContent(),await page.evaluate(()=>window.__dragEvents));console.error('QA_STATE',(await api('/links')).filter(l=>keys.includes(l.key)).map(l=>({key:l.key,name:l.name,pinned:l.pinned,category_id:l.category_id}))); throw error; } finally {
  for(const key of keys){try{await api('/links/'+key,'DELETE');}catch{}}
  for(const c of cats){try{await api('/categories/'+c.id,'DELETE',{});}catch{}}
  const after=await snapshot();
  fs.writeFileSync(artifact('-results.json'),JSON.stringify({base,isolated,checks,errors,originalDataUnchanged:require('node:util').isDeepStrictEqual(after,before)},null,2));
  await browser.close();assert.deepEqual(after,before,'原有导航数据发生变化');
 }
 console.log('APPEARANCE_ORDER_CHECKS',checks.length);
})().catch(error=>{console.error(error);process.exitCode=1;});
