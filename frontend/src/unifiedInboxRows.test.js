import test from 'node:test';
import assert from 'node:assert/strict';
import { buildUnifiedInboxRows } from './unifiedInboxRows.js';

const wa = (id, when) => ({
  id, contact_name: `WhatsApp ${id}`, contact_phone: '+306900000001',
  last_message_at: when, status: 'open',
});
const ig = (id, tenant, account, when, name='Instagram guest') => ({
  id, tenant_id: tenant, channel_account_id: account, contact_name: name,
  account_name: '@sunsetoiasailing', external_customer_id: `guest-${id}`,
  last_message_at: when, status: 'open',
});

test('when Instagram is empty, original WhatsApp data and relative order are preserved', () => {
  const existing = [wa(12,'2026-10-15T13:00:00Z'), wa(13,'2026-10-15T11:00:00Z')];
  const result = buildUnifiedInboxRows({ whatsapp: existing });
  assert.deepEqual(result.map(row => row.id), [12, 13]);
  assert.deepEqual(result.map(row => row.channel), ['whatsapp','whatsapp']);
  assert.equal(existing[0].channel, undefined);
});

test('mixed channel rows sort by message timestamp and use collision-safe keys', () => {
  const result = buildUnifiedInboxRows({
    whatsapp: [wa(1,'2026-10-15T10:00:00Z')],
    instagram: [ig(1,1,1,'2026-10-15T11:00:00Z'),ig(1,2,2,'2026-10-15T09:00:00Z')],
  });
  assert.deepEqual(result.map(row => row.channel), ['instagram','whatsapp','instagram']);
  assert.deepEqual(result.map(row => row.rowKey), ['ig:1:1:1','wa:1','ig:2:2:1']);
});

test('WhatsApp filter never returns Instagram and vice versa', () => {
  const opts = {whatsapp: [wa(2,'2026-10-15T10:00:00Z')], instagram: [ig(2,1,10,'2026-10-15T09:00:00Z')]};
  assert.deepEqual(buildUnifiedInboxRows({...opts,channel:'whatsapp'}).map(r => r.channel),['whatsapp']);
  assert.deepEqual(buildUnifiedInboxRows({...opts,channel:'instagram'}).map(r => r.channel),['instagram']);
});

test('Instagram is excluded from assignment and archive views until supported', () => {
  const opts = {whatsapp:[wa(2,'2026-10-15T10:00:00Z')],instagram:[ig(3,1,10,'2026-10-15T12:00:00Z')]};
  for(const conversationView of ['mine','follow_up','archived']){
    assert.equal(buildUnifiedInboxRows({...opts,conversationView}).filter(r=>r.channel==='instagram').length,0);
  }
});

test('search filters Instagram by name/account scoped ID and excludes archived threads', () => {
  const base=[ig(3,1,10,'2026-10-15T12:00:00Z','George Test'), ig(4,1,10,'2026-10-15T11:00:00Z','Other Guest')];
  const archived = {...ig(5,1,10,'2026-10-15T10:00:00Z'),status:'archived'};
  const opts = {instagram:[...base,archived]};
  assert.deepEqual(buildUnifiedInboxRows({...opts,searchQuery:'george'}).map(r=>r.id),[3]);
  assert.deepEqual(buildUnifiedInboxRows({...opts,searchQuery:'guest-4'}).map(r=>r.id),[4]);
  assert.deepEqual(buildUnifiedInboxRows(opts).map(r=>r.id),[3,4]);
});

test('adapter does not change existing WhatsApp or Instagram input objects', () => {
  const whatsapp=[wa(5,'2026-10-15T10:00:00Z')];
  const instagram=[ig(6,1,2,'2026-10-15T11:00:00Z')];
  const before=JSON.stringify({whatsapp,instagram});
  buildUnifiedInboxRows({whatsapp,instagram});
  assert.equal(JSON.stringify({whatsapp,instagram}),before);
});


test('WhatsApp-only keeps server ordering even when timestamps differ', () => {
  const items = [
    wa(1, '2026-10-15T10:00:00Z'),
    wa(2, '2026-10-15T13:00:00Z'),
  ];
  const result = buildUnifiedInboxRows({ whatsapp: items, instagram: [], channel: 'all' });
  assert.deepEqual(result.map(item => item.id), [1, 2]);
  assert.deepEqual(buildUnifiedInboxRows({ whatsapp: items, instagram: [], channel: 'whatsapp' }).map(item => item.id), [1, 2]);
});
