import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const source = await readFile(new URL('../edge/index.js', import.meta.url), 'utf8');
const { digest, equal, validateWindow, createHandler } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const now = Date.now();
const rows = Array.from({length:15}, (_, i) => ({sequence:i,
  capture_start:new Date(now-30000+i*2000).toISOString(),
  capture_end:new Date(now-28000+i*2000).toISOString()}));
assert.equal(validateWindow(rows, now), rows);
assert.throws(() => validateWindow(rows.slice(1),now), /15 complete/);
assert.throws(() => validateWindow(rows,now+10001), /stale/);
assert.throws(() => validateWindow(rows,now-5001), /future/);
assert.throws(() => validateWindow(rows.map((r,i) => i===5 ? {...r,sequence:99} : r),now), /gap/);
assert.throws(() => validateWindow(rows.map((r,i) => i===5 ? {...r,capture_start:new Date(now).toISOString()} : r),now), /gap/);
assert.equal((await digest('test')).length,64);
assert(equal('same','same')); assert(!equal('same','diff')); assert(!equal(undefined,'test'));
const env = (name) => ({SUPABASE_URL:'https://example.supabase.co',SUPABASE_SECRET_KEYS:'{"default":"sb_secret_test"}'})[name];
let calls = 0;
const handler = createHandler(env,async (_url,options) => {
  calls++;
  assert.equal(options.headers.apikey,'sb_secret_test');
  assert.equal(options.headers.authorization,undefined);
  return new Response('[]',{status:200});
});
assert.equal((await handler(new Request('https://example/health'))).status,200);
assert.equal(calls,0);
assert.equal((await handler(new Request('https://example/latest?camera_id=pi-camera'))).status,401);
assert.equal((await handler(new Request('https://example/cleanup',{method:'POST'}))).status,401);
assert.equal((await handler(new Request('https://example/latest?camera_id=pi-camera', {headers:{'x-device-key':'x'.repeat(40)}}))).status,401);
assert.equal((await handler(new Request('https://example/reserve',{method:'POST',body:'x'.repeat(8193)}))).status,413);
console.log('PASS: continuous/stale/future/gapped windows, scoped auth, key headers, request size');
