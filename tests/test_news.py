"""«Что нового»: окно при входе видит только вернувшийся игрок, который не видел свежее обновление; новичку — правила,
а пришедшему по ссылке в комнату окно не мешает. Пункт открывается в проигрывателе правил и возвращает к списку.
Таблица показывает всех игроков: лишние строки прокручиваются внутри плиты, своя строка прилипает к краю."""
import json
from _util import sync_playwright, BASE, launch, sign_up

errs = []
SEED = """([slot, news]) => { if (sessionStorage.getItem('seeded')) return; sessionStorage.setItem('seeded', '1');
  localStorage.setItem('bdm-profile' + slot, JSON.stringify({ pid: 'newstest01', name: 'Новостник', style: 'tech' }));
  if (news) localStorage.setItem('bdm-news' + slot, JSON.stringify(news)); }"""

def open_page(br, slot, news=None, w=1440, h=900, hash_=''):
    ctx = br.new_context(viewport={'width': w, 'height': h})
    ctx.route('**/*supabase.co/**', lambda r: r.abort())
    ctx.add_init_script(f"({SEED})([{json.dumps(slot)}, {json.dumps(news)}])")
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(BASE + '?p=' + slot + hash_); pg.wait_for_timeout(900)
    if pg.is_visible('#nameLater'): pg.click('#nameLater'); pg.wait_for_timeout(500)  # база недоступна — «Защити профиль» откладываем
    return ctx, pg

shown = lambda pg, sel: pg.evaluate(f"() => !document.querySelector('{sel}').hidden")

