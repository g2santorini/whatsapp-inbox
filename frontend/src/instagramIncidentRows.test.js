import test from 'node:test';
import assert from 'node:assert/strict';

import { buildIncidentCenterRows } from './instagramIncidentRows.js';

const safe = {
  code: 'quarantined_deliveries',
  episode: 1,
  observations: 3,
  is_active: true,
  dispatch_status: 'accepted',
};

test('normalizes only known safe in-app incident fields', () => {
  const result = buildIncidentCenterRows([{
    ...safe,
    guest_message: 'PRIVATE CUSTOMER TEXT',
    customer_id: 'SECRET-CUSTOMER',
    sender: 'PRIVATE',
    ciphertext: 'SECRET-CIPHERTEXT',
    token: 'SECRET-TOKEN',
    url: 'https://private.invalid',
  }]);
  assert.deepEqual(result, [{
    code: 'quarantined_deliveries',
    label: 'Instagram deliveries need review',
    episode: 1,
    observations: 3,
    active: true,
    status: 'accepted',
    canReview: true,
  }]);
  const serialized = JSON.stringify(result);
  for (const secret of [
    'PRIVATE CUSTOMER', 'SECRET-CUSTOMER',
    'SECRET-CIPHERTEXT', 'SECRET-TOKEN', 'private.invalid',
  ]) assert.equal(serialized.includes(secret), false);
});

test('unknown codes, invalid versions and fake states fail closed', () => {
  assert.deepEqual(buildIncidentCenterRows(null), []);
  assert.deepEqual(buildIncidentCenterRows([
    { ...safe, code: 'customer-secret-as-code' },
    { ...safe, episode: 0 },
    { ...safe, observations: Number.NaN },
    { ...safe, is_active: 'true' },
    { ...safe, dispatch_status: 'delete_all' },
  ]), []);
});

test('the UI only offers a review action after transport acceptance', () => {
  assert.equal(buildIncidentCenterRows([safe])[0].canReview, true);
  for (const state of ['pending', 'leased', 'failed', 'acknowledged']) {
    assert.equal(buildIncidentCenterRows([{
      ...safe, dispatch_status: state,
    }])[0].canReview, false);
  }
});

test('never displays arbitrarily large lists or arbitrary server text', () => {
  const results = buildIncidentCenterRows(Array.from({ length: 75 },
    (_, index) => ({ ...safe, episode: index + 1, notes: 'guest secret' })));
  assert.equal(results.length, 20);
  assert.equal(JSON.stringify(results).includes('guest secret'), false);
});
