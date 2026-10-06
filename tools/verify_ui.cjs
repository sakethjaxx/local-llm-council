// Run against an isolated preview server. All inference responses are synthetic.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

const baseURL = process.env.COUNCIL_PREVIEW_URL || 'http://127.0.0.1:8799';
const output = path.resolve(process.env.COUNCIL_UI_OUTPUT || '.audit-tmp/screenshots');

async function verify() {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 768, height: 1024 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
      const page = await browser.newPage({ viewport });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/ollama/check', route => route.fulfill({ json: { ready: true, missing: [], warnings: [] } }));
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

      await page.getByRole('button', { name: 'Connection', exact: true }).click();
      assert.equal(await page.locator('#connectionModal').evaluate(el => el.style.display), 'flex');
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('main').evaluate(el => el.inert), false);
      await page.getByRole('button', { name: 'Replays', exact: true }).click();
      await page.waitForFunction(() => !document.getElementById('replayRunList').textContent.includes('Loading'));
      await page.screenshot({ path: path.join(output, `history-${viewport.width}.png`) });
      await page.getByRole('button', { name: 'Close run history', exact: true }).click();

      await page.getByRole('textbox', { name: 'Review topic', exact: true }).fill('Review this synthetic project');
      await page.getByRole('button', { name: 'Run council', exact: true }).click();
      await page.waitForFunction(() => document.getElementById('councilPanel').textContent.includes('PROCEED'));
      await page.locator('.action-checkbox').check();
      assert(await page.locator('.action-item-row').evaluate(el => el.classList.contains('is-done')));
      assert.equal(await page.locator('.run-skeleton').count(), 0);
      dimensions = await overflow();
      assert(dimensions.scroll <= dimensions.width, `Stream overflow at ${viewport.width}: ${JSON.stringify(dimensions)}`);
      await page.locator('#councilPanel').scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(output, `result-${viewport.width}.png`), fullPage: true });
      assert.deepEqual(errors, [], `Browser errors at ${viewport.width}`);
      console.log(`PASS ${viewport.width}x${viewport.height}: layout, dialogs, history, streaming, action controls`);
      await page.close();
    }
  } finally {
    await browser.close();
  }
}

verify().catch(error => { console.error(error); process.exitCode = 1; });
