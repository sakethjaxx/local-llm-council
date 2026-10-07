// Run against an isolated preview server. All inference responses are synthetic.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

const baseURL = process.env.COUNCIL_PREVIEW_URL || 'http://127.0.0.1:8799';
const output = path.resolve(process.env.COUNCIL_UI_OUTPUT || '.audit-tmp/screenshots');
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

const RUN = { run_id: 'run-synthetic-1', status: 'completed', topic: 'Synthetic review', started_at: 1760000000 };
const RUN_DETAIL = {
  ...RUN, roster: { architect: { label: 'Architecture' } }, feedback: [],
  phases: [
    { phase: 1, member_id: 'architect', output: 'Looks fine.' },
    { phase: 3, member_id: 'chairman', output: '{"verdict":"PROCEED"}' },
  ],
};

// Serious and critical axe findings fail the run; minor/moderate ones are printed.
async function assertAccessible(page, label) {
  await page.evaluate(axeSource);
  const violations = await page.evaluate(async () => (await window.axe.run(document, { resultTypes: ['violations'], preload: false }))
    .violations.map((v) => ({ id: v.id, impact: v.impact, targets: v.nodes.slice(0, 3).map((n) => n.target.join(' ')) })));
  const blocking = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  for (const v of violations.filter((x) => !blocking.includes(x))) console.log(`  note (${v.impact}) ${label}: ${v.id} ${v.targets}`);
  assert.deepEqual(blocking, [], `Accessibility violations in ${label}: ${JSON.stringify(blocking)}`);
}

