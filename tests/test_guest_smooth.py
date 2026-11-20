"""Гость на экране хозяина движется плавно и на неровной сети (20.11.2026: у хозяина на телефоне гость на бегу дёргался).
Онлайн через ?net=local. Гость шлёт известную плавную траекторию x(t) = 10 + 1,8·sin(2πt/3) (подменяем x в его
сообщениях), сеть до хозяина — с задержкой, дрожанием и затыками, порядок сообщений сохраняется. Хозяин каждый кадр пишет,
где нарисован гость (p.drawX). Мерим замирания (кадр стоит, а гость бежит) и рывки скорости против настоящей.
До плавной отрисовки (remoteView): на дрожании 20–70 мс гость стоял в 36% кадров, рывки 2,6 м/с; после — 0% и 0,2 м/с."""
import math, statistics
from _util import sync_playwright, BASE, launch, sign_up

NETS = {  # имя: (база мс, дрожание мс, шанс затыка, затык мс, порог замираний %, порог рывков м/с)
    'ровная сеть 30 мс': (30, 0, 0, 0, 3, 0.5),
    'дрожание 20–70 мс': (20, 50, 0, 0, 3, 0.8),
    'дрожание + затыки': (20, 50, 0.03, 120, 5, 1.2),
}
SHIM = """(() => {
  const cfg = window.__net = { base: 30, jit: 0, p: 0, stall: 0 }; // задержка с самого соединения, как в жизни
  const post = BroadcastChannel.prototype.postMessage; let due = 0;
  BroadcastChannel.prototype.postMessage = function (m) {
    if (m && m.t === 'in') { const t = Date.now() / 1000, w = 2 * Math.PI / 3;
      m = Object.assign({}, m, { x: 10 + 1.8 * Math.sin(w * t), vx: 1.8 * w * Math.cos(w * t) / 0.8, y: 0, vy: 0, g: 1 }); }
    const d = cfg.base + Math.random() * cfg.jit + (Math.random() < cfg.p ? cfg.stall : 0);
    due = Math.max(due, performance.now() + d); // упорядоченный канал: позднее не обгоняет раннее
    const bc = this; setTimeout(() => post.call(bc, m), due - performance.now());
  };
})();"""
fv = lambda t: 1.8 * 2 * math.pi / 3 * math.cos(2 * math.pi * t / 3)
f = lambda t: 10 + 1.8 * math.sin(2 * math.pi * t / 3)

def analyse(s):
    s = [(t / 1000, x) for t, x in s]
    d = min(range(0, 301, 2), key=lambda ms: sum((x - f(t - ms / 1000)) ** 2 for t, x in s)) / 1000  # лучшая постоянная задержка
    mv = [i for i in range(1, len(s)) if abs(fv(s[i][0] - d)) > 1.0]
    stalls = sum(1 for i in mv if abs(s[i][1] - s[i - 1][1]) < 1e-4)
    sp = [(s[i][1] - s[i - 1][1]) / max(1e-3, s[i][0] - s[i - 1][0]) - fv(s[i][0] - d) for i in range(1, len(s))]
    return round(d * 1000), round(100 * stalls / max(1, len(mv)), 1), round(statistics.pstdev(sp), 2)

errs, bad = [], []
with sync_playwright() as pw:
    br = launch(pw)
    ctx = br.new_context(viewport={'width': 1000, 'height': 560}); ctx.route('**/*supabase.co/**', lambda r: r.abort())
    A = ctx.new_page(); B = ctx.new_page(); B.add_init_script(SHIM)
    for pg, n in ((A, 'A'), (B, 'B')): pg.on('pageerror', lambda e, n=n: errs.append(n + ': ' + str(e)))
    A.goto(BASE + '?net=local&p=7'); B.goto(BASE + '?net=local&p=8'); A.wait_for_timeout(800)
    sign_up(A, 'Хост'); sign_up(B, 'Гость')
    A.click('#netHost'); A.wait_for_timeout(400)
    B.fill('#netCode', A.inner_text('.net-status .code')); B.click('#netJoin'); B.wait_for_timeout(1500)
    assert A.evaluate("() => __bdm.Net.connected"), 'нет соединения'
    for name, (base, jit, p, stall, max_st, max_sp) in NETS.items():
        B.evaluate(f"() => Object.assign(window.__net, {{ base: {base}, jit: {jit}, p: {p}, stall: {stall} }})")
        A.wait_for_timeout(700)
        s = A.evaluate("""() => new Promise(res => { const s = [], t0 = performance.now();
          const k = () => { const p = __bdm.P[1]; s.push([Date.now(), p.drawX ?? p.x]); if (performance.now() - t0 < 6000) requestAnimationFrame(k); else res(s); };
          requestAnimationFrame(k); })""")
        d, st, sp = analyse(s)
        ok = st <= max_st and sp <= max_sp
        print(f"{'ok  ' if ok else 'FAIL'} · {name}: задержка {d} мс, замирания {st}% (≤{max_st}), рывки скорости {sp} м/с (≤{max_sp})")
        if not ok: bad.append(name)
    br.close()

errs = [e for e in errs if 'Failed to load resource' not in e]
assert not errs, errs
assert not bad, bad
print('OK: гость у хозяина движется плавно')
