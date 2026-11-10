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
  for (const source of sources) {
    assert.doesNotMatch(source, /type="date"/);
    assert.doesNotMatch(source, /type=\$\{[^}]*["']date["']/);  // chosen in code, e.g. t==="date"?"date":"text"
  }
  const html = (strings, ...values) => strings.reduce((out, s, i) => out + s + (values[i] ?? ''), '');
  const DateInput = createDateInput({html, useState: init => [typeof init === 'function' ? init() : init, () => {}],
    useEffect() {}});
  const out = DateInput({value: '2027-04-02', onChange() {}});
  assert.match(out, /placeholder=MM\/DD\/YYYY/);
  // A form can ask for a choice instead (Monitor and Update: "Select a date…").
  assert.match(DateInput({value: '', onChange() {}, placeholder: 'Select a date…'}), /placeholder=Select a date…/);
  assert.match(out, /value=04\/02\/2027/);
  assert.match(out, /Open calendar/);
});

test("the calendar is COMPASS's own, in English, Sunday first, never the browser's", async () => {
  const {MONTHS, WEEKDAYS, monthGrid, shiftMonth} = await import('../frontend/dates.js');
  assert.equal(MONTHS[10], 'November');
  assert.deepEqual(WEEKDAYS, ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']);
  const nov = monthGrid(2026, 10);                 // 1 Nov 2026 is a Sunday
  assert.equal(nov[0][0], '2026-11-01');
  assert.equal(nov.flat().filter(Boolean).length, 30);
  assert.ok(nov.every(week => week.length === 7));
  const feb = monthGrid(2027, 1);                  // 1 Feb 2027 is a Monday
  assert.equal(feb[0][0], null);
  assert.equal(feb[0][1], '2027-02-01');
  assert.deepEqual(shiftMonth({year: 2026, month: 11}, 1), {year: 2027, month: 0});
  assert.deepEqual(shiftMonth({year: 2027, month: 0}, -1), {year: 2026, month: 11});
  const source = fs.readFileSync(new URL('../frontend/dates.js', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /type="date"|showPicker/);
});

test('Directory Edit saves through the backend writer; Delete stays for organizations (10 Nov 2026)', () => {
  const page = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(page, /EDIT_SAVES/);
  assert.doesNotMatch(page, /Saving isn't connected yet/);
  assert.match(page, /\$\{!editing&&!deleting&&!removed&&html`<button class="example" type="button" onClick=\$\{\(\)=>\{setSaved\(null\);setEditing\(true\);\}\}>Edit<\/button>`\}/);
  assert.match(page, /fetch\(`\/api\/browse\/\$\{EDIT_PATHS\[kind\]\}\/\$\{record\.id\}\/edit`/);
  assert.match(page, /const EDIT_PATHS=\{actor:"actors",event:"events",person:"people",hub:"hubs"\};/);
  assert.match(page, /\$\{kind==="actor"&&!editing&&!deleting&&!removed&&html`<button class="example danger"/);
  // Only changed boxes are sent; read-only boxes never are.
  assert.match(page, /editable\.filter\(\(\[k\]\)=>draft\[k\]!==start\[k\]\)/);
  // Every tab keeps the saved values on screen and reads its list again.
  assert.equal((page.match(/onSaved=\$\{v=>\{setSel\(x=>\(\{\.\.\.x,\.\.\.v\}\)\);setVersion\(n=>n\+1\);\}\}/g) || []).length, 4);
});

test('people have a GHUS Notes box in Edit and on their profile (migration 625)', () => {
  const page = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  assert.match(page, /const HAS_NOTES=\{actor:true,event:true,person:true\};/);
  assert.match(page, /kind==="person"\s*\?"Where GHUS met them/);
  const person = page.slice(page.indexOf('kind="person" r='), page.indexOf('kind="person" r=') + 1600);
  assert.match(person, /title="GHUS Notes">\$\{sel\.ghus_notes\?/);
});
