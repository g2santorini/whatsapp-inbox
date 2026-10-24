import test from 'node:test';
import assert from 'node:assert/strict';
import {
  SENDRO_IG_CALLBACK, SENDRO_IG_STAGING_FRONTEND_HOST,
  isInstagramStagingHost, canStartInstagramConnection,
  parseInstagramAuthorizationStart, makeInstagramCompletionPayload,
} from './instagramConnectFlow.js';

const NOW = 1792800000000;
const EXPIRY = NOW / 1000 + 300;
const STATE = 'AbCd0123_-'.repeat(5);
const ACCOUNT = 31;
const USER = { id: 7, mfa_enabled: true, role: 'admin' };

function startResponse(modifications = {}) {
  const url = new URL('https://www.instagram.com/oauth/authorize');
  url.searchParams.set('client_id','123456789');
  url.searchParams.set('redirect_uri', SENDRO_IG_CALLBACK);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('scope','instagram_business_basic,instagram_business_manage_messages');
  url.searchParams.set('state', STATE);
  return { authorization_url: url.href, expires_at_epoch: EXPIRY, ...modifications };
}

function permission(modifications = {}) {
  return {
    enabled: true, hostname: SENDRO_IG_STAGING_FRONTEND_HOST,
    tenantId: 10, channelAccountId: ACCOUNT, currentUser: USER,
    hasStartHandler: true, hasFinishHandler: true, ...modifications,
  };
}

test('only exact staging frontend qualifies; production and local dev stay disabled', () => {
  assert.equal(isInstagramStagingHost(SENDRO_IG_STAGING_FRONTEND_HOST),true);
  for (const hostname of [
    'sendro-app.com','inbox.sendro-app.com','localhost','127.0.0.1',
    'sendro-frontend.onrender.com', 'sendro-frontend-staging.onrender.com.evil.com',
    '',undefined,
  ]) {
    assert.equal(isInstagramStagingHost(hostname), false);
    assert.equal(canStartInstagramConnection(permission({ hostname })), false);
  }
});

test('button is OFF by default even on staging with admin MFA and account', () => {
  assert.equal(canStartInstagramConnection(permission({enabled:false})),false);
  assert.equal(canStartInstagramConnection(permission({hasStartHandler:false})),false);
  assert.equal(canStartInstagramConnection(permission({hasFinishHandler:false})),false);
  assert.equal(canStartInstagramConnection(permission({channelAccountId:null})),false);
  assert.equal(canStartInstagramConnection(permission({tenantId:null})),false);
  assert.equal(canStartInstagramConnection(permission({currentUser:null})),false);
  assert.equal(canStartInstagramConnection(permission()),true);
});

test('non-admin, MFA-off, or invalid IDs cannot initiate link even when manually enabled', () => {
  for(const currentUser of [
    { ...USER, role:'operator' }, {...USER, role:'developer'},
    {...USER,role:'viewer'}, {...USER,mfa_enabled:false},
    {...USER,id:0},{...USER,id:'7'},
  ]) {
    assert.equal(canStartInstagramConnection(permission({currentUser})),false);
  }
  for(const tenantId of [0,-1,'10',true,1.4]) {
    assert.equal(canStartInstagramConnection(permission({tenantId})),false);
  }
});

test('valid authorization response returns state only in volatile JS memory', () => {
  const result = parseInstagramAuthorizationStart(startResponse(),NOW);
  assert.equal(result.state, STATE);
  assert.equal(result.expiresAtEpoch, EXPIRY);
  assert.equal(new URL(result.authorizationUrl).origin,'https://www.instagram.com');
  assert.ok(!('code' in result) && !('access_token' in result));
});

test('reject bad or non-Instagram redirect destinations before popup navigation', () => {
  for(const url of [
    'https://evil.example/oauth/authorize',
    'http://www.instagram.com/oauth/authorize',
    'https://instagram.com/oauth/authorize',
    'https://www.instagram.com.evil.com/oauth/authorize',
    'https://www.instagram.com/oauth/authorize/extra',
    'https://user:pass@www.instagram.com/oauth/authorize',
    'https://www.instagram.com/oauth/authorize#x',
    'not-a-url',
  ]) {
    assert.throws(()=>parseInstagramAuthorizationStart(
      startResponse({authorization_url:url}),NOW));
  }
});

test('reject tampered callback URI, scopes, duplicated state and extra parameters', () => {
  const mutations = [
    (url) => url.searchParams.set('redirect_uri','https://attacker.example/callback'),
    (url) => url.searchParams.set('scope','instagram_business_basic'),
    (url) => url.searchParams.append('state','a'.repeat(43)),
    (url) => url.searchParams.set('state','bad-state'),
    (url) => url.searchParams.set('response_type','token'),
    (url) => url.searchParams.set('client_id','not-an-id'),
    (url) => url.searchParams.set('next','https://attacker.example'),
  ];
  for(const mutate of mutations){
    const response = startResponse();
    const url = new URL(response.authorization_url);
    mutate(url);
    assert.throws(()=>parseInstagramAuthorizationStart({
      ...response,authorization_url:url.href,
    },NOW));
  }
});

test('stale, malformed and implausibly extended OAuth expiration denied', () => {
  for(const expires_at_epoch of [
    NOW/1000-1,NOW/1000,NOW/1000+361,0,'1792800300',true,NaN,
  ]) {
    assert.throws(()=>parseInstagramAuthorizationStart(
      startResponse({ expires_at_epoch }),NOW));
  }
});

test('complete request never includes Meta authorization code or access token', () => {
  const parsed=parseInstagramAuthorizationStart(startResponse(),NOW);
  const pending={
    state:parsed.state, expiresAtEpoch:parsed.expiresAtEpoch,
    tenantId:10, channelAccountId:ACCOUNT, userId:7,
  };
  const payload=makeInstagramCompletionPayload(pending,{
    tenantId:10,channelAccountId:ACCOUNT,userId:7,nowMs:NOW+1000,
  });
  assert.deepEqual(payload,{tenant_id:10,channel_account_id:ACCOUNT,state:STATE});
  assert.deepEqual(Object.keys(payload).sort(),['channel_account_id','state','tenant_id']);
});

test('tenant changes, user switching, expiry and account mismatch invalidate completion', () => {
  const pending={ state:STATE,expiresAtEpoch:EXPIRY,
                  tenantId:10,channelAccountId:ACCOUNT,userId:7 };
  const changes=[
    {tenantId:20},{channelAccountId:100},{userId:8},
    {tenantId:0},{tenantId:true},{userId:'7'},
    {nowMs:NOW+400000},
  ];
  for(const change of changes){
    assert.throws(()=>makeInstagramCompletionPayload(pending,{
      tenantId:10,channelAccountId:ACCOUNT,userId:7,nowMs:NOW,
      ...change,
    }));
  }
  assert.throws(()=>makeInstagramCompletionPayload(null,{
    tenantId:10,channelAccountId:ACCOUNT,userId:7,nowMs:NOW,
  }));
});
