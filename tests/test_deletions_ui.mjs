import assert from 'node:assert/strict';
import fs from 'node:fs';
import {test} from 'node:test';

import {
  PAGE_TAB, PAGE_TITLE, PERMISSION, RETENTION_DAYS, byDeadline, canRestore, daysLeftLabel, filterDeleted,
  isUrgent, kindLabel, widgetSummary,
} from '../frontend/deletions.js';

const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
const rows = [
  {deletion_id: 'a', name: 'Water Lab', entity_type: 'actor', days_remaining: 22, reason: 'Duplicate', deleted_by: 'Dana'},
  {deletion_id: 'b', name: 'Delta Summit', entity_type: 'event', days_remaining: 2, reason: null, deleted_by: 'Ama'},
  {deletion_id: 'c', name: 'Ada Byron', entity_type: 'person', days_remaining: 0, reason: 'Asked', deleted_by: 'Ama'},
  {deletion_id: 'd', name: 'Desert Hub', entity_type: 'hub', days_remaining: 9, reason: null, deleted_by: 'Dana'},
];

test('Pending Deletion is its own page, for those who may delete', () => {
  assert.equal(PAGE_TITLE, 'Pending Deletion');
  assert.equal(PAGE_TAB, 'deletions');
  assert.equal(PERMISSION, 'records.delete_permanent');
  assert.equal(RETENTION_DAYS, 30);
});

test('the Dashboard card counts them all and shows the three nearest their deadline', () => {
  const {count, soonest} = widgetSummary(rows);
  assert.equal(count, 4);
  assert.deepEqual(soonest.map(r => r.name), ['Ada Byron', 'Delta Summit', 'Desert Hub']);
  assert.deepEqual(widgetSummary([]), {count: 0, soonest: []});
  assert.deepEqual(byDeadline(rows).map(r => r.deletion_id), ['c', 'b', 'd', 'a']);
});

test('days left read plainly; expired ones cannot be restored', () => {
  assert.equal(daysLeftLabel(30), '30 days left');
  assert.equal(daysLeftLabel(1), '1 day left');
  assert.equal(daysLeftLabel(0), 'Removal due now');
  assert.equal(isUrgent(3), true);
  assert.equal(isUrgent(4), false);
  assert.equal(canRestore(rows[2]), false);
  assert.equal(canRestore(rows[1]), true);
  assert.equal(kindLabel('hub'), 'Hub');
});

test('the page filters by type and searches name, reason and who deleted', () => {
  assert.deepEqual(filterDeleted(rows, {entity_type: 'event'}).map(r => r.name), ['Delta Summit']);
  assert.deepEqual(filterDeleted(rows, {search: 'dana'}).map(r => r.name), ['Water Lab', 'Desert Hub']);
  assert.equal(filterDeleted(rows).length, 4);
});

test('Review Results keeps Rejected to itself: no deleted records there', () => {
  const review = read('../frontend/review.js');
  assert.doesNotMatch(review, /deletions\.js|DeletedRecords|Pending Deletion|Pending Permanent Removal/);
  assert.doesNotMatch(read('../frontend/review.css'), /deleted-records/);
});

test('the card is on the Dashboard only for deleters and View all opens the page', () => {
  // 20 Nov 2026: the original Dashboard design for everyone; the card is a panel in its style.
  const dashboard = read('../frontend/dashboard.js');
  assert.match(dashboard, /\$\{permissions && can\(DELETE_PERMISSION\) && html`<\$\{DeletionPanel\}\/>`\}/);
  assert.match(dashboard, /footer=\$\{`View all\$\{more\}`\} onFooter=\$\{\(\) => navigate\(\{tab: DELETIONS_TAB\}\)\}/);
  assert.match(dashboard, /widgetSummary\(state\.rows\)/);
  const panel = read('../frontend/deletions.js');
  assert.match(panel, /onClick=\$\{\(\) => onNavigate\(PAGE_TAB\)\}>View all<\/button>/);
  assert.match(panel, /onClick=\$\{\(\) => onNavigate\("dashboard"\)\}>← Dashboard<\/button>/);
  assert.match(panel, /data-needs=\$\{PERMISSION\} disabled=\$\{!canRestore\(r\)\}/);
  const index = read('../frontend/index.html');
  assert.match(index, /deletions:"records\.delete_permanent"\};/);                 // NAV_NEEDS: page gated
  assert.match(index, /deletions:"Pending Deletion"\};/);                          // its breadcrumb title
  assert.match(index, /\$\{account&&allowed\("deletions"\)&&tab==="deletions"&&html`<div><\$\{PageBoundary\} name="Pending Deletion"><\$\{PendingDeletionPage\} onNavigate=\$\{setTab\}\/>/);
  assert.match(index, /restored from Pending Deletion on the Dashboard until/);
  assert.match(index, /\/api\/browse\/\$\{KIND_PATH\[kind\]\}\/\$\{encodeURIComponent\(r\.id\)\}\/delete/);
});
