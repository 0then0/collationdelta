// Real browser acceptance against the production artifact under /collationdelta/.
// Uses only the explicitly installed, existing optional toolchain. No downloads.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import { createRequire } from 'node:module';
const [toolchain, site, output, ...names] = process.argv.slice(2);
if (!toolchain || !site || !output || !names.length) throw Error('Usage: node check_browser_page.mjs TOOLCHAIN SITE OUTPUT chromium firefox');
const require = createRequire(path.resolve(toolchain, 'package.json'));
const playwright = require('./node_modules/playwright-core');
await fs.mkdir(output, { recursive: true });
const allowed = ['index.html', 'app.mjs', 'input.mjs', 'worker.mjs', 'intl.mjs', 'style.css'];
const requests = [];
const server = http.createServer(async (req, res) => {
  requests.push({ method: req.method, url: req.url });
  const file = req.url === '/collationdelta/' ? 'index.html' : req.url.replace('/collationdelta/', '');
  if (req.method !== 'GET' || !allowed.includes(file)) { res.writeHead(404).end(); return; }
  try {
    const body = await fs.readFile(path.join(site, file));
    res.setHeader('Content-Type', file.endsWith('.mjs') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html');
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const manifest = { toolchain_version: require('./node_modules/playwright-core/package.json').version, runtimes: {} };
try {
  for (const name of names) {
    const browser = await playwright[name].launch({ headless: true });
    try {
      const context = await browser.newContext({ viewport: { width: 1100, height: 900 }, acceptDownloads: true });
      const page = await context.newPage();
      const network = [], errors = [];
      context.on('request', request => network.push({ method: request.method(), url: request.url(), body: request.postData() }));
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(`${origin}/collationdelta/`);
      await page.locator('#example').click();
      assert.match(await page.locator('#summary').textContent(), /8 strings/);
      const download = async filename => {
        await page.locator('#capture').click();
        await page.locator('#download').waitFor({ state: 'visible' });
        const pending = page.waitForEvent('download');
        await page.locator('#download').click();
        await (await pending).saveAs(path.join(output, filename));
        return JSON.parse(await fs.readFile(path.join(output, filename), 'utf8'));
      };
      const first = await download(`${name}.browser-export.json`);
      assert.equal(first.metadata.execution_context.kind, 'dedicated-worker');
      assert.equal(first.coverage.completed_comparisons, 64);
      assert.equal(first.coverage.complete, true);
      // Keyboard focus is visible and the actual populated page is inspected at both sizes.
      await page.locator('#example').focus();
      await page.keyboard.press('Tab');
      assert.ok(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle !== 'none'));
      await page.screenshot({ path: path.join(output, `${name}-desktop.png`), fullPage: true });
      await page.setViewportSize({ width: 360, height: 800 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: path.join(output, `${name}-narrow.png`), fullPage: true });
      const repeat = await download(`${name}-repeat.browser-export.json`);
      assert.deepEqual(repeat.observation, first.observation);
      const upload = async (id, value) => page.locator(id).setInputFiles({ name: 'input.json', mimeType: 'application/json', buffer: Buffer.from(typeof value === 'string' ? value : JSON.stringify(value)) });
      // File inputs, long IDs, controls, supplementary IDs, exact duplicates, and HTML-as-text.
      const corpus = structuredClone(first.corpus);
      corpus.entries[0].id = '😀\u0000';
      corpus.entries[1].value = '<img src="https://invalid.example/private" onerror="throw Error(1)">';
      corpus.entries[2].id = 'long'.repeat(100);
      await upload('#corpus', corpus);
      await upload('#profile', first.requested);
      await page.waitForFunction(() => !document.querySelector('#capture').disabled);
      const fileResult = await download(`${name}-files.browser-export.json`);
      assert.deepEqual(fileResult.corpus, corpus);
      assert.equal(await page.locator('img').count(), 0);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      // Unsupported is exportable, with no fallback pairs.
      await upload('#profile', { ...first.requested, locale: 'zz-ZZ' });
      await page.waitForFunction(() => !document.querySelector('#capture').disabled);
      const unsupported = await download(`${name}-unsupported.browser-export.json`);
      assert.equal(unsupported.observation.status, 'unsupported');
      assert.equal(unsupported.coverage.complete, false);
      assert.equal(unsupported.observation.results.length, 0);
      assert.match(await page.locator('#status').textContent(), /Unsupported/);
      await page.screenshot({ path: path.join(output, `${name}-unsupported.png`), fullPage: true });
      // Duplicate keys, Unicode and byte limits are input errors, never captures.
      for (const invalid of ['{"version":1,"version":1,"entries":[]}', '{"version":1,"entries":[{"id":"x","value":"\\ud800"}]}', ' '.repeat(1024 * 1024 + 1)]) {
        await upload('#corpus', invalid);
        await page.waitForFunction(() => document.querySelector('#status').dataset.state === 'error');
        assert.equal(await page.locator('#download').isVisible(), false);
        assert.equal(await page.locator('#capture').isDisabled(), true);
      }
      // A deliberately stalled Worker is a controlled UI fixture, not runtime evidence.
      await page.route('**/worker.mjs', route => route.fulfill({ contentType: 'text/javascript', body: 'self.onmessage=()=>{while(true){}};' }));
      await page.locator('#example').click();
      await page.locator('#capture').click();
      await page.locator('#cancel').click(); // Main thread stays responsive.
      assert.equal(await page.locator('#download').isVisible(), false);
      await page.locator('#example').click();
      await page.locator('#capture').click();
      await upload('#profile', first.requested); // Cancels in-flight run and discards old inputs.
      assert.equal(await page.locator('#download').isVisible(), false);
      assert.equal(await page.locator('#capture').isDisabled(), true);
      if (name === 'chromium') {
        await page.locator('#example').click();
        await page.locator('#capture').click();
        await page.waitForFunction(() => document.querySelector('#status').textContent.includes('exceeded 15 seconds'), null, { timeout: 18000 });
        assert.equal(await page.locator('#download').isVisible(), false);
      }
      await page.unroute('**/worker.mjs');
      await page.locator('#example').click();
      await download(`${name}-after-cancel.browser-export.json`);
      // All observed requests are static GETs, contain no uploaded file data, and stay on origin.
      assert.ok(network.length > 0);
      for (const request of network) {
        const url = new URL(request.url);
        assert.equal(url.origin, origin);
        assert.equal(request.method, 'GET');
        assert.equal(request.body, null);
        assert.ok(allowed.includes(url.pathname.replace('/collationdelta/', '') || 'index.html'));
      }
      assert.deepEqual(errors, []);
      manifest.runtimes[name] = { version: browser.version(), executable: playwright[name].executablePath(), network, checks: ['example', 'download', 'file-inputs', 'unsupported', 'strict-inputs', 'cancel', 'input-change', 'repeat', '360px', 'keyboard-focus', 'static-network-only'] };
      console.log(`${name} ${browser.version()}: browser-page acceptance passed`);
      await context.close();
    } finally { await browser.close(); }
  }
} finally {
  await new Promise(resolve => server.close(resolve));
}
manifest.server_requests = requests;
await fs.writeFile(path.join(output, 'browser-checks.json'), JSON.stringify(manifest, null, 2) + '\n');
