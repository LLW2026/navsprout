/* UI preferences are exercised on a disposable instance, including real storage events. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
if(process.env.NAV_GROUPS_ISOLATED!=='1')throw new Error('透明度回归必须使用隔离数据库');
const base=process.env.NAV_TEST_URL,token=process.env.NAV_TEST_API_TOKEN,password=process.env.NAV_TEST_PASSWORD;
const keys=['qa-transparency-public','qa-transparency-lan','qa-transparency-single'];let category;let passed=0;
async function api(route,method='GET',body){const r=await fetch(base+'/api/v1'+route,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const d=await r.json();assert.ok(r.ok,r.status+' '+JSON.stringify(d));return d.data||d;}
async function check(name,fn){await fn();passed++;console.log('PASS',name)}
async function alpha(page){return page.locator('.link-card').evaluateAll(cards=>cards.map(card=>{const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d');ctx.fillStyle=getComputedStyle(card).backgroundColor;ctx.fillRect(0,0,1,1);return ctx.getImageData(0,0,1,1).data[3]/255}));}
async function expectAlpha(page,value){for(const actual of await alpha(page))assert.ok(Math.abs(actual-value)<.01,actual+' != '+value)}
(async()=>{const b=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});const context=await b.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 category=await api('/categories','POST',{name:'透明度验收'});for(let i=0;i<3;i++)await api('/links/upsert','POST',{key:keys[i],name:'透明度入口'+i,url:base+'/?entry='+i,category:category.name,icon:'验',network:i===1?'lan':'public'});await api('/groups','POST',{name:'透明度聚合',keys:keys.slice(0,2)});
 await page.goto(base);await page.locator('[name=password]').fill(password);await page.locator('#login-form button').click();await page.locator('.group-card').waitFor();
 const picker=page.locator('.top-actions .theme-picker'),slider=picker.locator('[data-card-transparency]');
 await check('默认保留各主题材质，面板显示其实际透明度',async()=>{
  await picker.locator('[data-open-themes]').click();assert.equal(await slider.inputValue(),'0');
  await picker.locator('[data-theme-choice=glass]').click();assert.equal(await slider.inputValue(),'21');await expectAlpha(page,201/255);
  await picker.locator('[data-theme-choice=aurora]').click();assert.equal(await slider.inputValue(),'13');await expectAlpha(page,222/255);
  await picker.locator('[data-theme-choice=pine]').click();await expectAlpha(page,1);
 });
 await check('鼠标拖动即时改变普通与聚合背景，文字保持不透明',async()=>{
  const box=await slider.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width*.56,box.y+box.height/2,{steps:8});await page.mouse.up();const value=Number(await slider.inputValue());assert.ok(value>=54&&value<=58);assert.equal(await picker.locator('output').textContent(),value+'%');await expectAlpha(page,1-value/100);assert.equal(await picker.locator('.theme-choices').isVisible(),true);
  for(const opacity of await page.locator('.link-card,.link-card h3').evaluateAll(nodes=>nodes.map(n=>getComputedStyle(n).opacity)))assert.equal(opacity,'1');
 });
 await check('键盘可调到全不透明和全透明，卡片文字仍可见',async()=>{
  await slider.focus();await page.keyboard.press('Home');assert.equal(await slider.inputValue(),'0');await expectAlpha(page,1);await page.keyboard.press('End');assert.equal(await slider.inputValue(),'100');await expectAlpha(page,0);await page.locator('.group-card h3').waitFor({state:'visible'});
  await slider.evaluate(el=>{el.value='55';el.dispatchEvent(new Event('input',{bubbles:true}))});await expectAlpha(page,.45);
 });
 await check('刷新和同浏览器多标签同步，切换所有主题保留透明度',async()=>{
  await page.reload();await page.locator('.group-card').waitFor();assert.equal(await slider.inputValue(),'55');await expectAlpha(page,.45);
  const other=await context.newPage();await other.goto(base);await other.locator('.group-card').waitFor();await picker.locator('[data-open-themes]').click();await slider.focus();await page.keyboard.press('ArrowRight');assert.equal(await slider.inputValue(),'56');await other.waitForFunction(()=>document.documentElement.dataset.cardTransparency==='56');await expectAlpha(other,.44);assert.equal(await other.locator('.top-actions [data-card-transparency]').inputValue(),'56');
  for(const theme of await page.evaluate(()=>NavTheme.catalog.map(([name])=>name))){await picker.locator('[data-theme-choice='+theme+']').click();assert.equal(await slider.inputValue(),'56');await expectAlpha(page,.44)}await other.close();
 });
 await check('320/390手机与电脑主题面板、滑动条均在屏幕内',async()=>{
  for(const width of [320,390,1440]){await page.setViewportSize({width,height:844});const panel=picker.locator('.theme-choices'),bounds=await panel.boundingBox();assert.ok(bounds.x>=0&&bounds.y>=0&&bounds.x+bounds.width<=width);await slider.click({trial:true});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  await page.keyboard.press('Escape');await picker.locator('.theme-choices').waitFor({state:'hidden'});
 });
 await check('登录面板共用滑动条，浏览器禁用存储时仍可调整',async()=>{
  const c=await b.newContext({viewport:{width:320,height:844}}),p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));await p.addInitScript(()=>{Storage.prototype.getItem=()=>{throw new Error('blocked')};Storage.prototype.setItem=()=>{throw new Error('blocked')}});await p.goto(base);await p.locator('.login-theme [data-open-themes]').click();const input=p.locator('.login-theme [data-card-transparency]');await input.evaluate(el=>{el.value='60';el.dispatchEvent(new Event('input',{bubbles:true}))});assert.equal(await p.locator('.login-theme output').textContent(),'60%');assert.equal(await p.evaluate(()=>NavTheme.getTransparency()),60);const box=await p.locator('.login-theme .theme-choices').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=320&&box.y>=0);await c.close();
 });
 assert.deepEqual(errors,[]);console.log('TRANSPARENCY_CHECKS',passed);
}finally{await b.close();for(const key of keys)try{await api('/links/'+key,'DELETE')}catch{}if(category)await api('/categories/'+category.id,'DELETE',{});}
})().catch(e=>{console.error(e.stack);process.exit(1)});
