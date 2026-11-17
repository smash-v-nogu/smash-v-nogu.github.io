-- Смэш мне в ногу: схема Supabase (проект ktpeclypxevbfwtvuwbi)
-- Снято с рабочей базы 17.11.2026. Скрипт можно прогнать на чистом проекте целиком.
-- Клиент ходит в REST с публичным ключом (роль anon), доступ ограничен RLS.

create extension if not exists pgcrypto with schema extensions;

-- ========= Матчи =========
create table if not exists public.matches (
  id text primary key check (id ~ '^[a-z0-9]{8,24}$'),
  t bigint not null,                                   -- время матча, мс
  k text not null check (k in ('ai', 'net')),          -- против ИИ или онлайн
  a text check (a ~ '^[a-z0-9]{6,16}$'),               -- онлайн: игроки и победитель
  b text check (b ~ '^[a-z0-9]{6,16}$'),
  w text,
  p text check (p ~ '^[a-z0-9]{6,16}$'),               -- против ИИ: игрок, уровень, победа
  lv text check (lv in ('easy', 'medium', 'hard')),
  win boolean,
  s1 integer check (s1 between 0 and 30),
  s2 integer check (s2 between 0 and 30),
  created_at timestamptz not null default now(),
  check ((k = 'ai' and p is not null and lv is not null and win is not null)
      or (k = 'net' and a is not null and b is not null and a <> b and (w = a or w = b)))
);
create index if not exists matches_t_idx on public.matches (t desc);
alter table public.matches enable row level security;
create policy "matches read" on public.matches for select to anon, authenticated using (true);
create policy "matches add" on public.matches for insert to anon, authenticated with check (true);

-- ========= Игроки и рекорды =========
create table if not exists public.players (
  pid text primary key check (pid ~ '^[a-z0-9]{6,16}$'),
  name text not null check (char_length(name) between 1 and 16),
  best_smash integer not null default 0 check (best_smash between 0 and 400),
  best_rally integer not null default 0 check (best_rally between 0 and 999),
  best_train integer not null default 0 check (best_train between 0 and 999),
  updated_at timestamptz not null default now()
);
alter table public.players enable row level security;
create policy "players read" on public.players for select to anon, authenticated using (true);
create policy "players add" on public.players for insert to anon, authenticated with check (true);
create policy "players edit" on public.players for update to anon, authenticated using (true) with check (true);

-- ========= Открытые комнаты для лобби «Ждут соперника» =========
create table if not exists public.rooms (
  code text primary key check (code ~ '^[A-Z2-9]{4}$'),
  host_pid text not null check (host_pid ~ '^[a-z0-9]{6,16}$'),
  host_name text not null check (char_length(host_name) between 1 and 16),
  status text not null default 'open' check (status in ('open', 'playing')),
  updated_at timestamptz not null default now()
);
create index if not exists rooms_updated_idx on public.rooms (updated_at desc);
alter table public.rooms enable row level security;
create policy "rooms read" on public.rooms for select to anon, authenticated using (true);
create policy "rooms add" on public.rooms for insert to anon, authenticated with check (true);
create policy "rooms edit" on public.rooms for update to anon, authenticated using (true) with check (true);
create policy "rooms remove" on public.rooms for delete to anon, authenticated using (true);
grant select, insert, update, delete on public.rooms to anon, authenticated;

-- ========= Вход по имени и ПИН-коду =========
create table if not exists public.accounts (
  pid text primary key check (pid ~ '^[a-z0-9]{6,16}$'),
  name text not null check (char_length(name) between 1 and 16),
  pin_hash text not null,
  fails int not null default 0,
  locked_until timestamptz,
  created_at timestamptz not null default now()
);
create unique index if not exists accounts_name_lower on public.accounts (lower(name));
alter table public.accounts enable row level security;
revoke all on public.accounts from anon, authenticated;   -- только через bdm_login

-- Склейка профилей: старый id -> id аккаунта (клиенты пересчитывают таблицу)
create table if not exists public.aliases (
  from_pid text primary key check (from_pid ~ '^[a-z0-9]{6,16}$'),
  to_pid text not null check (to_pid ~ '^[a-z0-9]{6,16}$'),
  created_at timestamptz not null default now()
);
alter table public.aliases enable row level security;
create policy "aliases read" on public.aliases for select to anon, authenticated using (true);
revoke all on public.aliases from anon, authenticated;
grant select on public.aliases to anon, authenticated;

-- Игроки, появившиеся до входа по ПИНу: первый, кто займёт имя, забирает их записи
-- (снимок players на 17.11.2026; на чистом проекте будет пустым)
create table if not exists public.legacy_players as select pid, name from public.players;
alter table public.legacy_players enable row level security;
revoke all on public.legacy_players from anon, authenticated;

-- p_mode: 'new' — регистрация (или вход, если имя уже твоё и ПИН верный),
--         'login' — только вход (несуществующее имя -> err 'noname'),
--         'rename' — смена имени своего аккаунта.
-- Ответ: { ok, pid, name, mode: new | claim | login | rename } или { ok: false, err: bad | pin | taken | noname | locked }
create or replace function public.bdm_login(p_name text, p_pin text, p_pid text, p_mode text default 'new')
returns json language plpgsql security definer set search_path = public, extensions as $fn$
declare
  a public.accounts;
  nm text := trim(coalesce(p_name, ''));
  md text := coalesce(p_mode, 'new');
  legacy text;
  target text;
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

  select * into a from accounts where pid = p_pid;
  if found then
    if a.pin_hash <> crypt(p_pin, a.pin_hash) then return json_build_object('ok', false, 'err', 'pin'); end if;
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
