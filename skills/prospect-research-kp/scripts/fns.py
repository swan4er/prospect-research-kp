"""Юрлицо по реестру ФНС и его бухотчётность — без капчи и без сторонних сайтов.

python3 -I fns.py find "<название, ИНН или ОГРН>" [--region 26]
python3 -I fns.py money <ИНН>

find  — ЕГРЮЛ и ЕГРИП: название, ИНН, ОГРН, дата регистрации, руководитель. Ищет с учётом опечаток
        по всей России, но не по ФИО руководителей и учредителей.
money — бухотчётность ООО (ГИР БО): выручка и чистая прибыль по годам. У ИП её нет.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'


def get(url, form=None):
    data = urllib.parse.urlencode(form).encode() if form else None
    req = urllib.request.Request(url, data=data, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode('utf-8'))


def find(query, region):
    form = {'query': query, **({'region': region} if region else {})}
    token = get('https://egrul.nalog.ru/', form)
    if token.get('captchaRequired'):
        sys.exit('ФНС просит капчу — открыть egrul.nalog.ru вручную')
    time.sleep(1)  # результат готовится не сразу
    rows = get(f"https://egrul.nalog.ru/search-result/{token['t']}").get('rows', [])
    if not rows:
        print('Ничего не найдено.')
    for r in rows:
        kind = 'ИП' if r.get('k') == 'fl' else 'юрлицо'
        print(f"{r.get('c') or r.get('n')} | {kind} | ИНН {r.get('i')} | ОГРН {r.get('o')} | с {r.get('r')} | {r.get('g') or ''}")


def money(inn):
    query = urllib.parse.urlencode({'query': inn, 'page': 0})
    found = get(f'https://bo.nalog.gov.ru/advanced-search/organizations/search?{query}').get('content', [])
    if not found:
        sys.exit('В ГИР БО отчётности нет: ИП, новая компания или неверный ИНН')
    org = found[0]
    print(re.sub(r'<[^>]+>', '', org.get('shortName') or org.get('fullName') or inn), '— выручка и чистая прибыль, тыс. ₽')
    for rep in sorted(get(f"https://bo.nalog.gov.ru/nbo/organizations/{org['id']}/bfo/"), key=lambda x: x.get('period')):
        results = [(tc.get('correction') or {}).get('financialResult') for tc in rep.get('typeCorrections', [])]
        fin = next((f for f in results if f), {})
        print(f"{rep.get('period')} | выручка {fin.get('current2110')} | прибыль {fin.get('current2400')}")


ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest='cmd', required=True)
f = sub.add_parser('find')
f.add_argument('query')
f.add_argument('--region')
m = sub.add_parser('money')
m.add_argument('inn')
args = ap.parse_args()

if args.cmd == 'find':
    find(args.query, args.region)
else:
    money(args.inn)
