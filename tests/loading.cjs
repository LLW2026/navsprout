/* Read-only acceptance: production sessions are separate from the user's browser. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('fs'), assert=require('node:assert/strict');
const base=process.env.NAV_TEST_URL || 'http://127.0.0.1:8866';
const isolated=process.env.NAV_ORDER_ISOLATED==='1';
const password=isolated?(process.env.NAV_TEST_PASSWORD || '测试专用密码-20261024'):fs.readFileSync(process.env.HOME+'/.config/navsprout/admin-password.txt','utf8').trim();
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--no-proxy-server']});
 const context=await browser.newContext({viewport:{width:1920,height:1080}}), page=await context.newPage();
 const errors=[], results=[];page.on('pageerror',e=>errors.push(e.message));
 await context.addInitScript(()=>{if(!localStorage.getItem('nav-background'))localStorage.setItem('nav-background',JSON.stringify({mode:'daily',interval:1440,motion:false,overlay:'none'}));});
 try{
 await page.goto(base);await page.locator('[name=password]').fill(password);await page.locator('#login-form button').click();
 await page.locator('.link-card').first().waitFor();
 // Measure a fresh authenticated tab, then a normal navigation in that same tab.
 const state=await context.storageState();await context.close();
 const measuredContext=await browser.newContext({storageState:state,viewport:{width:1920,height:1080}});
 const measured=await measuredContext.newPage();measured.on('pageerror',e=>errors.push(e.message));
 for(let run=0;run<2;run++){
 const start=Date.now();await measured.goto(base,{waitUntil:'domcontentloaded'});
 await measured.locator('.link-card').first().waitFor();const cards=Date.now()-start;
 await measured.waitForFunction(()=>document.querySelector('.background-photo.visible'),null,{timeout:60000});const preview=Date.now()-start;
 await measured.waitForFunction(()=>document.querySelector('.background-photo.visible')?.naturalWidth>=3840,null,{timeout:60000});const full=Date.now()-start;
 await measured.waitForTimeout(1500);
 const record=await measured.evaluate(()=>({cards:document.querySelectorAll('.link-card').length,icons:document.querySelectorAll('.has-favicon').length,dimensions:[document.querySelector('.background-photo.visible').naturalWidth,document.querySelector('.background-photo.visible').naturalHeight],resources:performance.getEntriesByType('resource').map(r=>({path:new URL(r.name).pathname,bytes:r.transferSize,duration:Math.round(r.duration)}))}));
 const icons=record.resources.filter(r=>r.path.endsWith('/favicon'));
 assert.ok(icons.length<record.cards,'图标应按需加载');
 assert.ok(record.icons>0,'真实图标应显示');
 if(run===1){assert.ok(record.resources.filter(r=>/\.(js|css)$/.test(r.path)).every(r=>r.bytes===0),'重复访问静态资源应来自缓存');assert.ok(record.resources.filter(r=>/\.(webp|image)$/.test(r.path)).every(r=>r.bytes<=500),'重复访问背景应缓存复用或304');}
 results.push({run,cardsMs:cards,previewMs:preview,fullMs:full,cardCount:record.cards,icons:record.icons,iconRequests:icons.length,networkBytes:record.resources.reduce((a,r)=>a+r.bytes,0),dimensions:record.dimensions});
 console.log('PASS '+JSON.stringify(results.at(-1)));
 }
 const countBeforeScroll=await measured.evaluate(()=>performance.getEntriesByType('resource').filter(r=>new URL(r.name).pathname.endsWith('/favicon')).length);
 await measured.locator('.link-card').last().scrollIntoViewIfNeeded();await measured.waitForTimeout(2000);
 const countAfterScroll=await measured.evaluate(()=>performance.getEntriesByType('resource').filter(r=>new URL(r.name).pathname.endsWith('/favicon')).length);
 assert.ok(countAfterScroll>countBeforeScroll,'滚动后应请求新可见卡片的图标');
 const meta=(await (await measured.request.get(base+'/api/v1/backgrounds')).json()).data;
 const image=await measured.request.get(base+meta.photos[0].optimized_image);const etag=image.headers().etag;
 const anonymous=await browser.newContext();assert.equal((await anonymous.request.get(base+meta.photos[0].optimized_image,{headers:{'If-None-Match':etag}})).status(),401);await anonymous.close();
 for(const width of [320,3440,5120]){await measured.setViewportSize({width,height:1000});assert.ok(await measured.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'窄屏和超宽屏无横向溢出');}
 assert.deepEqual(errors,[]);
 fs.writeFileSync(process.env.NAV_LOADING_RESULT || 'artifacts/loading-acceptance.json',JSON.stringify({base,results,errors,checks:['静态缓存','私有背景304','原分辨率WebP','预览','可见区域图标','滚动加载','匿名拒绝','320/3440/5120布局']},null,2));
 console.log('PASS authenticated caching, visible icons, scrolling, full resolution, privacy, responsive layout');
 }finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exit(1)});