with sync_playwright() as pw:
    br = launch(pw)
    ctx, pg = open_page(br, '1')
    news = pg.evaluate("() => __bdm.NEWS.map(r => r.id)")
    assert len(news) >= 2 and news == sorted(news, reverse=True), f'NEWS от нового к старому: {news}'

    # вернулся и ни разу не видел — окно с самым свежим обновлением, после него помечено «видел»
    assert shown(pg, '#news'), 'вернувшемуся окно показано при входе'
    assert pg.evaluate("() => document.querySelectorAll('#nList .nrel').length") == 1
    assert pg.evaluate("() => localStorage.getItem('bdm-news1')") == json.dumps(news[0])
    # пункт открывается в проигрывателе правил, последний шаг — «К списку»
    n = pg.evaluate("() => __bdm.NEWS[0].items.length")
    pg.click('#nList .nitem'); pg.wait_for_timeout(300)
    assert shown(pg, '#rules') and not shown(pg, '#news')
    assert pg.evaluate("() => document.getElementById('rDemo').hidden") == (not pg.evaluate("() => !!__bdm.NEWS[0].items[0].demo")), 'мини-корт — только у пункта с анимацией'
    assert pg.inner_text('#rStep').endswith(f'1 / {n}'), pg.inner_text('#rStep')
    for _ in range(n - 1): pg.click('#rNext')
    assert pg.inner_text('#rNext') == 'К списку'
    pg.click('#rNext'); pg.wait_for_timeout(150)
    assert shown(pg, '#news') and not shown(pg, '#rules'), 'вернулись к списку'
    pg.keyboard.press('Escape'); pg.wait_for_timeout(100)
    assert not shown(pg, '#news')
    # повторный вход — окна нет, по кнопке в шапке — все обновления
    pg.reload(); pg.wait_for_timeout(900)
    if pg.is_visible('#nameLater'): pg.click('#nameLater'); pg.wait_for_timeout(500)
    assert not shown(pg, '#news'), 'второй раз окно не показываем'
    assert 'unseen' not in pg.get_attribute('#newsBtn', 'class')
    pg.click('#newsBtn'); pg.wait_for_timeout(150)
    assert pg.evaluate("() => document.querySelectorAll('#nList .nrel').length") == len(news)
    # пункт с анимацией: мини-корт рисуется, Esc возвращает к списку
    pg.click('#nList .nitem.has-demo'); pg.wait_for_timeout(1200)
    assert not pg.evaluate("() => document.getElementById('rDemo').hidden"), 'у пункта с анимацией есть мини-корт'
    lit = pg.evaluate("() => { const c = document.getElementById('rCanvas'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] + d[i + 1] + d[i + 2] > 300) n++; return n; }")
    assert lit > 200, f'анимация рисуется: {lit} светлых точек'
    pg.keyboard.press('Escape'); pg.wait_for_timeout(150)
    assert shown(pg, '#news') and not shown(pg, '#rules')
    pg.click('#nOk')
    # правила как раньше
    pg.click('#openRules'); pg.wait_for_timeout(150)
    assert pg.inner_text('#rStep') == '1 / 11' and pg.evaluate("() => document.querySelectorAll('#rDots button').length") == 11
    pg.click('#rClose'); pg.wait_for_timeout(100)
    assert not shown(pg, '#news'), 'закрытие правил не открывает новости'
    ctx.close()

    # видел предыдущее — в окне только новое
    ctx, pg = open_page(br, '2', news=news[1])
    assert shown(pg, '#news') and pg.evaluate("() => [...document.querySelectorAll('#nList .nrel h3')].length") == 1
    ctx.close()
    # видел всё — окна нет, фишка без «новое»
    ctx, pg = open_page(br, '3', news=news[0])
    assert not shown(pg, '#news') and not shown(pg, '#newsNew')
    ctx.close()
    # пришёл по ссылке в комнату — не мешаем войти, «новое» горит на фишке
    ctx, pg = open_page(br, '4', hash_='#ABCD')
    assert not shown(pg, '#news') and shown(pg, '#newsNew')
    ctx.close()

    # новичок: окно входа, потом правила, новостей нет и они помечены просмотренными
    ctx = br.new_context(viewport={'width': 1440, 'height': 900}); ctx.route('**/*supabase.co/**', lambda r: r.abort())
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(BASE + '?p=5'); pg.wait_for_timeout(800)
    assert shown(pg, '#nameDlg') and not shown(pg, '#news')
    pg.fill('#nameInput', 'Новичок'); pg.fill('#pinInput', '1234'); pg.press('#pinInput', 'Enter'); pg.wait_for_timeout(600)
    assert shown(pg, '#rules') and not shown(pg, '#news'), 'новичку правила, а не новости'
    assert pg.evaluate("() => localStorage.getItem('bdm-news5')") == json.dumps(news[0])
    ctx.close()

    # окно на низком экране стоит на месте: прокручивается только список, кнопки видны
    ctx, pg = open_page(br, '7', news=news[0], w=844, h=390)
    pg.click('#newsBtn'); pg.wait_for_timeout(200)
    g = pg.evaluate("""() => { const o = document.getElementById('news'), l = document.getElementById('nList'), f = document.querySelector('.news-foot').getBoundingClientRect();
      return [o.scrollHeight <= o.clientHeight + 1, l.scrollHeight > l.clientHeight + 50, f.bottom <= innerHeight && f.top >= 0]; }""")
    assert g == [True, True, True], f'окно не крутится, список крутится, кнопки видны: {g}'
    ctx.close()

    # таблица: 21 игрок — все в списке, прокрутка внутри плиты, своя строка внизу видна
    ctx, pg = open_page(br, '6', news=news[0])
    pg.evaluate("""() => { const b = __bdm, recs = []; let id = 0;
      for (let i = 0; i < 20; i++) { const a = 'lbtest' + String(i).padStart(4, '0'); b.store.names[a] = ['Игрок ' + i, 1];
        for (let j = 0; j < 20 - i; j++) recs.push({ id: 'lbrec' + String(id++).padStart(6, '0'), t: 1 + id, k: 'net', a, b: 'lbtest' + String((i + 1) % 20).padStart(4, '0'), w: a, s: [15, 9] }); }
      recs.push({ id: 'lbrec' + String(id++).padStart(6, '0'), t: 1 + id, k: 'ai', p: b.profile.pid, lv: 'easy', win: true, s: [15, 3] });
      localStorage.setItem('bdm-recs6', JSON.stringify(recs)); localStorage.setItem('bdm-names6', JSON.stringify(b.store.names)); }""")
    pg.reload(); pg.wait_for_timeout(900)
    if pg.is_visible('#nameLater'): pg.click('#nameLater'); pg.wait_for_timeout(300)
    rows = pg.evaluate("() => document.querySelectorAll('#lbBody tr').length")
    assert rows == 21, f'в таблице все 21 игрок, а не топ: {rows}'
    sc = pg.evaluate("() => { const s = document.getElementById('lbScroll'); return [s.scrollHeight, s.clientHeight]; }")
    assert sc[0] > sc[1] + 100, f'лишние строки прокручиваются внутри плиты: {sc}'
    me = pg.evaluate("""() => { const s = document.getElementById('lbScroll').getBoundingClientRect(), r = document.querySelector('#lbBody tr.me td').getBoundingClientRect(); /* прилипают ячейки, строка остаётся на месте */ return [r.top >= s.top - 1, r.bottom <= s.bottom + 1]; }""")
    assert me == [True, True], f'своя строка видна без прокрутки: {me}'
    tiles = pg.evaluate("() => ['.t-ai', '.t-lb'].map(s => Math.round(document.querySelector(s).getBoundingClientRect().height))")
    # десктоп: таблица на всю высоту меню — низ вровень с «Управлением», а оно не разрастается и меню влезает в 900 px
    geo = pg.evaluate("""() => { const r = s => document.querySelector(s).getBoundingClientRect();
      return [Math.round(r('.t-lb').bottom - r('.t-keys').bottom), Math.round(r('.t-keys').height), Math.round(r('#menu > .menu-inner').height)]; }""")
    assert abs(geo[0]) <= 1 and geo[1] < 230 and geo[2] <= 900, f'таблица до низа меню, «Управление» компактное, меню в экране: {geo}'
    ctx.close()
    br.close()

assert not [e for e in errs if 'Failed to load resource' not in e], errs
print(f'OK: что нового ({len(news)} обновл.), таблица на 21 игрока, высота плит ИИ/таблица {tiles}')
