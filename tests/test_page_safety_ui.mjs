import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

// 2026-11-03: a 500 from /api/browse/actors was read as data, "data.actors.filter"
// threw, and because every page stays mounted the whole platform went blank.
const page = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');

test('a failed request is an error, never data shaped like a list', () => {
  assert.doesNotMatch(page, /const api = \(p\)=>fetch\(p\)\.then\(r=>r\.json\(\)\);/);
  assert.match(page, /return r\.ok\?body:\{__error:/);
  assert.match(page, /\.catch\(\(\)=>\(\{__error:"The server could not be reached\."\}\)\)/);
});

test('every directory list says it could not load instead of crashing', () => {
  for (const route of ['/api/browse/actors"),[version]', '/api/browse/hubs"),[version]', '/api/browse/events"),[version]',
                       '/api/browse/people"),[version]']) {
    const at = page.indexOf(`useOnce(()=>api("${route}`);
    assert.ok(at > 0, route);
    const guard = page.indexOf('if(data.__error) return html`<${LoadError}', at);
    const nextLoading = page.indexOf('if(!data) return html`<${Loading}/>`;', at);
    assert.ok(guard > nextLoading && guard - nextLoading < 120, `${route} has no error guard after Loading`);
  }
});

test('one page failing never takes the others or the sidebar down', () => {
  for (const name of ['Dashboard', 'Ask Compass', 'Ecosystem Directory', 'Monitor and Update', 'Data Feed',
    'Review Results', 'Explore and Map']) {
    assert.ok(page.includes(`<\${PageBoundary} name="${name}">`), name);
  }
  assert.match(page, /static getDerivedStateFromError\(error\)\{return \{error\};\}/);
});

test('the always-light page keeps light status colors on a computer set to dark mode', () => {
  const block = page.slice(page.indexOf(':root{color-scheme:light;'), page.indexOf('body{background-image:none'));
  for (const v of ['--amber-soft:#fbf0d9', '--amber:#94600a', '--green-soft:#e5f2e3', '--orange-soft:#fdeedd',
    '--red-soft:#fdecec', '--link:#1f5fa8']) {
    assert.ok(block.includes(v), v);
  }
});
