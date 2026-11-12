/* The "Connect your AI" box never shows the key in full (v2 item 3).
 *
 * Vite turns src/areas/team/AIKeyBox.tsx into plain JavaScript, React renders it to HTML, and
 * the test looks for the key in that HTML: the same text a screenshot would hold. The Copy
 * buttons must still copy the real lines. Run: npm test */
import assert from 'node:assert/strict';
import { createServer } from 'vite';

const KEY = 'osk_test_only_not_a_real_key_' + 'abcdefghijkl3f9a';
const LINK = { server: 'https://x--os.modal.run/mcp/', key: KEY, url: 'https://x--os.modal.run/mcp/s/' + KEY + '/' };

const vite = await createServer({ configFile: false, root: new URL('..', import.meta.url).pathname, logLevel: 'error',
  server: { middlewareMode: true, hmr: false }, appType: 'custom', optimizeDeps: { noDiscovery: true, include: [] } });
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
let failed = 0;
try {
  const React = await import('react');
  const { renderToStaticMarkup } = await import('react-dom/server');
  const box = await vite.ssrLoadModule('/src/areas/team/AIKeyBox.tsx');
  const L = await vite.ssrLoadModule('/src/lib/ailink.ts');
  const copied = [];
  const html = renderToStaticMarkup(React.createElement(box.AIKeyLines, { name: 'Eva', link: LINK, onCopy: (t) => copied.push(t) }));
  const text = html.replace(/<[^>]+>/g, ' ').replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&#x27;/g, "'");

  test('the key is never on screen in full, not even 8 characters of it', () => {
    assert.ok(!html.includes(KEY), 'the full key is in the box');
    for (let i = 0; i + 8 <= KEY.length - 4; i++) assert.ok(!html.includes(KEY.slice(i, i + 8)), 'a piece of the key is on screen: ' + KEY.slice(i, i + 8));
  });

  test('the box shows the last 4 characters of the key, masked', () => {
    assert.equal(L.maskKey(KEY), '••••••••3f9a');
    assert.ok(text.includes('••••••••3f9a'));
    assert.ok(text.includes('https://x--os.modal.run/mcp/s/••••••••3f9a/'), 'the claude.ai link is masked too');
  });

  test('Claude on the web comes first, with "No sign-in"', () => {
    const order = ['Claude on the web (claude.ai)', 'Claude Code', 'Codex', 'Hermes', 'Another AI tool'].map((t) => text.indexOf(t));
    assert.ok(order.every((i) => i > -1), 'a tool is missing: ' + order);
    assert.deepEqual(order.slice().sort((a, b) => a - b), order, 'tool order: ' + order);
    assert.match(text, /Pick "No sign-in"/);
  });

  test('each Copy button copies the real line, with the full key', () => {
    const lines = L.aiSetup(LINK);
    assert.equal(lines[0].text, LINK.url);
    assert.ok(lines.every((l) => l.text.includes(KEY)), 'every tool line carries the key');
    assert.equal(L.onScreen(lines[1].text, KEY), lines[1].text.replace(KEY, '••••••••3f9a'));
    assert.equal(L.onScreen('no key here', KEY), 'no key here');
    const buttons = (html.match(/aria-label="Copy /g) || []).length;
    assert.equal(buttons, lines.length + 2, 'one Copy per tool, plus the server address and the key');
  });
} catch (e) {
  failed++;
  console.log('FAIL the box did not render\n     ' + (e && (e.stack || e.message)));
}
for (const [name, fn] of tests) {
  try { await fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + (e && e.message)); }
}
await vite.close();
console.log('\n' + (tests.length - failed) + '/' + tests.length + ' passed');
process.exit(failed ? 1 : 0);
