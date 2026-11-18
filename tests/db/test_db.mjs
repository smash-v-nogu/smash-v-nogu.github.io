// Схема базы в памяти (PGlite = настоящий Postgres в WebAssembly): права anon, функции записи с ПИНом.
// Запуск: cd tests/db && npm install && node test_db.mjs
// MIGRATE=1 — сначала старая схема (коммит 409b209, до закрытия записи), потом миграции по шагам, как на рабочей базе.
import { PGlite } from '@electric-sql/pglite';
import { pgcrypto } from '@electric-sql/pglite/contrib/pgcrypto';
import { readFileSync } from 'node:fs';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const read = p => readFileSync(ROOT + p, 'utf8');
// Как в Supabase: роли anon/authenticated, им по умолчанию даны все права на таблицы и функции в public
const PRELUDE = `
  create schema if not exists extensions;
  create role anon nologin; create role authenticated nologin;
  grant usage on schema public, extensions to anon, authenticated;
  alter default privileges in schema public grant all on tables to anon, authenticated;
  alter default privileges in schema public grant all on functions to anon, authenticated;
`;

const db = await PGlite.create({ extensions: { pgcrypto } });
await db.exec(PRELUDE);

const asAnon = async (sql, params = []) => {
  await db.exec('set role anon');
  try { return await db.query(sql, params); } finally { await db.exec('reset role'); }
};
const denied = async (sql, what) => {
  await assert.rejects(asAnon(sql), e => e.code === '42501', what + ': ожидался отказ в доступе');
};
const val = r => (typeof r === 'string' ? JSON.parse(r) : r);
const login = async (name, pin, pid, mode = 'new') =>
  val((await asAnon('select public.bdm_login($1, $2, $3, $4) r', [name, pin, pid, mode])).rows[0].r);
const sync = async (pid, pin, matches = [], best = null) =>
  val((await asAnon('select public.bdm_sync($1, $2, $3::jsonb, $4::jsonb) r', [pid, pin, JSON.stringify(matches), best && JSON.stringify(best)])).rows[0].r);
const room = async (pid, pin, code, status) =>
  val((await asAnon('select public.bdm_room($1, $2, $3, $4) r', [pid, pin, code, status])).rows[0].r);
const one = async sql => (await db.query(sql)).rows[0];
const NOW = Date.now();
const ai = (id, p, extra = {}) => ({ id, t: NOW - 60000, k: 'ai', p, lv: 'hard', win: true, s1: 15, s2: 9, a: null, b: null, w: null, ...extra });
const net = (id, a, b, extra = {}) => ({ id, t: NOW - 60000, k: 'net', a, b, w: a, s1: 15, s2: 12, p: null, lv: null, win: null, ...extra });
const NS = { v: 1, r: 'h', n: 1, dur: 160, ct: 1200, path: 'relay-udp>srflx-udp', sw: [[0, 'srflx-udp>srflx-udp'], [14, 'relay-udp>srflx-udp']], png: [24, 60, 800], ice: [9, 30], fz: 3, fzT: 1.2, gap: 900, rx: 61, fps: 60, hid: 0, buf: 0, ua: 'mac chrome 157' };

if (process.env.MIGRATE) {
  // Старая схема, как на рабочей базе до 17.11.2026: прямая запись открыта
  await db.exec(execSync('git show 409b209:supabase/schema.sql', { cwd: ROOT }).toString());
  await asAnon(`insert into public.matches (id, t, k, p, lv, win, s1, s2) values ('oldmatch01', ${NOW}, 'ai', 'kirill0001', 'easy', true, 15, 3)`);
  const mig = read('supabase/migrations/20261117_writes_need_pin.sql');
  const [step1, step2] = mig.split('-- ===================== ШАГ 2');
  await db.exec(step1);
  // после шага 1 старый клиент ещё пишет напрямую
  await asAnon(`insert into public.players (pid, name) values ('oldclient1', 'Старый') on conflict (pid) do update set name = excluded.name`);
  await asAnon(`delete from public.rooms where code = 'ZZZZ'`);
  await db.exec(step2.slice(step2.indexOf('\n')));  // без хвоста строки-заголовка
  // до миграции умного матч smart база пропускает (клиент отправит его снова), после — записывает
  assert.equal((await login('Ранний', '7777', 'early00001')).ok, true);
  let e = await sync('early00001', '7777', [ai('early00smart', 'early00001', { lv: 'smart' })]);
  assert.equal(e.saved, 0); assert.deepEqual(e.skipped, ['early00smart']);
  await db.exec(read('supabase/migrations/20261118_smart_level.sql'));
  e = await sync('early00001', '7777', [ai('early00smart', 'early00001', { lv: 'smart' })]);
  assert.equal(e.saved, 1, 'после миграции матч smart записался');
  // до миграции сводки сети старый bdm_sync поле net пропускает молча, матч записывается
  e = await sync('early00001', '7777', [net('early00net1', 'early00001', 'someone001', { net: NS })]);
  assert.equal(e.saved, 1, 'старый bdm_sync не спотыкается о поле net');
  await db.exec(read('supabase/migrations/20261118_net_stats.sql'));
  console.log('миграция: шаг 1 не ломает старый клиент, шаг 2 применился, уровень smart открыт');
} else {
  await db.exec(read('supabase/schema.sql'));
}

