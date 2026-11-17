-- Уровень ИИ «умный» (smart) в общей таблице (18.11.2026)
--
-- Было: matches.lv разрешал только easy / medium / hard, и матчи против умного bdm_sync пропускал.
-- Порядок на рабочей базе: эта миграция -> задеплоить клиент, который отправляет матчи smart.
-- Старый клиент не затронут: такой уровень он не шлёт, а при чтении таблицы пропускает.
-- Новый клиент, если миграции ещё нет, не теряет матчи: пропущенные базой smart-матчи он отправит снова.

-- Снимаем check на уровень по содержимому, а не по имени: на рабочей базе имя может отличаться
do $$
declare c text;
begin
  for c in
    select conname from pg_constraint
    where conrelid = 'public.matches'::regclass and contype = 'c'
      and pg_get_constraintdef(oid) like '%lv%' and pg_get_constraintdef(oid) like '%easy%'
  loop
    execute format('alter table public.matches drop constraint %I', c);
  end loop;
end $$;

alter table public.matches add constraint matches_lv_check check (lv in ('easy', 'medium', 'hard', 'smart'));

-- Проверка: должна быть строка matches_lv_check со smart и общий check на k
select conname, pg_get_constraintdef(oid) as def
from pg_constraint where conrelid = 'public.matches'::regclass and contype = 'c' order by conname;
