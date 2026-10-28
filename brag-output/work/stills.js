const {chromium}=require('playwright');
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:1920,height:1080}});
const errs=[];p.on('pageerror',e=>errs.push(e.message));
await p.goto('file://'+process.argv[2]);await p.evaluate(()=>window.ready);
const ts=process.argv[4].split(',').map(Number);
for(const t of ts){await p.evaluate(t=>seek(t),t);await p.screenshot({path:process.argv[3]+'/st-'+String(t).replace('.','_')+'.jpg',type:'jpeg',quality:80});}
console.log('errors',errs);await b.close()})();
