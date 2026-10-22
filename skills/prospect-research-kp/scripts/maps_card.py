"""Карты: поиск, карточка, темы и отзывы, ответы владельца. Без браузера и без имён авторов отзывов.

python3 -I maps_card.py yandex-search "<что искать>" [--near долгота,широта] [--top 8]
python3 -I maps_card.py yandex <адрес карточки Яндекса или ID> [--full]
python3 -I maps_card.py 2gis-search "<что искать>" [--city moscow] [--top 8]
python3 -I maps_card.py 2gis <адрес карточки 2ГИС или ID фирмы> [--city moscow] [--full]

Автоматический браузер карты блокируют (429, капча), обычные запросы — нет: страницы приходят
с данными внутри. Если 2ГИС отвечает «обновите браузер», поднять версию Chrome в переменной UA.
Поиск обеих карт молча исправляет запрос — скрипт печатает исправление: сверять написание.
Обе карты отдают выборку из 50 отзывов, не обязательно самых свежих.
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


def two_gis(arg, city, full):
    m = re.search(r'2gis\.\w+/([\w-]+)/firm/(\d+)', arg)
    city, firm = (m.group(1), m.group(2)) if m else (city, re.search(r'(\d{6,})', arg).group(1))
    page = fetch(f'https://2gis.ru/{city}/firm/{firm}/tab/reviews')
    title = re.search(r'<title>(.*?)</title>', page, re.S)
    print(html.unescape(title.group(1)).replace('Отзывы о ', '').replace(' - 2ГИС', '') if title else firm)
    for data in two_gis_data(page):
        box = next(iter(walk(data, lambda d: 'items' in d and 'orgRating' in d)), None)
        if not box:
            continue
        print(f"Рейтинг {box.get('orgRating') or box.get('rating')} · отзывов в ленте {box.get('total')}\n")
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
args = ap.parse_args()

if args.cmd == 'yandex-search':
    yandex_search(args.query, args.near, args.top)
elif args.cmd == 'yandex':
    yandex(args.card, args.full)
elif args.cmd == '2gis-search':
    two_gis_search(args.query, args.city, args.top)
else:
    two_gis(args.card, args.city, args.full)