// 1. Прямая запись закрыта, чтение открыто
await denied(`insert into public.matches (id, t, k, p, lv, win, s1, s2) values ('hackmatch1', 1, 'ai', 'kirill0001', 'hard', true, 15, 0)`, 'insert matches');
await denied(`update public.players set name = 'Взлом'`, 'update players');
await denied(`insert into public.players (pid, name) values ('hacker0001', 'Взлом')`, 'insert players');
await denied(`delete from public.matches`, 'delete matches');
await denied(`insert into public.rooms (code, host_pid, host_name) values ('ABCD', 'hacker0001', 'Взлом')`, 'insert rooms');
await denied(`delete from public.rooms`, 'delete rooms');
await denied(`update public.rooms set host_name = 'Взлом'`, 'update rooms');
await denied(`insert into public.aliases (from_pid, to_pid) values ('hacker0001', 'kirill0001')`, 'insert aliases');
await denied(`select * from public.accounts`, 'select accounts');
await denied(`select * from public.legacy_players`, 'select legacy_players');
await denied(`select public.bdm_auth('kirill0001', '1234')`, 'bdm_auth снаружи');
await denied(`insert into public.net_stats (match_id, pid, d) values ('mynet00001', 'hacker0001', '{}')`, 'insert net_stats');
await denied(`delete from public.net_stats`, 'delete net_stats');
for (const t of ['matches', 'players', 'rooms', 'aliases', 'net_stats']) await asAnon(`select count(*) from public.${t}`);
const left = (await db.query(`select table_name, string_agg(privilege_type, ',' order by privilege_type) p
  from information_schema.role_table_grants where table_schema = 'public' and grantee = 'anon' group by 1 order by 1`)).rows;
assert.deepEqual(left, ['aliases', 'matches', 'net_stats', 'players', 'rooms'].map(t => ({ table_name: t, p: 'SELECT' })), 'у anon остаётся только чтение');

// 2. Регистрация и запись своего
assert.deepEqual(await login('Кирилл', '1234', 'kirill0001'), { ok: true, pid: 'kirill0001', name: 'Кирилл', mode: 'new' });
assert.equal((await login('Вика', '4321', 'vika000001')).ok, true);
let r = await sync('kirill0001', '1234', [
  ai('mine000001', 'kirill0001'),
  net('mynet00001', 'kirill0001', 'vika000001'),
  ai('foreign001', 'vika000001'),                      // чужой
  net('foreignnet', 'vika000001', 'someone001'),       // чужой
  ai('BAD id', 'kirill0001'),                          // кривой id
  ai('future0001', 'kirill0001', { t: NOW + 3 * 86400000 }), // из будущего
  ai('badscore01', 'kirill0001', { s1: 99 }),          // счёт вне границ
  ai('smart00001', 'kirill0001', { lv: 'smart' }),     // против умного
  ai('badlevel01', 'kirill0001', { lv: 'genius' }),    // такого уровня нет
], { smash: 250, rally: 12, train: 40 });
assert.equal(r.ok, true); assert.equal(r.saved, 3);
assert.deepEqual([...r.skipped].sort(), ['BAD id', 'badlevel01', 'badscore01', 'foreign001', 'foreignnet', 'future0001']);
assert.equal((await one(`select lv from matches where id = 'smart00001'`)).lv, 'smart');
assert.deepEqual(await one(`select name, best_smash, best_rally, best_train from players where pid = 'kirill0001'`),
  { name: 'Кирилл', best_smash: 250, best_rally: 12, best_train: 40 });
