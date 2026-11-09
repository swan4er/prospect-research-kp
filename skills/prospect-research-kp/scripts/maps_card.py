"""Карты: поиск, карточка, темы и отзывы, ответы владельца. Без браузера и без имён авторов отзывов.

python3 -I maps_card.py yandex-search "<что искать>" [--near долгота,широта] [--top 8]
python3 -I maps_card.py yandex <адрес карточки Яндекса или ID> [--full]
python3 -I maps_card.py 2gis-search "<что искать>" [--city moscow] [--top 8]
python3 -I maps_card.py 2gis <адрес карточки 2ГИС или ID фирмы> [--city moscow] [--full] [--prices]

Автоматический браузер карты блокируют (429, капча), обычные запросы — нет: страницы приходят
с данными внутри. Если 2ГИС отвечает «обновите браузер», поднять версию Chrome в переменной UA.
Поиск обеих карт молча исправляет запрос — скрипт печатает исправление: сверять написание.
Обе карты отдают выборку из 50 отзывов, не обязательно самых свежих.
Карточка печатает и контакты, часы, куда ведёт кнопка записи, рекламу и цены. Чего нет в данных
страницы — «не видно»: это не значит «нет». --prices у 2ГИС — ещё один запрос, вкладка «Цены».
"""
import argparse
import collections
import datetime
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = os.environ.get('UA', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36')


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ru-RU,ru;q=0.9'})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            body, final = resp.read().decode('utf-8', errors='replace'), resp.geturl()
    except urllib.error.HTTPError as e:
        sys.exit(f'{url}: HTTP {e.code} — открыть вручную или через WebFetch')
    if 'captcha' in final or 'museum' in final:
        sys.exit(f'{url}: капча или «обновите браузер» ({final}) — открыть вручную или через WebFetch')
    return body


def walk(obj, pred, found=None):
    found = [] if found is None else found
    if isinstance(obj, dict):
        if pred(obj):
            found.append(obj)
        for value in obj.values():
            walk(value, pred, found)
    elif isinstance(obj, list):
        for value in obj:
            walk(value, pred, found)
    return found


def when(stamp):
    # «2026-08-04T19:27:48.745Z», «2026-10-11T20:22:57.0+07:00»
    stamp = re.sub(r'\.\d+', '', stamp).replace('Z', '+00:00')
    return datetime.datetime.fromisoformat(stamp)


def one_line(text, limit=200):
    text = ' '.join((text or '').split())
    return text if limit is None else text[:limit]


def report(reviews, sample, full):
    """reviews: [(дата, оценка, дата ответа или None, текст, источник, текст ответа)]."""
    if not reviews:
        print('Отзывов в выборке нет.')
        return
    reviews.sort(key=lambda r: r[0], reverse=True)
    stars = collections.Counter(r[1] for r in reviews)
    fresh = sum(1 for r in reviews if (datetime.datetime.now(datetime.timezone.utc) - r[0]).days <= 90)
    print(f'Выборка: {len(reviews)} отзывов, {sample}. Самый свежий — {reviews[0][0]:%Y-%m-%d}, за последние 90 дней — {fresh}.')
    print('Оценки:', ', '.join(f'{s}★ {stars[s]}' for s in sorted(stars, reverse=True)))
    # даты ответов: пачки показывают, когда кто-то взялся за карточку
    days = collections.Counter(f'{r[2]:%Y-%m-%d}' for r in reviews if r[2])
    print(f'С ответом владельца: {sum(days.values())} из {len(reviews)}.'
          + (' Когда отвечали: ' + ', '.join(f'{d} ×{n}' for d, n in sorted(days.items())) if days else ''))
    print('\nОтзывы, свежие сверху (дата | оценка | ответ | источник | текст):')
    for date, stars_, answered, text, source, answer in reviews:
        reply = f'ответ {answered:%Y-%m-%d}' if answered else 'без ответа'
        print(f'{date:%Y-%m-%d} | {stars_}★ | {reply} | {source} | {one_line(text, None if full else 200)}')
        if full and answer:
            print(f'    ответ: {one_line(answer, None)}')


def listed(items):
    # чего нет в данных страницы — «не видно», а не «нет»
    return ', '.join(items) if items else 'не видно'


def as_list(value, kind=dict):
    # на месте списка в данных карт бывает None или другой тип — такие места пропускать
    return [x for x in value if isinstance(x, kind)] if isinstance(value, list) else []


def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_str(value):
    return value if isinstance(value, str) else ''


def link(url):
    url = as_str(url)
    # 2ГИС заворачивает внешние ссылки в свой счётчик: link.2gis.ru/…?<настоящий адрес>
    try:
        if urllib.parse.urlsplit(url).netloc == 'link.2gis.ru' and '?' in url:
            url = url.split('?', 1)[1]
    except ValueError:
        pass
    # заготовка текста в ссылке WhatsApp — от карты, а не от клиента
    return re.sub(r'(wa\.me/\d+)\?text=.*', r'\1', url)


def button(caption, kind, value):
    caption = as_str(caption) or 'без подписи'
    if kind == 'phone':
        return f'кнопка «{caption}» набирает номер {value or "(номер не виден)"}'
    return f'кнопка «{caption}» → {link(value)}' if link(value) else f'кнопка «{caption}»'


def prices(title, items, total, note=''):
    """items: [(название, цена)]; печатает не больше 10."""
    if not items:
        print(f'{title}: не видно')
        return
    print(f'{title} ({min(len(items), 10)} из {max(total if isinstance(total, int) else 0, len(items))}{note}):')
    for name, price in items[:10]:
        print(f"  {one_line(as_str(name), 120) or 'без названия'} — {price}")


def facts(show, *args):
    # непривычные данные карточки не должны отнимать темы и отзывы, которые печатались и раньше
    try:
        show(*args)
    except Exception as e:
        print(f'Данные карточки: не разобрались ({type(e).__name__})')


def corrected(found, query):
    fixed = next((f for f in found if f and f.strip().lower() != query.strip().lower()), None)
    if fixed:
        print(f'ВНИМАНИЕ: карта исправила запрос «{query}» на «{fixed}» — сверить написание в результатах.')


def yandex_state(page):
    m = re.search(r'<script type="application/json" class="state-view">(.*?)</script>', page, re.S)
    if not m:
        sys.exit('Нет данных на странице Яндекса: капча или другая структура — открыть вручную или через WebFetch')
    return json.loads(m.group(1))


def yandex_orgs(state):
    # одна организация встречается в данных страницы несколько раз
    orgs = {}
    for o in walk(state, lambda d: 'ratingData' in d and 'title' in d and 'coordinates' in d):
        orgs.setdefault(o.get('id'), o)
    return list(orgs.values())


def ampm(hours):
    # Яндекс иногда пишет часы как «10:00 AM–8:00 PM»
    def rep(m):
        return f'{int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0):02d}:{m.group(2)}'
    return re.sub(r'(\d{1,2}):(\d{2})\s?(AM|PM)', rep, as_str(hours))


def yandex_facts(org, org_id):
    """Контакты, часы, запись, реклама и цены из данных той же страницы."""
    if str(org.get('id')) != org_id:
        # иначе контакты, реклама и цены другой организации со страницы сошли бы за клиентские
        print('Данные карточки: не видно — карточка клиента не найдена в данных страницы')
        return
    print('Телефоны:', listed([f"{p.get('value') or p.get('number')}" + (f" ({p['info']})" if as_str(p.get('info')) else '')
                               for p in as_list(org.get('phones')) if p.get('value') or p.get('number')]))
    print('Сайт:', listed(as_list(org.get('urls'), str)))
    print('Соцсети и мессенджеры:', listed([s['href'] for s in as_list(org.get('socialLinks')) if as_str(s.get('href'))]))
    print('Часы:', ampm(org.get('workingTimeText')) or 'не видно')
    advert, promo = as_dict(org.get('advert')), as_dict(org.get('promo'))
    partner = as_str(as_dict(as_dict(org.get('booking')).get('partner')).get('name'))
    booking = [f"онлайн-запись{' через ' + partner if partner else ''} → {b['href']}"
               for b in as_list(org.get('businessLinks')) if b.get('type') == 'booking' and as_str(b.get('href'))]
    if org.get('booking') and not booking:
        booking = [f'онлайн-запись через {partner or "Яндекс"}, ссылки в данных нет']
    booking += ['рекламная ' + button(b.get('title'), b.get('type'), b.get('value')) for b in as_list(advert.get('actionButtons'))]
    print('Запись:', listed(booking))
    if advert or promo.get('hasActiveAdvert'):
        client = as_dict(as_dict(advert.get('ordInfo')).get('client'))
        action = as_str(as_dict(promo.get('promoAction')).get('name'))
        print('Своя реклама в Яндексе: есть' + (f"; рекламодатель {client['name']}" if client.get('name') else '')
              + (f", ИНН {client['tin']}" if client.get('tin') else '')
              + (f'; акция «{one_line(action)}»' if action else ''))
    else:
        print('Своя реклама в Яндексе: не видно')
    # рекламодатель Яндекса закрывает свою карточку от чужой рекламы
    others = [f"{a.get('title')} ({a.get('id')})" for a in as_list(as_dict(org.get('relatedAdverts')).get('nearbyOnCard'))]
    hidden = as_dict(org.get('modularCard')).get('showCompetitors') is False
    print('Чужая реклама на карточке:', listed(others) if others or not hidden else 'нет, блок конкурентов на этой карточке выключен')
    top = as_dict(org.get('topObjects'))
    updated = as_str(as_dict(top.get('relevance')).get('lastUpdateTime'))
    prices('Цены в карточке', [(i.get('title'), f"{i['price']} {as_str(i.get('currency'))}".strip())
                               for c in as_list(top.get('categories')) for i in as_list(c.get('categoryItems')) if i.get('price')],
           top.get('fullObjectsCount'), f', обновлены {updated[:10]}' if updated else '')


def yandex(arg, full):
    org_id = re.search(r'(\d{6,})', arg).group(1)
    state = yandex_state(fetch(f'https://yandex.ru/maps/org/{org_id}/reviews/'))
    orgs = yandex_orgs(state)
    org = next((o for o in orgs if str(o.get('id')) == org_id), orgs[0] if orgs else {})
    rating = org.get('ratingData', {})
    lon, lat = org.get('coordinates', [None, None])
    print(f"{org.get('title')} — {org.get('address')}")
    print(f"Рейтинг {round(rating.get('ratingValue') or 0, 1)} · оценок {rating.get('ratingCount')} · отзывов {rating.get('reviewCount')}"
          f" · онлайн-запись в карточке: {'есть' if org.get('booking') else 'не видно'}")
    print(f'Координаты для поиска соседей: {lon},{lat}')
    facts(yandex_facts, org, org_id)
    aspects = next((d['aspects'] for d in walk(state, lambda d: isinstance(d.get('aspects'), list) and d['aspects'])), [])
    if aspects:
        print('\nТемы отзывов по оценке Яндекса (сначала с большей долей негатива):')
        for a in sorted(aspects, key=lambda a: a.get('negative', 0) / max(a.get('count', 1), 1), reverse=True):
            print(f"  {a['text']}: негатив {100 * a.get('negative', 0) / max(a.get('count', 1), 1):.0f}% из {a.get('count')}")
    print()
    report([
        (when(r['updatedTime']), int(r.get('rating') or 0),
         when(r['businessComment']['updatedTime']) if r.get('businessComment') else None,
         r.get('text'), 'Яндекс', (r.get('businessComment') or {}).get('text'))
        for r in walk(state, lambda d: 'reviewId' in d and 'updatedTime' in d)
    ], 'Яндекс отбирает их по релевантности, а не по дате', full)


def yandex_search(query, near, top):
    params = {'text': query}
    if near:
        lon, lat = (float(x) for x in near.split(','))
        params.update({'ll': f'{lon},{lat}', 'z': 15})
    state = yandex_state(fetch('https://yandex.ru/maps/?' + urllib.parse.urlencode(params)))
    corrected([d.get('requestCorrectedQuery') for d in walk(state, lambda d: 'requestCorrectedQuery' in d)], query)
    orgs = yandex_orgs(state)
    if near:
        # километры по плоскости: в пределах города погрешность мала
        km = lambda o: math.dist((o['coordinates'][0] * 111.32 * math.cos(math.radians(lat)), o['coordinates'][1] * 110.57),
                                 (lon * 111.32 * math.cos(math.radians(lat)), lat * 110.57))
        orgs = sorted(orgs, key=km)
    print(f'Яндекс, «{query}»: найдено {len(orgs)}, показаны первые {top}' + (' по расстоянию' if near else ''))
    print(('км | ' if near else '') + 'рейтинг | оценок | отзывов | название | адрес | ID')
    for o in orgs[:top]:
        r = o['ratingData']
        print((f'{km(o):.2f} | ' if near else '') + f"{round(r.get('ratingValue') or 0, 1)} | {r.get('ratingCount')} | {r.get('reviewCount')}"
              f" | {o['title']} | {o.get('address')} | {o.get('id')}")


def js_unescape(s):
    def rep(m):
        e = m.group(1)
        if e[0] in 'ux' and len(e) > 1:
            return chr(int(e[1:], 16))
        return {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f', 'v': '\v', '0': '\0'}.get(e, e)
    return re.sub(r'\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)', rep, s, flags=re.S)


def two_gis_data(page):
    # данные лежат строками внутри JSON.parse('…')
    for payload in re.findall(r"JSON\.parse\('((?:\\.|[^'\\])*)'\)", page, re.S):
        try:
            yield json.loads(js_unescape(payload).encode('utf-16', 'surrogatepass').decode('utf-16'))
        except ValueError:
            continue


DAYS = (('Mon', 'пн'), ('Tue', 'вт'), ('Wed', 'ср'), ('Thu', 'чт'), ('Fri', 'пт'), ('Sat', 'сб'), ('Sun', 'вс'))


def two_gis_hours(schedule):
    schedule = as_dict(schedule)
    if schedule.get('is_24x7'):
        return 'круглосуточно'
    days = [(short, ', '.join(f"{h['from']}–{h['to']}" for h in as_list(as_dict(schedule.get(day)).get('working_hours'))
                              if h.get('from') and h.get('to')) or 'выходной')
            for day, short in DAYS]
    if all(hours == 'выходной' for _, hours in days):
        return 'не видно'
    groups = []  # подряд идущие дни с одинаковыми часами: [первый, последний, часы]
    for short, hours in days:
        if groups and groups[-1][2] == hours:
            groups[-1][1] = short
        else:
            groups.append([short, short, hours])
    if len(groups) == 1:
        return f'ежедневно {groups[0][2]}'
    return '; '.join(f"{first}{'–' + last if last != first else ''} {hours}" for first, last, hours in groups)


def same_firm(targets, contacts):
    """Что из рекламного блока совпало с контактами карточки: только так видно, что реклама этой фирмы."""
    plain = lambda u: re.sub(r'^https?://(www\.)?', '', link(u).lower()).rstrip('/')
    number = lambda u: re.sub(r'\D', '', link(u))[-10:]
    numbers = {number(c.get('value')) for c in contacts if c.get('type') in ('phone', 'fax', 'whatsapp', 'viber', 'telegram')}
    links = {plain(c.get('value')) for c in contacts} - {''}
    found = []
    for target in targets:
        if len(number(target)) == 10 and number(target) in numbers:
            found.append('телефон')
        elif plain(target) in links:
            found.append('ссылка')
    return ', '.join(sorted(set(found), reverse=True))


def two_gis_facts(datas, firm, with_prices):
    """Контакты, часы, запись, реклама и цены из данных той же страницы."""
    branch = max((b for data in datas for b in walk(data, lambda d: d.get('type') == 'branch' and 'name' in d
                                                     and str(d.get('id', '')).split('_')[0] == firm)), key=len, default=None)
    if not branch:
        print('Данные карточки: не видно — карточка филиала не найдена в данных страницы')
        return
    contacts = [c for g in as_list(branch.get('contact_groups')) for c in as_list(g.get('contacts'))]
    value = lambda c: link(c.get('value') or c.get('text'))
    print('Телефоны:', listed([f"{c['value']}" + (' (факс)' if c.get('type') == 'fax' else '') + (f" ({c['comment']})" if as_str(c.get('comment')) else '')
                               for c in contacts if c.get('type') in ('phone', 'fax') and c.get('value')]))
    print('Почта:', listed([value(c) for c in contacts if c.get('type') == 'email' and value(c)]))
    print('Сайт:', listed([value(c) for c in contacts if c.get('type') == 'website' and value(c)]))
    print('Соцсети и мессенджеры:', listed([value(c) for c in contacts if c.get('type') not in ('phone', 'fax', 'email', 'website') and value(c)]))
    print('Часы:', two_gis_hours(branch.get('schedule')))
    # кнопка записи и реклама лежат в рекламном блоке, привязанном к фирме в данных страницы: «<поиск>_<ID фирмы>»
    # (на сохранённых страницах ключ всегда вида «<uuid>_<ID фирмы>»)
    ads = as_dict(next((as_dict(ctx).get('ads') for data in datas for holder in walk(data, lambda d: isinstance(d.get('searchContext'), dict))
                        for key, ctx in holder['searchContext'].items() if str(key).endswith('_' + firm) and as_dict(ctx).get('ads')), {}))
    options, ad_link = as_dict(ads.get('options')), as_dict(ads.get('link'))
    actions = as_list(options.get('actions'))
    # чей блок, в данных прямо не сказано: своим он считается, только если его телефон или ссылка совпали с карточкой
    matched = same_firm([a.get('value') for a in actions] + [ad_link.get('value')], contacts) if ads else ''
    caveat = ' (кнопка из рекламного блока; чей он — по данным страницы не подтверждается)' if actions and not matched else ''
    print('Запись:', listed([button(a.get('caption') or a.get('name'), a.get('type'), a.get('value')) for a in actions]) + caveat)
    if ads:
        print(('Своя реклама в 2ГИС: есть' + f' (совпадение с карточкой: {matched})' if matched else
               'Рекламный блок в карточке 2ГИС: есть; чей он — по данным страницы не подтверждается')
              + (f"; «{one_line(as_str(ads.get('text')))}»" if as_str(ads.get('text')) else '')
              + (f"; рекламодатель {options['legal_name']}" if options.get('legal_name') else '')
              + (f"; ссылка «{as_str(ad_link.get('text')) or 'без подписи'}» в объявлении → {link(ad_link.get('value'))}" if link(ad_link.get('value')) else '')
              + ('; в данных есть и показ на карточках конкурентов' if options.get('competitor_poi') else ''))
    else:
        print('Своя реклама в 2ГИС: не видно')
    print('Чужая реклама на карточке: не видно — в данных страницы 2ГИС её нет')
    tags = [a['name'].replace('\xa0', ' ') for g in as_list(branch.get('attribute_groups')) for a in as_list(g.get('attributes'))
            if '₽' in as_str(a.get('name'))]
    print('Цены в карточке:', listed(tags) + ('' if with_prices else ' (весь прайс — флаг --prices)'))


def two_gis_price(offer):
    value = as_dict(offer.get('price_value'))
    part = lambda key: as_dict(value.get(key)) if as_dict(value.get(key)).get('value') is not None else {}
    rub = lambda v: f"{v['value']} {'₽' if v.get('currency', 'RUB') == 'RUB' else v.get('currency')}"
    fixed, low, high = part('fixed'), part('from'), part('to')
    if fixed:
        return rub(fixed)
    if low and high:
        return f"{low['value']}–{rub(high)}"
    if low or high:
        return ('от ' + rub(low)) if low else ('до ' + rub(high))
    return f"{offer['price']} ₽" if offer.get('price') else 'цена не указана'


def two_gis_prices(city, firm):
    time.sleep(3)  # второй запрос к карте — не сразу за первым
    datas = list(two_gis_data(fetch(f'https://2gis.ru/{city}/firm/{firm}/tab/prices')))
    names = {d['product'].get('id'): d['product'].get('name') for data in datas for d in walk(data, lambda d: isinstance(d.get('product'), dict))}
    offers = {}
    for data in datas:
        for o in walk(data, lambda d: 'productId' in d and ('price_value' in d or 'price' in d)):
            offers.setdefault(o['productId'], o)
    info = next((d for data in datas for d in walk(data, lambda d: isinstance(d.get('list_info'), dict))), {})
    updated = as_str(info.get('updated_at'))
    prices('Прайс со вкладки «Цены»', [(names.get(pid) or str(pid), two_gis_price(o)) for pid, o in offers.items()],
           info.get('total'), f', {updated[0].lower()}{updated[1:]}' if updated else '')


def two_gis(arg, city, full, with_prices):
    m = re.search(r'2gis\.\w+/([\w-]+)/firm/(\d+)', arg)
    city, firm = (m.group(1), m.group(2)) if m else (city, re.search(r'(\d{6,})', arg).group(1))
    page = fetch(f'https://2gis.ru/{city}/firm/{firm}/tab/reviews')
    title = re.search(r'<title>(.*?)</title>', page, re.S)
    print(html.unescape(title.group(1)).replace('Отзывы о ', '').replace(' - 2ГИС', '') if title else firm)
    datas = list(two_gis_data(page))
    for data in datas:
        box = next(iter(walk(data, lambda d: 'items' in d and 'orgRating' in d)), None)
        if not box:
            continue
        print(f"Рейтинг {box.get('orgRating') or box.get('rating')} · отзывов в ленте {box.get('total')}")
        facts(two_gis_facts, datas, firm, with_prices)
        if with_prices:
            # 404, 429 или капча на второй странице не должны отнимать уже полученные карточку и отзывы
            try:
                two_gis_prices(city, firm)
            except SystemExit as e:
                print(f'Прайс со вкладки «Цены»: не видно ({e})')
            except Exception as e:
                print(f'Прайс со вкладки «Цены»: не видно ({type(e).__name__})')
        print()
        report([
            (when(r['date_created']), r.get('rating') or 0,
             when(r['official_answer']['date_created']) if r.get('official_answer') else None,
             r.get('text'), r.get('provider') or '2gis', (r.get('official_answer') or {}).get('text'))
            for r in box['items'] if r.get('date_created')
        ], 'первые в ленте 2ГИС, порядок у неё свой', full)
        return
    sys.exit('Нет данных на странице 2ГИС: капча или другая структура — открыть вручную или через WebFetch')


def two_gis_search(query, city, top):
    page = fetch(f'https://2gis.ru/{city}/search/{urllib.parse.quote(query)}')
    branches, fixes = {}, []
    for data in two_gis_data(page):
        for b in walk(data, lambda d: d.get('type') == 'branch' and 'name' in d and 'id' in d):
            branches.setdefault(b['id'], b)
        fixes += [d['query_fix'].get('corrected_query') for d in walk(data, lambda d: isinstance(d.get('query_fix'), dict))]
    corrected(fixes, query)
    print(f'2ГИС, «{query}» ({city}): найдено {len(branches)}, показаны первые {top}')
    print('рейтинг | отзывов | название | адрес | ID')
    for b in list(branches.values())[:top]:
        r = b.get('reviews') or {}
        print(f"{r.get('general_rating')} | {r.get('general_review_count')} | {b['name']} | {b.get('address_name')} | {b['id']}")


ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest='cmd', required=True)
ys = sub.add_parser('yandex-search')
ys.add_argument('query')
ys.add_argument('--near')
ys.add_argument('--top', type=int, default=8)
yc = sub.add_parser('yandex')
yc.add_argument('card')
yc.add_argument('--full', action='store_true')
gs = sub.add_parser('2gis-search')
gs.add_argument('query')
gs.add_argument('--city', default='moscow')
gs.add_argument('--top', type=int, default=8)
gc = sub.add_parser('2gis')
gc.add_argument('card')
gc.add_argument('--city', default='moscow')
gc.add_argument('--full', action='store_true')
gc.add_argument('--prices', action='store_true')
args = ap.parse_args()

if args.cmd == 'yandex-search':
    yandex_search(args.query, args.near, args.top)
elif args.cmd == 'yandex':
    yandex(args.card, args.full)
elif args.cmd == '2gis-search':
    two_gis_search(args.query, args.city, args.top)
else:
    two_gis(args.card, args.city, args.full, args.prices)
