"""Умный ИИ («читает» соперника): физика как у сложного, выигрыш только от предвидения.
1. Ускоренная симуляция в демо-режиме, каждый случай — против сложного и против умного:
   - обычный средний ИИ и случайный бот (любой удар, любой прицел) — умный не сильнее сложного;
   - однообразный бот (всегда острый дроп / тугая сетка) — умный заметно сильнее сложного.
2. Игра против умного через меню: «Читаю тебя» появляется, память пишется в localStorage и переходит в следующую партию,
   матч записан с уровнем smart и уходит в общую таблицу; если база ещё без миграции 20261118 и пропустила его,
   он остаётся в очереди и уходит со следующей синхронизацией. Supabase подменён.
SECS — игровых секунд на случай (по умолчанию 15000; сравнения «как сложный» идут вдвое дольше — там важна точность)."""
import json, os
from _util import sync_playwright, BASE, launch, sign_up, ai_case

SECS = float(os.environ.get('SECS', '15000'))
UP, DOWN = 0.05, 0.08  # «как сложный»: не сильнее на 5 п.п. очков и не слабее на 8 (шум разницы при 30000 с — около 1,6 п.п.)
MORE = 0.08   # «заметно сильнее»: на 8 п.п. очков больше, чем у сложного (с тактикой 18.11 около +14, до неё +12…+20)

HARD, SMART = {'diff': 'hard'}, {'diff': 'smart'}
# (имя, соперник, во сколько раз дольше SECS)
OPPONENTS = [
    ('средний ИИ', {'diff': 'medium'}, 2),
    ('случайный бот', {'diff': 'hard', 'bot': 'any'}, 2),
    ('однообразный бот (острый дроп)', {'diff': 'hard', 'bot': {'key': 'drop', 'place': 1}}, 1),
]

syncs, db = [], {'migrated': False}  # migrated — применена ли на фейковой базе миграция 20261118 (уровень smart)


def handle(route):
    req = route.request; u = req.url
    if '/rpc/bdm_login' in u:
        b = json.loads(req.post_data)
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'pid': b['p_pid'], 'name': b['p_name'].strip(), 'mode': 'new'}))
    if '/rpc/bdm_sync' in u:
        b = json.loads(req.post_data); syncs.append(b)
        skipped = [] if db['migrated'] else [m['id'] for m in b.get('p_matches') or [] if m.get('lv') == 'smart']
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True, 'saved': 0, 'skipped': skipped}))
    if req.method == 'GET':
        return route.fulfill(status=200, content_type='application/json', body='[]')
    return route.fulfill(status=401, content_type='application/json', body='{"code":"42501"}')


