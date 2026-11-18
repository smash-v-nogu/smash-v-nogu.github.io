-- Сводка сети онлайн-матчей (18.11.2026)
--
-- Зачем: жалобу «в первой партии лагало» задним числом не разобрать — серверам не видно ни пути (напрямую или
-- через ретранслятор, UDP или TCP), ни пинга. Теперь каждая сторона присылает свою сводку вместе с матчем.
-- Что меняется: новая таблица net_stats (anon только читает) и bdm_sync, который пишет в неё поле net матча.
-- Порядок на рабочей базе: эта миграция -> деплой клиента. Наоборот тоже ничего не ломает: старый bdm_sync
-- поле net молча пропускает (сводки первых матчей тогда просто не сохранятся).

-- ========= Сводка сети онлайн-матчей (с 18.11.2026) =========
-- Каждый участник присылает свою сторону вместе с матчем через bdm_sync: путь (напрямую / ретранслятор, UDP / TCP),
-- пинг, замирания, темп. Нужна, чтобы разбирать жалобы «лагало». Ключи d — как в NetStats.take() в index.html:
-- v версия, r h|g (хозяин / гость), n номер матча в соединении, dur с, ct мс до соединения, path и sw [[с, путь]…],
-- png [p50, p95, max] пинг игры мс, ice [p50, max] пинг соединения мс, fz замираний > 250 мс, fzT с в них, gap самая
-- длинная пауза мс, rx сообщений друга в с, fps свои кадры в с, hid с скрытой вкладки, buf макс. очередь канала, ua.
create table if not exists public.net_stats (
  match_id text not null check (match_id ~ '^[a-z0-9]{8,24}$'),
  pid text not null check (pid ~ '^[a-z0-9]{6,16}$'),
  d jsonb not null check (jsonb_typeof(d) = 'object' and octet_length(d::text) <= 1500),
  created_at timestamptz not null default now(),
  primary key (match_id, pid)
);
alter table public.net_stats enable row level security;
drop policy if exists "net_stats read" on public.net_stats;
create policy "net_stats read" on public.net_stats for select to anon, authenticated using (true);
revoke all on public.net_stats from anon, authenticated;   -- пишет только bdm_sync
grant select on public.net_stats to anon, authenticated;

-- Синхронизация своего. p_matches — массив строк как в таблице matches (до 200): записываются только матчи,
-- где игрок участвует своим id или старым, склеенным с аккаунтом; чужие и кривые пропускаются.
-- У онлайн-матча может быть поле net — своя сводка сети (см. net_stats): пишется одна на игрока и матч,
-- только если матч в базе и игрок в нём участвует. Кривая сводка не мешает записать сам матч.
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
      if m->>'k' = 'net' and jsonb_typeof(m->'net') = 'object' then
        begin
          insert into net_stats (match_id, pid, d)
          select x.id, p_pid, m->'net' from matches x
          where x.id = m->>'id' and x.k = 'net' and (x.a = any(me) or x.b = any(me))
          on conflict (match_id, pid) do nothing;
        exception when others then null;  -- сводка больше 1500 байт или кривая — матч уже записан, её просто нет
        end;
      end if;
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

-- Проверка: таблица есть, у anon только чтение; в bdm_sync есть вставка в net_stats
select table_name, string_agg(privilege_type, ',') from information_schema.role_table_grants
where table_schema = 'public' and table_name = 'net_stats' and grantee = 'anon' group by 1;
select position('net_stats' in pg_get_functiondef('public.bdm_sync(text, text, jsonb, jsonb)'::regprocedure)) > 0 as sync_writes_net;
