import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {createDateInput, isoFromUs, usDate, usDateTime} from '../frontend/dates.js';

test('dates read MM/DD/YYYY, and text that is not a day is never made into one', () => {
  assert.equal(usDate('2026-10-26'), '10/26/2026');
  assert.equal(usDate('2026-10-26 17:38:00+00'), usDate(new Date('2026-10-26T17:38:00Z')));
  assert.equal(usDate(new Date(2027, 0, 5)), '01/05/2027');
  // A month alone stays a month: no invented first day.
  assert.equal(usDate('March 2026'), 'March 2026');
  assert.equal(usDate('Spring 2027'), 'Spring 2027');
  assert.equal(usDate(null), '');
  assert.match(usDateTime('2026-10-26T17:38:00'), /^10\/26\/2026, 5:38 PM$/);
});

test('a typed US date becomes ISO only when it is a whole, real date', () => {
  assert.equal(isoFromUs('10/26/2026'), '2026-10-26');
  assert.equal(isoFromUs('4/2/2027'), '2027-04-02');
  assert.equal(isoFromUs('2027-04-02'), '2027-04-02');
  for (const bad of ['02/30/2026', '13/01/2026', '10/26/26', '10/26', '', 'tomorrow']) {
    assert.equal(isoFromUs(bad), '', bad);
  }
});

test('every calendar on the platform is the MM/DD/YYYY date field', () => {
  const sources = ['discovery.js', 'datafeed.js', 'index.html', 'review.js']
    .map(name => fs.readFileSync(new URL(`../frontend/${name}`, import.meta.url), 'utf8'));
  // The browser's own date field follows the computer's language; only the
  // hidden picker inside DateInput (dates.js) may use it.
  for (const source of sources) assert.doesNotMatch(source, /type="date"/);
  const html = (strings, ...values) => strings.reduce((out, s, i) => out + s + (values[i] ?? ''), '');
  const DateInput = createDateInput({html, useState: init => [typeof init === 'function' ? init() : init, () => {}],
    useEffect() {}});
  const out = DateInput({value: '2027-04-02', onChange() {}});
  assert.match(out, /placeholder="MM\/DD\/YYYY"/);
  assert.match(out, /value=04\/02\/2027/);
  assert.match(out, /Open calendar/);
});
