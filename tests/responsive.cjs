/* Read-only acceptance of real catalog layouts on wide and ultrawide screens. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const vars={NAV_API_TOKEN:process.env.NAV_TEST_API_TOKEN};
const password=process.env.NAV_TEST_PASSWORD;
const base=process.env.NAV_TEST_URL||'http://127.0.0.1:8866',checks=[],errors=[];
async function snapshot(){const r=await fetch(base+'/api/v1/export',{headers:{Authorization:'Bearer '+vars.NAV_API_TOKEN}});assert.equal(r.status,200);const data=await r.json();delete data.exported_at;return data;}
(async()=>{
 const before=await snapshot(),browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 const context=await browser.newContext(),page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(base);await page.locator('#login-view').waitFor();await page.locator('[name=password]').fill(password);await page.locator('#login-form button').click();await page.locator('.link-card').first().waitFor();
  for(const [width,height,columns] of [[1920,1080,1],[2560,1080,1],[3440,1440,2],[3840,1080,2],[5120,1440,2],[2560,720,2]]){
   await page.setViewportSize({width,height});await page.evaluate(()=>scrollTo(0,0));
   const layout=await page.evaluate(()=>{
    const content=document.querySelector('.content').getBoundingClientRect(),sections=document.querySelector('#sections'),style=getComputedStyle(sections);
    const cards=[...document.querySelectorAll('.link-card')].map(n=>n.getBoundingClientRect());
    const pinned=document.querySelector('section[data-section=pinned]')?.getBoundingClientRect();
    return {viewport:innerWidth,scroll:document.documentElement.scrollWidth,contentWidth:content.width,columns:style.display==='grid'?style.gridTemplateColumns.split(' ').length:1,
     minCard:Math.min(...cards.map(c=>c.width)),maxCard:Math.max(...cards.map(c=>c.width)),cardRight:Math.max(...cards.map(c=>c.right)),search:document.querySelector('#search-form').getBoundingClientRect().width,
     pinnedWidth:pinned?.width,sectionsWidth:sections.getBoundingClientRect().width};
   });
   assert.ok(layout.scroll<=width);assert.equal(layout.columns,columns);assert.ok(layout.contentWidth>width*.8);assert.ok(layout.minCard>=210&&layout.maxCard<=350);assert.ok(layout.cardRight<=width);assert.ok(layout.search<=1201);
   if(layout.pinnedWidth)assert.ok(Math.abs(layout.pinnedWidth-layout.sectionsWidth)<2);
   const picker=page.locator('.top-actions .theme-picker');await picker.locator('[data-open-themes]').click();const rect=await picker.locator('.theme-choices').boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=width);await page.keyboard.press('Escape');
   await page.locator('.top-actions summary[aria-label="设置"]').click();assert.ok(await page.locator('#sort-links').isVisible());await page.locator('.top-actions summary[aria-label="设置"]').click();
   await page.screenshot({path:path.join(root,`artifacts/wide-${width}x${height}.png`)});checks.push({width,height,...layout});console.log('PASS',width+'x'+height,columns+'列分类','卡片宽度',Math.round(layout.minCard)+'–'+Math.round(layout.maxCard));
  }
  await page.setViewportSize({width:1440,height:1050});await page.evaluate(()=>{window.NavTheme.set('glass');scrollTo(0,0)});
  await page.screenshot({path:path.join(root,'artifacts/desktop.png')});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(root,'artifacts/mobile.png')});
  assert.deepEqual(await snapshot(),before);assert.deepEqual(errors,[]);
 }finally{fs.writeFileSync(path.join(root,'artifacts/responsive-results.json'),JSON.stringify({base,checks,errors},null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