errs, res = [], {}
with sync_playwright() as pw:
    br = launch(pw)
    ctx = br.new_context(viewport={'width': 1200, 'height': 700}); ctx.route('**/*supabase.co/**', lambda r: r.abort())
    A = ctx.new_page(); A.on('pageerror', lambda e: errs.append(str(e)))
    A.goto(BASE + '?p=6'); A.wait_for_timeout(800)
    assert A.evaluate("() => __bdm.game.mode") == 'demo', 'на старте крутится демо'
    for name, opp, k in OPPONENTS:
        for me in (HARD, SMART):
            r = ai_case(A, opp, me, secs=SECS * k)
            res[(name, me['diff'])] = r
            rd = r['read']; extra = ''
            if rd:
                extra = (f" · уверен в {rd['sure'] / rd['shots']:.0%} ударов, из них угадал {rd['right'] / max(1, rd['sure']):.0%}"
                         f" · «Читаю тебя» в {rd['shown'] / max(1, r['rallies']):.0%} розыгрышей")
            print(f"{name} против {me['diff']}: у {me['diff']} {1 - r['share0']:.1%} очков, {1 - r['win0']:.0%} партий из {r['n']}"
                  f" · ударов за розыгрыш {r['avgHits']}, макс {r['maxHits']}{extra}", flush=True)

    # 2. Игра против умного через меню
    B = br.new_context(viewport={'width': 1200, 'height': 700}); B.route('**/*supabase.co/**', handle)
    G = B.new_page(); G.on('pageerror', lambda e: errs.append('G: ' + str(e)))
    G.goto(BASE + '?p=3'); G.wait_for_timeout(800)
    sign_up(G, 'Повторюша')
    G.click('#diffSeg button[data-diff="smart"]')
    assert G.get_attribute('#diffSeg button[data-diff="smart"]', 'aria-checked') == 'true'
    assert 'запоминает' in G.inner_text('#diffNote'), 'подсказка к уровню'
    G.click('.t-ai .len button[data-len="7"]')
    G.click('#playAi'); G.wait_for_timeout(300)
    assert G.evaluate("() => __bdm.game.mode === '1p' && __bdm.game.diff === 'smart'")
    assert 'умный' in G.evaluate("() => __bdm.P[1].name"), 'на табло видно уровень'
    # за игрока слева играет однообразный бот: всегда острый дроп
    G.evaluate("() => { __bdm.P[0].ai = { diff: 'hard', bot: { key: 'drop', place: 1 } }; }")
    seen = False
    for _ in range(3000):
        if G.evaluate("() => __bdm.game.state === 'over'"): break
        seen = G.evaluate("() => { __bdm.fastForward(0.25); return __bdm.game.popups.some(p => p.text === 'Читаю тебя'); }") or seen
    assert G.evaluate("() => __bdm.game.state === 'over'"), 'партия доиграна'
    assert seen, 'всплывашка «Читаю тебя» появлялась'
    G.wait_for_timeout(800)  # после партии игра сама синхронизируется с базой
    mem = G.evaluate("() => JSON.parse(localStorage.getItem('bdm-read3'))")
    assert mem and mem['who'] == G.evaluate("() => __bdm.profile.pid") and mem['t'], 'память умного сохранена под своим профилем'
    rec = G.evaluate("() => __bdm.store.recs[__bdm.store.recs.length - 1]")
    assert rec['k'] == 'ai' and rec['lv'] == 'smart', f'матч записан с уровнем smart: {rec}'
    st = G.evaluate("() => __bdm.standings().find(r => r.pid === __bdm.profile.pid)")
    assert st and st['lv']['smart'] == (1 if rec['win'] else 0), 'победы над умным считаются отдельно'
    pushed = [m['id'] for s in syncs for m in (s.get('p_matches') or [])]
    assert rec['id'] in pushed, 'матч с умным отправлен в общую таблицу'
    assert not G.evaluate("id => __bdm.store.cloud.has(id)", rec['id']), 'база без миграции пропустила матч — он остаётся в очереди'
    db['migrated'] = True; n0 = len(syncs)
    G.evaluate("() => __bdm.cloudSync()")
    assert any(m['id'] == rec['id'] for s in syncs[n0:] for m in (s.get('p_matches') or [])), 'со следующей синхронизацией матч отправлен снова'
    assert G.evaluate("id => __bdm.store.cloud.has(id)", rec['id']), 'после миграции матч записан и больше не отправляется'
    # память переходит в следующую партию — и после перезагрузки страницы
    G.click('#again'); G.wait_for_timeout(300)
    carried = G.evaluate("() => { const t = __bdm.P[1].ai.read.t; return Object.values(t).reduce((s, row) => s + Object.values(row).reduce((a, b) => a + b, 0), 0); }")
    assert carried > 0, 'следующая партия начинается с памятью о прошлой'
    G.reload(); G.wait_for_timeout(800)
    G.click('#diffSeg button[data-diff="smart"]'); G.click('#playAi'); G.wait_for_timeout(300)
    loaded = G.evaluate("() => Object.keys(__bdm.P[1].ai.read.t).length")
    assert loaded > 0, 'после перезагрузки память взята из localStorage'
    br.close()

for (name, lv), r in res.items():
    assert r['maxQuiet'] <= 180 and r['maxHits'] < 100, f'{name} против {lv}: розыгрыш завис'
    assert r['n'] >= 20, f'{name} против {lv}: всего {r["n"]} партий'
share = {k: 1 - r['share0'] for k, r in res.items()}
for name in ('средний ИИ', 'случайный бот'):
    d = share[(name, 'smart')] - share[(name, 'hard')]
    assert -DOWN <= d <= UP, f'{name}: умный должен играть как сложный, разница {d:+.1%}'
mono = 'однообразный бот (острый дроп)'
d = share[(mono, 'smart')] - share[(mono, 'hard')]
assert d >= MORE, f'{mono}: умный должен быть заметно сильнее сложного, разница {d:+.1%}'
rm, rr = res[(mono, 'smart')]['read'], res[('случайный бот', 'smart')]['read']
assert rm['sure'] / rm['shots'] >= 0.6 and rm['right'] / rm['sure'] >= 0.9, f'однообразного читает уверенно и верно: {rm}'
assert rr['sure'] / rr['shots'] <= 0.15, f'случайного почти не пытается читать: {rr}'
assert not errs, [e for e in errs if 'Failed to load resource' not in e] or None
print(f"OK: умный ИИ (против однообразного {d:+.1%} очков к сложному)")
