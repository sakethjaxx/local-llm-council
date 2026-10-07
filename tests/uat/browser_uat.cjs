// Real-model browser acceptance journey (nothing mocked). Launched by run_uat.py --browser,
// or directly: COUNCIL_PREVIEW_URL=http://127.0.0.1:8765 NODE_PATH=tools/frontend/node_modules node tests/uat/browser_uat.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const baseURL = process.env.COUNCIL_PREVIEW_URL || 'http://127.0.0.1:8765';
const output = path.resolve(process.env.COUNCIL_UI_OUTPUT || '.audit-tmp/uat/screenshots');
const RUN_TIMEOUT_MS = Number(process.env.UAT_RUN_TIMEOUT_MS || 30 * 60 * 1000);

const step = (message) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${message}`);

async function journey() {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(`console: ${msg.text()}`); });
  try {
    await page.goto(baseURL);
    await page.waitForFunction(() => document.querySelectorAll('.seat-item').length > 0);
    step('UI loaded with hardware-suggested roster');

    await page.getByRole('button', { name: 'Turbo', exact: true }).click();
    await page.getByRole('button', { name: 'Economy', exact: true }).click();
    while (await page.locator('.seat-item').count() > 2) {
      await page.locator('.seat-remove').first().click();
    }
    const models = await page.locator('.seat-model-select').evaluateAll((els) => els.map((el) => el.value));
    assert.equal(new Set(models).size, 1, `Turbo should put every seat on one small model: ${models}`);
    assert.equal(await page.locator('.seat-model-missing').count(), 0, 'Turbo picked a model that is not installed');
    await page.waitForFunction(() => /ready/i.test(document.getElementById('preflightBox').textContent));
    step(`Roster: 1 analyst + chairman on ${models[0]}, economy budget, preflight ready`);

    await page.getByRole('textbox', { name: 'Review topic', exact: true })
      .fill('Should a small local CLI tool cache HTTP responses on disk or in memory? Keep it brief.');
    const started = Date.now();
    await page.getByRole('button', { name: 'Run council', exact: true }).click();
    await page.waitForFunction(() => /VERDICT:/.test(document.getElementById('councilPanel').textContent), null,
      { timeout: RUN_TIMEOUT_MS, polling: 2000 });
    const verdict = (await page.locator('#councilPanel h2', { hasText: 'VERDICT:' }).last().textContent()).trim();
    step(`${verdict} after ${Math.round((Date.now() - started) / 1000)}s`);
    assert.match(verdict, /VERDICT:\s*\S+/, 'verdict text is empty');
    const actions = page.locator('.action-checkbox');
    if (await actions.count()) {
      await actions.first().check();
      assert(await page.locator('.action-item-row').first().evaluate((el) => el.classList.contains('is-done')));
      step(`${await actions.count()} action items; first one ticked off`);
    }
    await page.screenshot({ path: path.join(output, 'uat-result.png'), fullPage: true });

    await page.getByRole('button', { name: 'Replays', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('.replay-run-item').length > 0);
    await page.locator('.replay-run-item').first().click();
    await page.waitForFunction(() => document.querySelectorAll('#replayRunDetail .replay-phase').length >= 2);
    const replayPhases = await page.locator('#replayRunDetail .replay-phase').count();
    step(`Replay opened with ${replayPhases} saved phase outputs`);
    await page.screenshot({ path: path.join(output, 'uat-replay.png') });

    assert.deepEqual(errors, [], 'browser errors during the journey');
    console.log('PASS browser journey');
  } finally {
    await browser.close();
  }
}

journey().catch((error) => { console.error(error.message || error); process.exitCode = 1; });
