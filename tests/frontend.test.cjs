const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function runtime(files = ['state.js', 'stream_handler.js']) {
  const elements = new Map();
  const writes = [];
  const context = vm.createContext({
    console, URL, Headers, TextDecoder, TextEncoder, ReadableStream, AbortController, FormData,
    setTimeout, clearTimeout, performance,
    window: { location: { href: 'http://localhost:8765/', origin: 'http://localhost:8765' } },
    document: { getElementById: id => elements.get(id) || null },
    localStorage: { getItem: () => null, setItem: (...args) => writes.push(args), removeItem: () => {} },
    fetch: async () => ({ status: 200 }),
  });
  for (const filename of files) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/council/static/js', filename), 'utf8'), context);
  }
  return { context, elements, writes, evaluate: source => vm.runInContext(source, context) };
}

test('cloud keys stay in memory and clearing removes them from requests', () => {
  const app = runtime();
  app.elements.set('keyOpenAI', { value: 'test-cloud-key' });
  app.evaluate('persistCloudKeys()');
  assert.equal(app.evaluate('cloudKeyHeaders()["X-OpenAI-API-Key"]'), 'test-cloud-key');
  assert.equal(app.writes.length, 0);
  app.context.showToast = () => {};
  app.evaluate('clearCloudKeys()');
  assert.equal(app.evaluate('cloudKeyHeaders()["X-OpenAI-API-Key"]'), undefined);
});

test('server credentials accompany only same-origin nonredirecting requests', async () => {
  const app = runtime();
  app.elements.set('serverApiKey', { value: 'test-server-key' });
  let request;
  app.context.fetch = async (url, options) => { request = { url, options }; return { status: 200 }; };
  await app.evaluate('councilFetch("/runs", {headers: {"X-OpenAI-API-Key": "test-cloud-key"}})');
  assert.equal(request.options.headers.get('X-API-Key'), 'test-server-key');
  assert.equal(request.options.headers.get('X-OpenAI-API-Key'), 'test-cloud-key');
  assert.equal(request.options.redirect, 'error');
  await assert.rejects(app.evaluate('councilFetch("https://attacker.example/")'), /stay on this server/);
});

test('SSE preserves split UTF-8, CRLF, multiple frames and final buffered event', async () => {
  const app = runtime();
  const events = [];
  const bytes = new TextEncoder().encode('data: {"chunk":"caf\u00e9"}\r\n\r\ndata:{"type":"done"}');
  app.context.response = { body: new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i++) controller.enqueue(bytes.slice(i, i + 1));
    controller.close();
  } }) };
  app.context.onEvent = event => events.push(event);
  await app.evaluate('readSse(response, onEvent)');
  assert.deepEqual(JSON.parse(JSON.stringify(events)), [{ chunk: 'caf\u00e9' }, { type: 'done' }]);
});

test('token bursts batch rendering and member completion flushes authoritative text', async () => {
  const app = runtime();
  let renders = 0;
  const body = { style: {}, set innerHTML(value) { this.content = value; renders++; } };
  const card = { isConnected: true, querySelector: selector => selector === '.card-body' ? body : null };
  app.context.card = card;
  app.context.renderMarkdown = text => text;
  app.evaluate('thinkingCards["architect-1"] = card');
  for (let i = 0; i < 50; i++) app.evaluate('handleEvent({type:"member_token",member:"architect",chunk:"a"}, null)');
  assert.equal(renders, 0);
  await new Promise(resolve => setTimeout(resolve, 120));
  assert.equal(renders, 1);
  assert.equal(body.content, 'a'.repeat(50));
  app.evaluate('handleEvent({type:"member_done",member:"architect",full_text:"final answer"}, null)');
  assert.equal(body.content, 'final answer');
  assert.equal(app.evaluate('pendingTokenRenders.size'), 0);
});

test('ending an aborted run cannot clear a newer run controller', async () => {
  const app = runtime();
  const classes = new Set();
  const button = { disabled: false, classList: { add: value => classes.add(value), remove: value => classes.delete(value) } };
  app.elements.set('launchBtn', button);
  app.elements.set('topicText', { value: 'review' });
  app.elements.set('councilPanel', {});
  app.context.refreshPreflight = async () => app.evaluate('preflightState = {ready:true}');
  app.context.settledPreflight = async () => app.evaluate('preflightState');
  app.context.renderLoadingState = () => {};
  app.context.showToast = () => {};
  app.context.handleEvent = () => {};
  app.context.readSse = async (response, onEvent) => onEvent({ type: 'done' });
  const requests = [];
  app.context.councilFetch = () => new Promise((resolve, reject) => requests.push({ resolve, reject }));
  const first = app.evaluate('launchCouncil()');
  await new Promise(resolve => setImmediate(resolve));
  app.evaluate('stopActiveRun()');
  const second = app.evaluate('launchCouncil()');
  await new Promise(resolve => setImmediate(resolve));
  const current = app.evaluate('activeCouncilAbortController');
  requests[0].reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
  await first;
  assert.equal(app.evaluate('activeCouncilAbortController'), current);
  assert.equal(classes.has('btn-danger'), true);
  requests[1].resolve({ ok: true });
  await second;
  assert.equal(app.evaluate('activeCouncilAbortController'), null);
  assert.equal(classes.has('btn-danger'), false);
});

test('launch preflight settles on the newest roster check instead of a cleared state', async () => {
  const app = runtime(['state.js', 'api.js', 'stream_handler.js']);
  app.elements.set('preflightBox', { innerHTML: '' });
  const pending = [];
  app.context.fetch = () => new Promise(resolve => pending.push(resolve));
  const reply = { ok: true, status: 200, json: async () => ({ ready: true, missing: [], warnings: [] }) };
  app.evaluate('refreshPreflight()');  // the launch's own check
  app.evaluate('refreshPreflight()');  // a roster edit lands meanwhile
  const settled = app.evaluate('settledPreflight()');
  await new Promise(resolve => setTimeout(resolve, 0));
  pending[0](reply);  // the superseded check finishes first and is ignored
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(app.evaluate('preflightState'), null);
  pending[1](reply);
  assert.equal((await settled).ready, true);
});
