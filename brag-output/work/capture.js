// usage: node capture.js stills t1,t2,...  |  node capture.js video out.mp4
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
(async () => {
  const mode = process.argv[2];
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  pg.on('pageerror', e => console.error('PAGEERR', e.message));
  await pg.goto('file://' + path.join(__dirname, 'video.html'));
  await pg.evaluate(() => window.ready);
  if (mode === 'stills') {
    for (const t of process.argv[3].split(',').map(Number)) {
      await pg.evaluate(t => render(t), t);
      await pg.screenshot({ path: path.join(__dirname, 'stills', `t${t.toFixed(2)}.jpg`), type: 'jpeg', quality: 85 });
    }
  } else {
    const FPS = 30, N = 60 * FPS;
    const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
      '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', process.argv[3]], { stdio: ['pipe', 'inherit', 'inherit'] });
    for (let f = 0; f < N; f++) {
      await pg.evaluate(t => render(t), f / FPS);
      const buf = await pg.screenshot({ type: 'jpeg', quality: 93 });
      if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
      if (f % 150 === 0) console.log('frame', f);
    }
    ff.stdin.end(); await new Promise(r => ff.on('close', r));
  }
  await b.close();
})();