async function verify() {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 768, height: 1024 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
      const page = await browser.newPage({ viewport });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      // CSP violations and failed resource loads surface as console errors.
      page.on('console', message => { if (message.type() === 'error') errors.push(`console: ${message.text()}`); });
      await page.route('**/ollama/check', route => route.fulfill({ json: { ready: true, missing: [], warnings: [] } }));
      // A same-origin image for the Markdown check below (1x1 transparent PNG).
      await page.route('**/static/markdown-check.png', route => route.fulfill({ contentType: 'image/png',
        body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64') }));
      await page.route('**/runs?*', route => route.fulfill({ json: { runs: [RUN] } }));
      await page.route(`**/runs/${RUN.run_id}`, route => route.fulfill({ json: RUN_DETAIL }));
      await page.route('**/council/stream', route => {
        const meta = { label: 'Architecture', icon: 'A', color: '#0071e3' };
        const decision = JSON.stringify({ verdict: 'PROCEED', risk_score: 2, action_items: ['Add integration coverage'], consensus: ['Safe defaults'], disputes: [] });
        const events = [
          { type: 'phase_start', phase: 1, label: 'Analysis' },
          { type: 'member_thinking', phase: 1, member: 'architect', meta },
          { type: 'member_token', member: 'architect', chunk: '**Safe review**' },
          { type: 'member_done', member: 'architect', full_text: '**Safe review**' },
          { type: 'phase_start', phase: 3, label: 'Synthesis' },
          { type: 'member_thinking', phase: 3, member: 'chairman', meta: { ...meta, label: 'Chairman' } },
          { type: 'member_done', member: 'chairman', full_text: decision },
          { type: 'done' },
        ];
        return route.fulfill({ contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') });
      });
      await page.goto(baseURL);
      await page.waitForFunction(() => document.getElementById('preflightBox').textContent.includes('ready'));
      const overflow = () => page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: window.innerWidth }));
      let dimensions = await overflow();
      assert(dimensions.scroll <= dimensions.width, `Initial overflow at ${viewport.width}: ${JSON.stringify(dimensions)}`);
      await page.screenshot({ path: path.join(output, `initial-${viewport.width}.png`), fullPage: true });
      await assertAccessible(page, `main ${viewport.width}`);

      // Dialogs: open, check, close with Escape, and focus goes back to the opener.
      await page.getByRole('button', { name: 'Connection', exact: true }).click();
      assert.equal(await page.locator('#connectionModal').evaluate(el => el.style.display), 'flex');
      if (viewport.width === 1440) await assertAccessible(page, 'connection dialog');
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('main').evaluate(el => el.inert), false);
      assert.equal(await page.evaluate(() => document.activeElement?.textContent.trim()), 'Connection', 'focus not restored');

      await page.getByRole('button', { name: 'Replays', exact: true }).click();
      await page.waitForFunction(() => document.querySelector('.replay-run-open'));
      if (viewport.width === 1440) await assertAccessible(page, 'replay dialog');
      await page.locator('.replay-run-open').first().focus();
      await page.keyboard.press('Enter');  // rows must work from the keyboard
      await page.waitForFunction(() => document.querySelectorAll('#replayRunDetail .replay-phase').length >= 2);
      await page.screenshot({ path: path.join(output, `history-${viewport.width}.png`) });
      await page.getByRole('button', { name: 'Close run history', exact: true }).click();

      if (viewport.width === 1440) {
        await page.getByRole('button', { name: 'Models', exact: true }).click();
        await page.waitForFunction(() => document.querySelector('#modelLibraryModal')?.style.display === 'flex');
        await page.waitForTimeout(800);
        await assertAccessible(page, 'model library dialog');
        await page.keyboard.press('Escape');
      }

      // Model Markdown must not load remote resources; links open safely.
      const rendered = await page.evaluate(() => {
        const box = document.createElement('div');
        box.innerHTML = renderMarkdown('![x](https://tracker.example/p.png?q=topic) [docs](https://docs.example) ![ok](/static/markdown-check.png)');
        return { imgs: [...box.querySelectorAll('img')].map((img) => img.getAttribute('src')),
                 rel: box.querySelector('a')?.getAttribute('rel') };
      });
      assert.deepEqual(rendered.imgs, [null, '/static/markdown-check.png'], JSON.stringify(rendered));
      assert.equal(rendered.rel, 'noopener noreferrer');

      for (const view of ['Memory', 'Code Graph']) {
        await page.getByRole('button', { name: view, exact: true }).click();
        await page.waitForFunction(() => document.getElementById('memoryModal').style.display === 'flex');
        await page.waitForTimeout(500);
        await page.getByRole('button', { name: 'Close graph', exact: true }).click();
      }

      // Removing a seat works from the keyboard.
      const seats = await page.locator('.seat-item').count();
      await page.locator('.seat-remove').first().focus();
      await page.keyboard.press('Enter');
      assert.equal(await page.locator('.seat-item').count(), seats - 1, 'seat remove is not keyboard-operable');

      await page.getByRole('textbox', { name: 'Review topic', exact: true }).fill('Review this synthetic project');
      await page.getByRole('button', { name: 'Run council', exact: true }).click();
      await page.waitForFunction(() => document.getElementById('councilPanel').textContent.includes('PROCEED'));
      await page.locator('.action-checkbox').check();
      assert(await page.locator('.action-item-row').evaluate(el => el.classList.contains('is-done')));
      assert.equal(await page.locator('.run-skeleton').count(), 0);
      dimensions = await overflow();
      assert(dimensions.scroll <= dimensions.width, `Stream overflow at ${viewport.width}: ${JSON.stringify(dimensions)}`);
      await assertAccessible(page, `results ${viewport.width}`);
      await page.locator('#councilPanel').scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(output, `result-${viewport.width}.png`), fullPage: true });

      if (viewport.width === 1440) {
        await page.evaluate(() => document.getElementById('themeToggle').click());
        await assertAccessible(page, 'dark theme');
      }
      assert.deepEqual(errors, [], `Browser errors at ${viewport.width}`);
      console.log(`PASS ${viewport.width}x${viewport.height}: layout, dialogs, keyboard, accessibility, history, streaming, action controls`);
      await page.close();
    }
  } finally {
    await browser.close();
  }
}

verify().catch(error => { console.error(error); process.exitCode = 1; });
