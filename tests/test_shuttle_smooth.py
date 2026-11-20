"""Волан в полёте движется плавно (20.11.2026: на телефоне «волану не хватает кадров, будто лагает»).
Мерим, где волан нарисован в каждом кадре (sh.drawX/drawY — то, что видит игрок), и сравниваем перемещение за кадр
с соседними: в плавном полёте скорость меняется мягко, рывок — когда кадр сдвинул волан заметно больше или меньше соседей.
Случаи: своя игра против ИИ (так же считает и хозяин онлайна), гость онлайна на ровной сети и на сети с дрожанием.
Порог — средний рывок в процентах от перемещения за кадр, без кадров с ударом (там скорость меняется по-настоящему)."""
import math, os, statistics, sys
from _util import sync_playwright, BASE, launch, sign_up

STRICT = '--measure' not in sys.argv  # --measure: только напечатать цифры, без проверки порогов
SHIM = """(() => {
  const cfg = window.__net = { base: 0, jit: 0 };
  const post = BroadcastChannel.prototype.postMessage; let due = 0;
  BroadcastChannel.prototype.postMessage = function (m) {
    if (!(m && m.t === 'st') || !(cfg.base + cfg.jit)) return post.call(this, m);
    due = Math.max(due, performance.now() + cfg.base + Math.random() * cfg.jit); // порядок сохраняется
    const bc = this; setTimeout(() => post.call(bc, m), due - performance.now());
  };
})();"""
SAMPLE = """(ms) => new Promise(res => { const s = [], t0 = performance.now(), sh = __bdm.sh;
  const k = now => { s.push([now, sh.drawX ?? sh.x, sh.drawY ?? sh.y, sh.inPlay && !sh.held ? 1 : 0, __bdm.game.hitId]);
    if (now - t0 < ms) requestAnimationFrame(k); else res(s); };
  requestAnimationFrame(k); })"""

def judder(s):
    """Средний и 90-й процентиль рывка, % от перемещения за кадр; только полёт, без кадров рядом с ударом."""
    out = []
    for i in range(2, len(s) - 1):
        a, b, c, d = s[i - 2], s[i - 1], s[i], s[i + 1]
        if not (a[3] and b[3] and c[3] and d[3]) or not (a[4] == b[4] == c[4] == d[4]): continue
        v = lambda p, q: ((q[1] - p[1]) / (q[0] - p[0]), (q[2] - p[2]) / (q[0] - p[0]))  # м/мс
        v0, v1, v2 = v(a, b), v(b, c), v(c, d)
        sp = math.hypot(*v1)
        if sp * 1000 < 2: continue  # почти висит — не мерим
        mid = ((v0[0] + v2[0]) / 2, (v0[1] + v2[1]) / 2)
        out.append(100 * math.hypot(v1[0] - mid[0], v1[1] - mid[1]) / sp)
    if not out: return None
    out.sort()
    return round(statistics.mean(out), 1), round(out[int(len(out) * 0.9)], 1), len(out)

res, errs = {}, []
with sync_playwright() as pw:
    br = launch(pw)
    ctx = br.new_context(viewport={'width': 1000, 'height': 560}); ctx.route('**/*supabase.co/**', lambda r: r.abort())
    # 1. Своя игра: оба — ИИ, волан летает без остановки
    L = ctx.new_page(); L.on('pageerror', lambda e: errs.append('L: ' + str(e)))
    L.goto(BASE + '?p=6'); L.wait_for_timeout(600); sign_up(L, 'Соло')
    L.evaluate("() => { const b = __bdm; b.startGame ? b.startGame('1p') : document.querySelector('#playAi').click(); }")
    L.wait_for_timeout(300)
    L.evaluate("() => { const P = __bdm.P; P[0].ai = { diff: 'hard' }; P[1].ai = { diff: 'hard' }; }")
    L.wait_for_timeout(1000)
    res['своя игра'] = judder(L.evaluate(SAMPLE, 9000))
    L.close()
    # 2–3. Онлайн: у хозяина играет ИИ (подаёт и бьёт), смотрим волан у гостя
    A = ctx.new_page(); B = ctx.new_page(); A.add_init_script(SHIM)
    for pg, n in ((A, 'A'), (B, 'B')): pg.on('pageerror', lambda e, n=n: errs.append(n + ': ' + str(e)))
    A.goto(BASE + '?net=local&p=7'); B.goto(BASE + '?net=local&p=8'); A.wait_for_timeout(800)
    sign_up(A, 'Хост'); sign_up(B, 'Гость')
    A.click('#netHost'); A.wait_for_timeout(400)
    B.fill('#netCode', A.inner_text('.net-status .code')); B.click('#netJoin'); B.wait_for_timeout(1500)
    assert A.evaluate("() => __bdm.Net.connected"), 'нет соединения'
    A.evaluate("() => { __bdm.P[0].ai = { diff: 'hard' }; }")
    for name, (base, jit) in {'гость, ровная сеть 30 мс': (30, 0), 'гость, дрожание 20–70 мс': (20, 50)}.items():
        A.evaluate(f"() => Object.assign(window.__net, {{ base: {base}, jit: {jit} }})")
        A.wait_for_timeout(800)
        res[name] = judder(B.evaluate(SAMPLE, 12000))
    br.close()

# до починки (20.11): 12,5% · 28% · 54%; после: 1,2% · 0,8% · 5,9%
LIMIT = {'своя игра': 4, 'гость, ровная сеть 30 мс': 4, 'гость, дрожание 20–70 мс': 12}
bad = []
for k, v in res.items():
    ok = v is not None and v[0] <= LIMIT[k]
    print(f"{'ok  ' if ok or not STRICT else 'FAIL'} · {k}: рывок {v[0] if v else '—'}% в среднем, 90% кадров ≤ {v[1] if v else '—'}% (кадров {v[2] if v else 0}; порог {LIMIT[k]}%)")
    if not ok: bad.append(k)
errs = [e for e in errs if 'Failed to load resource' not in e]
assert not errs, errs
if STRICT:
    assert not bad, bad
    print('OK: волан летит плавно')
