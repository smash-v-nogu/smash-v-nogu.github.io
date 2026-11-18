"""Добивание у сетки: смэш по волану, который у сетки идёт выше троса, бьёт коротко и круто вниз.
Ставим волан и игрока руками (демо, левый игрок без ИИ), жмём смэш и смотрим, какой вышел удар и куда он падает.
Плюс сетка: из-под самого пола она выходит высокой (её можно добить), с хорошего контакта сверху — тугой.
И ИИ: сложный добивает небрежную сетку однообразного дропера, добивания не улетают в аут. Supabase отрезан."""
import os
from _util import sync_playwright, BASE, launch

NET, NET_H = 6.7, 1.524

# Левый игрок — человек без ввода; волан летит к нему с правой стороны. Возвращает удар и куда он упадёт.
HIT = """
([px, sx, sy, svx, svy, key, press]) => {
  const b = window.__bdm, g = b.game, P = b.P, sh = b.sh, me = P[0];
  me.ai = null; me.x = px; me.y = 0; me.vx = 0; me.vy = 0; me.onGround = true; me.press = press || 0; me.sta = 1;
  me.swing = null; me.recover = 0; me.charge = 0;
  g.state = 'rally'; g.over = null;
  Object.assign(sh, { x: sx, y: sy, vx: svx, vy: svy, inPlay: true, held: false, netHit: false, isServe: false, lastHitter: P[1], variant: 'drop', trail: [] });
  const hid = g.hitId;
  me.shotReq = key;
  for (let i = 0; i < 12 && g.hitId === hid; i++) b.fastForward(1 / 240);
  if (g.hitId === hid) return { hit: false };
  const r = b.simulate(sh.x, sh.y, sh.vx, sh.vy, true);
  return { hit: true, v: sh.variant, vy: sh.vy, kmh: Math.round(Math.hypot(sh.vx, sh.vy) * 3.6), land: r.landX, netY: r.netY, t: r.t, startX: sh.x };
}
"""

# Сложный против однообразного дропера: сколько добиваний и чем они кончились
AI = """
([secs]) => {
  const b = window.__bdm, g = b.game, P = b.P;
  P[0].ai = { diff: 'hard' }; P[1].ai = { diff: 'hard', bot: { key: 'drop', place: 1 } };
  const k0 = g.stats.shots.kill || 0, by0 = { ...(g.stats.by || {}) };
  b.fastForward(secs);
  const by = {}; for (const k in g.stats.by || {}) if (k.endsWith('/ kill')) by[k] = g.stats.by[k] - (by0[k] || 0);
  return { kills: (g.stats.shots.kill || 0) - k0, by };
}
"""

errs = []
with sync_playwright() as pw:
    br = launch(pw)
    ctx = br.new_context(viewport={'width': 1200, 'height': 700}); ctx.route('**/*supabase.co/**', lambda r: r.abort())
    A = ctx.new_page(); A.on('pageerror', lambda e: errs.append(str(e)))
    A.goto(BASE + '?p=8'); A.wait_for_timeout(800)
    assert A.evaluate("() => __bdm.game.mode") == 'demo', 'на старте крутится демо'

    # 1. Волан у сетки выше троса — добивание: вниз, в корт соперника, быстро
    for sx, sy in [(NET - 0.02, 1.68), (NET - 0.25, 1.72), (NET + 0.03, 1.66)]:
        for _ in range(5):
            r = A.evaluate(HIT, [NET - 0.5, sx, sy, -1.2, -0.6, 'smash', 0])
            assert r['hit'], f'волан {sx - NET:+.2f} м / {sy} м: удара не было'
            assert r['v'] == 'kill', f'волан {sx - NET:+.2f} м / {sy} м над полом: ждали добивание, вышло {r["v"]}'
            assert r['vy'] < 0, f'добивание летит вверх: vy = {r["vy"]:.2f}'
            assert NET + 0.5 < r['land'] < NET + 4.5, f'добивание упало в {r["land"] - NET:.2f} м от сетки'
            assert r['t'] < 0.35, f'добивание летит {r["t"]:.2f} игровых с — это не добивание'
    print('OK: выше троса у сетки смэш = добивание, вниз и в корт')

    # 2. Ниже троса — по-прежнему драйв, выше 1,9 м — смэш
    r = A.evaluate(HIT, [NET - 1.0, NET - 0.6, 1.45, -1.2, -0.6, 'smash', 0])
    assert r['hit'] and r['v'] == 'drive', f'волан ниже троса: ждали драйв, вышло {r}'
    r = A.evaluate(HIT, [NET - 1.2, NET - 0.6, 2.05, -1.2, -0.6, 'smash', 0])
    assert r['hit'] and r['v'] == 'smash', f'волан выше 1,9 м: ждали смэш, вышло {r}'
    # дальше от сетки на той же высоте — уже не добивание: трос мешает бить вниз
    r = A.evaluate(HIT, [NET - 1.6, NET - 1.4, 1.70, -1.2, -0.6, 'smash', 0])
    assert r['hit'] and r['v'] == 'drive', f'волан в 1,4 м от сетки на 1,7 м: ждали драйв, вышло {r}'
    print('OK: ниже троса — драйв, выше 1,9 м — смэш, далеко от сетки — драйв')

    # 3. Сетка из-под пола выходит высокой, с хорошего контакта сверху — тугой
    low, high = [], []
    for _ in range(8):
        r = A.evaluate(HIT, [NET - 0.95, NET - 0.45, 0.35, -0.6, -1.2, 'drop', 0])
        assert r['hit'] and r['v'] == 'net', f'низкий волан у сетки: ждали сетку, вышло {r}'
        low.append(r['netY'] - NET_H)
        # волан в лучшей точке: 0,8 м от плеча (плечо 1,45 м), давления нет
        r = A.evaluate(HIT, [NET - 0.6 - 0.76, NET - 0.6, 1.2, -0.3, -0.8, 'drop', 0])
        assert r['hit'] and r['v'] == 'net', f'волан у сетки на 1,2 м: ждали сетку, вышло {r}'
        if r['netY'] is not None and r['netY'] > NET_H: high.append(r['netY'] - NET_H)
    low_avg, high_avg = sum(low) / len(low), sum(high) / max(1, len(high))
    print(f'сетка над тросом: из-под пола {low_avg * 100:.0f} см, сверху {high_avg * 100:.0f} см')
    assert low_avg > 0.08, f'сетка из-под пола проходит всего на {low_avg * 100:.0f} см над тросом — её не добить'
    assert high and high_avg < 0.07, f'сетка с хорошего контакта проходит на {high_avg * 100:.0f} см над тросом — слишком высоко'
    print('OK: сетка из-под пола высокая, сверху — тугая')

    # 4. ИИ добивает и не улетает в аут
    A.goto(BASE + '?p=8'); A.wait_for_timeout(800)
    r = A.evaluate(AI, [4000])
    print(f'сложный против дропера за 4000 с: добиваний {r["kills"]}, {r["by"]}')
    assert r['kills'] >= 2, f'сложный ИИ почти не добивает: {r["kills"]} за 4000 с'
    assert r['by'].get('Аут / kill', 0) <= max(1, r['kills'] // 5), f'добивания улетают в аут: {r["by"]}'
    br.close()

assert not errs, errs
print('OK: добивание у сетки')
