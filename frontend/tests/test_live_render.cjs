// Exercise the actual component with synthetic data; no account or backend.
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const assert = require('node:assert/strict');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const source = path.resolve('src');
const original = Module._resolveFilename;
Module._resolveFilename = function(request, parent, ...rest) {
  if (request.startsWith('@/')) request = path.join(source, request.slice(2));
  return original.call(this, request, parent, ...rest);
};
for (const ext of ['.ts', '.tsx']) {
  require.extensions[ext] = function(mod, filename) {
    const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      fileName: filename,
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    });
    mod._compile(result.outputText, filename);
  };
}
const { LiveTrading } = require(path.join(source, 'components/LiveTrading.tsx'));
function render(positions, realised = null) {
  return renderToStaticMarkup(React.createElement(LiveTrading, {
    initial: { stamped_at: new Date().toISOString(), positions, realised, unreachable: [] },
  }));
}
function floating(html) {
  const part = html.slice(html.indexOf('>شناور<'), html.indexOf('>پوزیشن باز<'));
  return part.replace(/<[^>]*>/g, '');
}
let count = 0;
function check(name, fn) { fn(); count++; console.log('PASS ' + name); }
check('missing positions are unknown', () => {
  const h = render(null); assert(h.includes('وضعیت پوزیشن‌ها خوانده نشده است.'));
  assert(!h.includes('هیچ پوزیشن بازی نیست.')); assert(floating(h).includes('—'));
});
check('unavailable empty payload does not assert an empty account', () => {
  const h = render({ available: false, positions: [] });
  assert(!h.includes('هیچ پوزیشن بازی نیست.')); assert(floating(h).includes('—'));
});
check('confirmed empty account can display zero', () => {
  const h = render({ available: true, positions: [] });
  assert(h.includes('هیچ پوزیشن بازی نیست.')); assert(floating(h).includes('0.00'));
});
check('missing position profit does not manufacture zero', () => {
  assert(floating(render({ positions: [{ symbol: 'TEST' }] })).includes('—'));
});
check('known loss is preserved', () => {
  assert(floating(render({ positions: [{ symbol: 'TEST', profit: -12.5 }] })).includes('-12.50'));
});
check('explicit zero floating remains known', () => {
  assert(floating(render({ positions: [{ symbol: 'TEST' }], floating: 0 })).includes('0.00'));
});
check('missing costs and history are stated independently', () => {
  const h = render({ positions: [] }, { available: true, net: null, window_days: 1 });
  assert(h.includes('کامل بودن تاریخچه تأیید نشده است.'));
  assert(h.includes('کامل بودن هزینه‌های ثبت‌شده تأیید نشده است.'));
  assert(h.includes('1 روز اخیر')); assert(!h.includes('محقق‌شده امروز'));
});
check('known fees do not imply complete history', () => {
  const h = render({ positions: [] }, { available: true, net: 0, fees_available: true, history_complete: null });
  assert(!h.includes('کامل بودن هزینه‌های ثبت‌شده تأیید نشده است.'));
  assert(h.includes('کامل بودن تاریخچه تأیید نشده است.'));
});
console.log(JSON.stringify({passed: count, failed: 0, synthetic: true}));
