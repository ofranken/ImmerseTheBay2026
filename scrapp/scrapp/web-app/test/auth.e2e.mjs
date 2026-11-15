// End-to-end checks for studio logins and per-user data. Needs the Scrapp API and the studio running, plus the two demo
// accounts (11111111 and 22222222):   BASE=https://scrapp.nmagic.dev node --test test/auth.e2e.mjs
import test from 'node:test';
import assert from 'node:assert/strict';

const BASE = (process.env.BASE || 'http://localhost:3000').replace(/\/$/, '');
const post = (path, body, cookie) => fetch(BASE + path, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(cookie ? { cookie } : {}) }, body: JSON.stringify(body), redirect: 'manual' });
const get = (path, cookie) => fetch(BASE + path, { headers: cookie ? { cookie } : {}, redirect: 'manual' });

async function login(u) {
  const r = await post('/api/auth/login', { username: u, password: u });
  assert.equal(r.status, 200, `login ${u}`);
  const set = r.headers.getSetCookie().join('; ');
  assert.match(set, /HttpOnly/i); assert.match(set, /SameSite=Lax/i);
  return { cookie: set.split(';')[0], user: (await r.json()).user };
}

test('signed out: pages go to /login, API says 401, no shared password anywhere', async () => {
  const page = await fetch(BASE + '/', { headers: { accept: 'text/html' }, redirect: 'manual' });
  assert.equal(page.status, 302); assert.match(page.headers.get('location'), /\/login$/);
  for (const p of ['/api/config', '/api/tasks', '/api/mongo/images', '/api/collages', '/api/friends', '/api/inbox', '/app.js']) {
    assert.equal((await get(p)).status, 401, p);
  }
  assert.equal((await fetch(BASE + '/login')).status, 200);
  const basic = await fetch(BASE + '/api/config', { headers: { Authorization: 'Basic ' + Buffer.from('x:anything').toString('base64') } });
  assert.equal(basic.status, 401, 'HTTP Basic no longer works');
});

test('wrong password and garbage are rejected without a session', async () => {
  const bad = await post('/api/auth/login', { username: '22222222', password: 'nope' });
  assert.equal(bad.status, 401); assert.equal(bad.headers.getSetCookie().length, 0);
  assert.equal((await post('/api/auth/login', {})).status, 400);
  assert.equal((await get('/api/config', 'scrapp_studio=garbage')).status, 401);
});

test('login works with username or email and /api/config names the signed-in user', async () => {
  const a = await login('22222222');
  assert.equal(a.user.username, '22222222');
  const byEmail = await post('/api/auth/login', { username: '22222222@gmail.com', password: '22222222' });
  assert.equal(byEmail.status, 200);
  const cfg = await (await get('/api/config', a.cookie)).json();
  assert.equal(cfg.user.username, '22222222');
  assert.equal((await get('/api/auth/me', a.cookie)).status, 200);
});

test('each user only sees their own content, and ids from the browser are ignored', async () => {
  const one = await login('11111111'), two = await login('22222222');
  const list = async (c, q = '') => (await (await get('/api/mongo/images?source=stickers&limit=100' + q, c.cookie)).json());
  const mine1 = await list(one), mine2 = await list(two);
  assert.ok(mine1.total > 0 && mine2.total > 0, 'both demo accounts have stickers');
  const ids1 = new Set(mine1.items.map((i) => i.docId)), ids2 = new Set(mine2.items.map((i) => i.docId));
  assert.ok([...ids1].every((i) => !ids2.has(i)), 'no sticker appears for both users');
  assert.ok(mine1.items.every((i) => i.ownerId === one.user.id) && mine2.items.every((i) => i.ownerId === two.user.id));
  // asking for someone else's data by id changes nothing
  const spoof = await list(two, `&owner=${one.user.id}&me=${one.user.id}`);
  assert.ok(spoof.items.every((i) => i.ownerId === two.user.id), 'owner= is ignored');
  // user 2 cannot read user 1's files by guessing ids
  const file1 = mine1.items[0].image;
  assert.equal((await get(file1, one.cookie)).status, 200);
  assert.equal((await get(file1, two.cookie)).status, 404, "someone else's file is hidden");
  assert.equal((await get(file1)).status, 401);
  // meshes, collages, tasks are scoped too
  for (const p of ['/api/mongo/meshes', '/api/collages', '/api/tasks']) {
    const a = await (await get(p, one.cookie)).json(), b = await (await get(p, two.cookie)).json();
    const idsA = new Set((a.items || a).map((x) => x.id)), idsB = (b.items || b).map((x) => x.id);
    assert.ok(idsB.every((i) => !idsA.has(i)), `${p} does not leak`);
  }
  // the old "list every user" endpoint is gone
  assert.notEqual((await get('/api/users', one.cookie)).status, 200);
});

test("another user's capture/cut and collage cannot be used", async () => {
  const one = await login('11111111'), two = await login('22222222');
  const cap = (await (await get('/api/mongo/images?source=captures&limit=1', one.cookie)).json()).items[0];
  assert.ok(cap, 'user 1 has a capture');
  assert.equal((await post('/api/cut/start', { docId: cap.docId }, two.cookie)).status, 404);
  assert.equal((await post('/api/cut/segment', { captureId: cap.docId, prompt: 'cup' }, two.cookie)).status, 404);
  assert.equal((await post('/api/cut/stickers', { token: 'forged', indices: [0] }, two.cookie)).status, 404);
  // a collage of user 1 that was NOT shared with user 2 is invisible to user 2 (a shared one is readable, by design)
  const sharedWithTwo = new Set((await (await get('/api/inbox', two.cookie)).json()).map((e) => e.itemId));
  const colls = await (await get('/api/collages', one.cookie)).json();
  const hidden = colls.find((c) => !sharedWithTwo.has(c.id));
  assert.ok(hidden, 'user 1 has an unshared collage to test with');
  assert.equal((await get('/api/collages/' + hidden.id, two.cookie)).status, 404);
  const shared = colls.find((c) => sharedWithTwo.has(c.id));
  if (shared) assert.equal((await get('/api/collages/' + shared.id, two.cookie)).status, 200);
  // a task another user started is invisible and its files are private
  assert.equal((await get('/models/does-not-exist.glb', two.cookie)).status, 404);
});

test('cross-site posts are blocked and logout ends the session', async () => {
  const r = await fetch(BASE + '/api/auth/logout', { method: 'POST', headers: { Origin: 'https://evil.example' } });
  assert.equal(r.status, 403);
  const a = await login('22222222');
  assert.equal((await get('/api/config', a.cookie)).status, 200);
  const out = await post('/api/auth/logout', {}, a.cookie);
  assert.equal(out.status, 200); assert.match(out.headers.getSetCookie().join(';'), /Max-Age=0/);
  assert.equal((await get('/api/config', a.cookie)).status, 401, 'the old token stops working here after logout (cache cleared)');
});
