-- Запись в общую таблицу — только своё и только с ПИНом (17.11.2026)
--
-- Было: с публичным ключом любой мог переименовать любого игрока, поставить ему рекорд,
-- добавить матч с кем угодно, удалить чужую комнату. А ветка bdm_login «вход по своему id»
-- проверяла ПИН без счётчика ошибок, так что ПИН любого игрока подбирался перебором.
--
-- Порядок на рабочей базе:
--   ШАГ 1 (ниже) -> задеплоить клиент, который пишет через bdm_sync / bdm_room -> ШАГ 2.
-- Старые клиенты после шага 2 не смогут писать, но их матчи остаются в очереди
-- в браузере и уйдут, как только откроется новая версия страницы.

-- ===================== ШАГ 1: новые функции (старый клиент продолжает работать) =====================

-- Проверка ПИНа для функций записи: тот же счётчик ошибок и блок на 15 минут, что у bdm_login.
-- Ответ: ok | bad | noacc | locked | pin. Снаружи не вызывается.
create or replace function public.bdm_auth(p_pid text, p_pin text)
returns text language plpgsql security definer set search_path = public, extensions as $fn$
declare
  a public.accounts;
begin
  if coalesce(p_pin, '') !~ '^[0-9]{4}$' or coalesce(p_pid, '') !~ '^[a-z0-9]{6,16}$' then return 'bad'; end if;
  select * into a from accounts where pid = p_pid for update;
  if not found then return 'noacc'; end if;
  if a.locked_until is not null and a.locked_until > now() then return 'locked'; end if;
  if a.pin_hash <> crypt(p_pin, a.pin_hash) then
    update accounts set fails = fails + 1,
      locked_until = case when fails + 1 >= 8 then now() + interval '15 minutes' else null end
    where pid = a.pid;
    return 'pin';
  end if;
  if a.fails <> 0 or a.locked_until is not null then update accounts set fails = 0, locked_until = null where pid = a.pid; end if;
  return 'ok';
end
$fn$;
revoke all on function public.bdm_auth(text, text) from public, anon, authenticated;

-- Вход: ветка «аккаунт с этим id уже есть, меняем имя» теперь тоже считает ошибки ПИНа
create or replace function public.bdm_login(p_name text, p_pin text, p_pid text, p_mode text default 'new')
returns json language plpgsql security definer set search_path = public, extensions as $fn$
declare
  a public.accounts;
  nm text := trim(coalesce(p_name, ''));
  md text := coalesce(p_mode, 'new');
  legacy text;
  target text;
  st text;
