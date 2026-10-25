const assert = require('node:assert/strict');
const test = require('node:test');
const postcss = require('postcss');
const tailwind = require('tailwindcss');

test('patched CSS dependencies retain responsive, RTL and arbitrary variants', async () => {
  const result = await postcss([tailwind({
    content: [{ raw: '<div class="flex hover:bg-blue-500 md:grid-cols-2 rtl:text-right [&>span]:font-bold"></div>' }],
    corePlugins: { preflight: false },
  })]).process('@tailwind utilities;', { from: undefined });
  const declarations = [];
  result.root.walkDecls((d) => declarations.push([d.prop, d.value]));
  for (const pair of [['display', 'flex'], ['text-align', 'right'], ['font-weight', '700'], ['grid-template-columns', 'repeat(2, minmax(0, 1fr))']]) {
    assert.ok(declarations.some(([prop, value]) => prop === pair[0] && value === pair[1]), `missing ${pair.join(': ')}`);
  }
  const selectors = [];
  result.root.walkRules((r) => selectors.push(r.selector));
  assert.ok(selectors.some((s) => s.includes(':hover')));
  assert.ok(selectors.some((s) => s.includes('span')));
  assert.ok(selectors.some((s) => s.includes('rtl')));
  assert.match(result.css, /@media\s*\(min-width: 768px\)/);
});
