const {chromium}=require('playwright');
(async()=>{const [file,out,a,b]=process.argv.slice(2);const br=await chromium.launch();
const p=await br.newPage({viewport:{width:1920,height:1080}});
await p.goto('file://'+file);await p.evaluate(()=>window.ready);
for(let f=+a;f<+b;f++){await p.evaluate(t=>seek(t),f/30);
await p.screenshot({path:out+'/f'+String(f).padStart(5,'0')+'.jpg',type:'jpeg',quality:93});}
await br.close();console.log('done',a,b)})();