r = await sync('kirill0001', '1234', [ai('mine000001', 'kirill0001')], { smash: 100, rally: 30, train: 'много' });
assert.equal(r.saved, 0, 'повтор матча не дублируется');
assert.deepEqual(await one(`select best_smash, best_rally, best_train from players where pid = 'kirill0001'`),
  { best_smash: 250, best_rally: 30, best_train: 40 }, 'рекорды только растут, мусор не ломает');
r = await sync('kirill0001', '1234', [], { smash: 9999 });
assert.equal((await one(`select best_smash from players where pid = 'kirill0001'`)).best_smash, 400, 'рекорд упирается в 400');

// 3. Имя в таблице игроков берётся из аккаунта
assert.equal((await login('Кир', '1234', 'kirill0001', 'rename')).ok, true);
await sync('kirill0001', '1234', [], { smash: 0 });
assert.equal((await one(`select name from players where pid = 'kirill0001'`)).name, 'Кир');

// 4. Старый id из другого браузера склеен с аккаунтом — его матчи записываются
assert.equal((await login('Кир', '1234', 'oldpid0001', 'login')).pid, 'kirill0001');
r = await sync('kirill0001', '1234', [ai('fromold001', 'oldpid0001')]);
assert.equal(r.saved, 1, 'матч со старым id аккаунта');

// 5. Чужим ПИНом не записать, перебор блокируется
assert.deepEqual(await sync('vika000001', '1111', [ai('hack000001', 'vika000001')]), { ok: false, err: 'pin' });
assert.deepEqual(await sync('nobody0001', '1234'), { ok: false, err: 'noacc' });
assert.deepEqual(await sync('kirill0001', '12a4'), { ok: false, err: 'bad' });
assert.deepEqual(await asAnon(`select public.bdm_sync('kirill0001', '1234', '{"a":1}'::jsonb, null) r`).then(x => val(x.rows[0].r)), { ok: false, err: 'bad' });
assert.deepEqual(await sync('kirill0001', '1234', Array.from({ length: 201 }, (_, i) => ai('many' + String(i).padStart(6, '0'), 'kirill0001'))), { ok: false, err: 'bad' });
for (let i = 0; i < 6; i++) await sync('vika000001', String(1000 + i));
assert.equal((await one(`select fails from accounts where pid = 'vika000001'`)).fails, 7);
assert.equal((await sync('vika000001', '4321')).ok, true, 'верный ПИН до блока проходит и сбрасывает счётчик');
assert.equal((await one(`select fails from accounts where pid = 'vika000001'`)).fails, 0);
for (let i = 0; i < 8; i++) await sync('vika000001', String(2000 + i));
assert.deepEqual(await sync('vika000001', '4321'), { ok: false, err: 'locked' }, 'после 8 ошибок блок даже с верным ПИНом');
assert.deepEqual(await room('vika000001', '4321', 'ABCD', 'open'), { ok: false, err: 'locked' });
assert.deepEqual(await login('Вика', '4321', 'vika000001', 'login'), { ok: false, err: 'locked' }, 'блок общий со входом');
await db.exec(`update accounts set locked_until = now() - interval '1 second' where pid = 'vika000001'`);
assert.equal((await sync('vika000001', '4321')).ok, true, 'после блока пускает');

// 6. Дыра в bdm_login закрыта: ветка «свой id + новое имя» тоже считает ошибки
for (let i = 0; i < 8; i++) assert.deepEqual(await login('Подбор' + i, String(3000 + i), 'vika000001'), { ok: false, err: 'pin' });
assert.deepEqual(await login('Подбор', '4321', 'vika000001'), { ok: false, err: 'locked' }, 'перебор через id блокируется');
await db.exec(`update accounts set locked_until = null, fails = 0 where pid = 'vika000001'`);