begin
  if coalesce(p_pin, '') !~ '^[0-9]{4}$' or coalesce(p_pid, '') !~ '^[a-z0-9]{6,16}$' or char_length(nm) not between 1 and 16
     or md not in ('new', 'login', 'rename') then
    return json_build_object('ok', false, 'err', 'bad');
  end if;

  select * into a from accounts where lower(name) = lower(nm);
  if found then
    if md = 'rename' and a.pid <> p_pid then return json_build_object('ok', false, 'err', 'taken'); end if;
    if a.locked_until is not null and a.locked_until > now() then return json_build_object('ok', false, 'err', 'locked'); end if;
    if a.pin_hash <> crypt(p_pin, a.pin_hash) then
      update accounts set fails = fails + 1,
        locked_until = case when fails + 1 >= 8 then now() + interval '15 minutes' else null end
      where pid = a.pid;
      return json_build_object('ok', false, 'err', case when md = 'login' then 'pin' else 'taken' end);
    end if;
    update accounts set fails = 0, locked_until = null, name = case when md = 'rename' then nm else name end where pid = a.pid;
    if p_pid <> a.pid and not exists (select 1 from accounts where pid = p_pid) then
      insert into aliases (from_pid, to_pid) values (p_pid, a.pid)
        on conflict (from_pid) do update set to_pid = excluded.to_pid;
    end if;
    return json_build_object('ok', true, 'pid', a.pid, 'name', case when md = 'rename' then nm else a.name end, 'mode', 'login');
  end if;

  if md = 'login' then return json_build_object('ok', false, 'err', 'noname'); end if;

  if exists (select 1 from accounts where pid = p_pid) then
    st := bdm_auth(p_pid, p_pin);
    if st <> 'ok' then return json_build_object('ok', false, 'err', case when st = 'locked' then 'locked' else 'pin' end); end if;
    update accounts set name = nm where pid = p_pid;
    return json_build_object('ok', true, 'pid', p_pid, 'name', nm, 'mode', 'rename');
  end if;

  select l.pid into legacy from legacy_players l
    where lower(l.name) = lower(nm)
      and not exists (select 1 from accounts x where x.pid = l.pid)
    order by exists (select 1 from matches m where m.p = l.pid or m.a = l.pid or m.b = l.pid) desc,
      coalesce((select pl.best_smash from players pl where pl.pid = l.pid), 0) desc
    limit 1;
  target := coalesce(legacy, p_pid);
  insert into accounts (pid, name, pin_hash) values (target, nm, crypt(p_pin, gen_salt('bf')));
  insert into aliases (from_pid, to_pid)
    select l.pid, target from legacy_players l
    where lower(l.name) = lower(nm) and l.pid <> target
      and not exists (select 1 from accounts x where x.pid = l.pid)
    on conflict (from_pid) do nothing;
  if p_pid <> target then
    insert into aliases (from_pid, to_pid) values (p_pid, target) on conflict (from_pid) do update set to_pid = excluded.to_pid;
  end if;
  return json_build_object('ok', true, 'pid', target, 'name', nm, 'mode', case when legacy is null then 'new' else 'claim' end);
end
$fn$;
revoke all on function public.bdm_login(text, text, text, text) from public;
grant execute on function public.bdm_login(text, text, text, text) to anon, authenticated;

-- Синхронизация своего. p_matches — массив строк как в таблице matches (до 200): записываются только матчи,
-- где игрок участвует своим id или старым, склеенным с аккаунтом; чужие и кривые пропускаются.
-- p_best — { smash, rally, train }: рекорды только растут, имя всегда берётся из аккаунта.
-- Ответ: { ok: true, saved, skipped: [id…] } или { ok: false, err: bad | noacc | locked | pin }
create or replace function public.bdm_sync(p_pid text, p_pin text, p_matches jsonb default '[]'::jsonb, p_best jsonb default null)
returns json language plpgsql security definer set search_path = public, extensions as $fn$
declare
  st text := bdm_auth(p_pid, p_pin);
  ms jsonb := coalesce(p_matches, '[]'::jsonb);
  me text[];
  m jsonb;
  n int;
  saved int := 0;
  skipped text[] := '{}';
  max_t bigint := (extract(epoch from now()) * 1000)::bigint + 86400000;  -- не из будущего (сутки на кривые часы)
  num constant text := '^[0-9]{1,4}$';
begin
  if st <> 'ok' then return json_build_object('ok', false, 'err', st); end if;
  if jsonb_typeof(ms) <> 'array' or jsonb_array_length(ms) > 200 or (p_best is not null and jsonb_typeof(p_best) <> 'object') then
    return json_build_object('ok', false, 'err', 'bad');
  end if;
  me := array(select p_pid union select from_pid from aliases where to_pid = p_pid);

  for m in select value from jsonb_array_elements(ms) loop
    if jsonb_typeof(m) = 'object'
       and ((m->>'k' = 'ai' and m->>'p' = any(me)) or (m->>'k' = 'net' and (m->>'a' = any(me) or m->>'b' = any(me))))
       and coalesce(m->>'t', '') ~ '^[0-9]{10,15}$' and (m->>'t')::bigint <= max_t then
      begin
        insert into matches (id, t, k, a, b, w, p, lv, win, s1, s2)
        values (m->>'id', (m->>'t')::bigint, m->>'k', m->>'a', m->>'b', m->>'w', m->>'p', m->>'lv',
                (m->>'win')::boolean, (m->>'s1')::int, (m->>'s2')::int)
        on conflict (id) do nothing;
        get diagnostics n = row_count;
        saved := saved + n;
      exception when others then
        skipped := skipped || coalesce(m->>'id', '?');
      end;
    else
      skipped := skipped || coalesce(m->>'id', '?');
    end if;
  end loop;

  if p_best is not null then
    insert into players as pl (pid, name, best_smash, best_rally, best_train, updated_at)
    select a.pid, a.name,
      least(case when p_best->>'smash' ~ num then (p_best->>'smash')::int else 0 end, 400),
      least(case when p_best->>'rally' ~ num then (p_best->>'rally')::int else 0 end, 999),
      least(case when p_best->>'train' ~ num then (p_best->>'train')::int else 0 end, 999),
      now()
    from accounts a where a.pid = p_pid
    on conflict (pid) do update set
      name = excluded.name,
      best_smash = greatest(pl.best_smash, excluded.best_smash),
      best_rally = greatest(pl.best_rally, excluded.best_rally),
      best_train = greatest(pl.best_train, excluded.best_train),
      updated_at = now();
  end if;
  return json_build_object('ok', true, 'saved', saved, 'skipped', skipped);