// 7. Комнаты: только своя, одна на игрока, чужую живую не перехватить, старые чистятся
assert.deepEqual(await room('kirill0001', '1234', 'ABCD', 'open'), { ok: true });
assert.deepEqual(await one(`select host_pid, host_name, status from rooms where code = 'ABCD'`), { host_pid: 'kirill0001', host_name: 'Кир', status: 'open' });
assert.deepEqual(await room('vika000001', '4321', 'ABCD', 'open'), { ok: false, err: 'taken' });
assert.deepEqual(await room('vika000001', '4321', 'ABCD', 'gone'), { ok: true });
assert.equal((await one(`select count(*)::int n from rooms where code = 'ABCD'`)).n, 1, 'чужую комнату не убрать');
assert.deepEqual(await room('vika000001', '0000', 'WXYZ', 'open'), { ok: false, err: 'pin' });
assert.deepEqual(await room('kirill0001', '1234', 'abcd', 'open'), { ok: false, err: 'bad' });
assert.deepEqual(await room('kirill0001', '1234', 'EFGH', 'closed'), { ok: false, err: 'bad' });
assert.deepEqual(await room('kirill0001', '1234', 'EFGH', 'open'), { ok: true });
assert.deepEqual((await db.query(`select code from rooms where host_pid = 'kirill0001'`)).rows, [{ code: 'EFGH' }], 'у игрока одна комната');
await db.exec(`update rooms set updated_at = now() - interval '1 minute' where code = 'EFGH'`);
assert.deepEqual(await room('vika000001', '4321', 'EFGH', 'open'), { ok: true }, 'брошенный код можно занять');
await db.exec(`insert into rooms (code, host_pid, host_name, updated_at) values ('OLDR', 'someone001', 'Старый', now() - interval '2 hours')`);
await room('kirill0001', '1234', 'JKLM', 'playing');
assert.equal((await one(`select count(*)::int n from rooms where code = 'OLDR'`)).n, 0, 'комнаты старше часа удаляются');
assert.deepEqual(await room('kirill0001', '1234', 'JKLM', 'gone'), { ok: true });
assert.equal((await one(`select count(*)::int n from rooms where host_pid = 'kirill0001'`)).n, 0);

// 8. Забрать старый профиль по имени (legacy) по-прежнему работает
await db.exec(`insert into legacy_players (pid, name) values ('legacy0001', 'Саша'); insert into players (pid, name, best_smash) values ('legacy0001', 'Саша', 300)`);
assert.deepEqual(await login('саша', '5555', 'newpid0001'), { ok: true, pid: 'legacy0001', name: 'саша', mode: 'claim' });
assert.equal((await sync('legacy0001', '5555', [ai('sasha00001', 'newpid0001')], { smash: 10 })).saved, 1);
assert.equal((await one(`select best_smash from players where pid = 'legacy0001'`)).best_smash, 300);

// 9. Сводка сети: каждый участник пишет свою сторону своего онлайн-матча, одна на игрока и матч
const nets = async id => (await db.query(`select pid, d from net_stats where match_id = $1 order by pid`, [id])).rows;
r = await sync('kirill0001', '1234', [net('netstat001', 'kirill0001', 'vika000001', { net: NS })]);
assert.equal(r.saved, 1);
assert.deepEqual(await nets('netstat001'), [{ pid: 'kirill0001', d: NS }], 'сводка хозяина записалась вместе с матчем');
r = await sync('vika000001', '4321', [net('netstat001', 'kirill0001', 'vika000001', { net: { ...NS, r: 'g', fz: 0 } })]);
assert.equal(r.saved, 0, 'матч уже записал хозяин');
assert.deepEqual((await nets('netstat001')).map(x => [x.pid, x.d.r]), [['kirill0001', 'h'], ['vika000001', 'g']], 'гость дописал свою сторону к готовому матчу');
await sync('kirill0001', '1234', [net('netstat001', 'kirill0001', 'vika000001', { net: { ...NS, fz: 99 } })]);
assert.equal((await nets('netstat001'))[0].d.fz, 3, 'повтор не перезаписывает');
assert.equal((await login('Тим', '2468', 'tim0000001')).ok, true);
r = await sync('tim0000001', '2468', [net('netstat001', 'tim0000001', 'vika000001', { net: NS })]);
assert.equal((await nets('netstat001')).length, 2, 'к чужому матчу свою сводку не приписать, даже назвавшись участником');
r = await sync('kirill0001', '1234', [net('netbig0001', 'kirill0001', 'vika000001', { net: { ...NS, ua: 'x'.repeat(2000) } }), net('netstr0001', 'kirill0001', 'vika000001', { net: 'лагало' }), ai('aiwnet0001', 'kirill0001', { net: NS })]);
assert.equal(r.saved, 3, 'кривая сводка не мешает записать матч');
assert.equal((await one(`select count(*)::int n from net_stats where match_id in ('netbig0001', 'netstr0001', 'aiwnet0001')`)).n, 0, 'слишком большая, не объект и у матча с ИИ — не пишется');

console.log('OK: база' + (process.env.MIGRATE ? ' (через миграцию)' : ''));