end
$fn$;
revoke all on function public.bdm_sync(text, text, jsonb, jsonb) from public;
grant execute on function public.bdm_sync(text, text, jsonb, jsonb) to anon, authenticated;

-- Своя комната в лобби: p_status open | playing — объявить или обновить пульс, gone — убрать.
-- У игрока одна комната; занятый живой код чужого игрока не перехватить; комнаты старше часа удаляются.
-- Ответ: { ok: true } или { ok: false, err: bad | noacc | locked | pin | taken }
create or replace function public.bdm_room(p_pid text, p_pin text, p_code text, p_status text)
returns json language plpgsql security definer set search_path = public, extensions as $fn$
declare
  st text := bdm_auth(p_pid, p_pin);
  r public.rooms;
begin
  if st <> 'ok' then return json_build_object('ok', false, 'err', st); end if;
  if coalesce(p_code, '') !~ '^[A-Z2-9]{4}$' or coalesce(p_status, '') not in ('open', 'playing', 'gone') then
    return json_build_object('ok', false, 'err', 'bad');
  end if;
  delete from rooms where updated_at < now() - interval '1 hour';
  if p_status = 'gone' then
    delete from rooms where code = p_code and host_pid = p_pid;
    return json_build_object('ok', true);
  end if;
  select * into r from rooms where code = p_code;
  if found and r.host_pid <> p_pid and r.updated_at > now() - interval '45 seconds' then
    return json_build_object('ok', false, 'err', 'taken');
  end if;
  delete from rooms where host_pid = p_pid and code <> p_code;
  insert into rooms (code, host_pid, host_name, status, updated_at)
  select p_code, a.pid, a.name, p_status, now() from accounts a where a.pid = p_pid
  on conflict (code) do update set host_pid = excluded.host_pid, host_name = excluded.host_name,
    status = excluded.status, updated_at = now();
  return json_build_object('ok', true);
end
$fn$;
revoke all on function public.bdm_room(text, text, text, text) from public;
grant execute on function public.bdm_room(text, text, text, text) to anon, authenticated;


-- ===================== ШАГ 2: закрыть прямую запись (после деплоя нового клиента) =====================

drop policy if exists "matches add" on public.matches;
drop policy if exists "players add" on public.players;
drop policy if exists "players edit" on public.players;
drop policy if exists "rooms add" on public.rooms;
drop policy if exists "rooms edit" on public.rooms;
drop policy if exists "rooms remove" on public.rooms;
revoke all on public.matches, public.players, public.rooms from anon, authenticated;
grant select on public.matches, public.players, public.rooms to anon, authenticated;

-- Проверка после шага 2: у anon и authenticated должен остаться только SELECT,
-- политики — только "… read".
-- select grantee, table_name, string_agg(privilege_type, ', ' order by privilege_type)
--   from information_schema.role_table_grants
--   where table_schema = 'public' and grantee in ('anon', 'authenticated') group by 1, 2 order by 2, 1;
-- select tablename, policyname, cmd from pg_policies where schemaname = 'public' order by 1, 2;
