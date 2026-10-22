"""Посты канала по месяцам: сколько их, какие просмотры, на какие адреса ссылаются, о чём.

python3 -I by_month.py posts.jsonl [--links] [--text 300]
--links   на какие адреса ссылаются посты, где бы ссылка ни стояла; пост считается один раз на адрес.
          Новый адрес — новый продукт или канал продаж, пропавший — то, что перестали продвигать.
--text N  посты по месяцам: дата, просмотры, адреса и первые N знаков текста — чтобы прочитать
          и решить, что продвигает каждый пост. Решать по смыслу, а не по словам.
"""
import argparse
import collections
import json
import statistics
import urllib.parse

ap = argparse.ArgumentParser()
ap.add_argument('posts')
ap.add_argument('--links', action='store_true')
ap.add_argument('--text', type=int, default=0, metavar='N')
args = ap.parse_args()


def target(link):
    # у t.me важен канал или бот, у остальных сайтов — домен
    u = urllib.parse.urlparse(link)
    host = u.netloc.removeprefix('www.')
    parts = u.path.strip('/').split('/')
    if host not in ('t.me', 'telegram.me') or not parts[0]:
        return host
    # t.me/m/<код> ведёт в конкретный аккаунт, у каждой такой ссылки свой адресат
    return f'{host}/m/{parts[1]}' if parts[0] == 'm' and len(parts) > 1 else f'{host}/{parts[0]}'


def targets(post):
    # Telegram сам превращает в ссылки слова вида CLAUDE.md или FL.ru: у них заглавные буквы в адресе
    return sorted({t for t in map(target, post.get('links', [])) if t and t == t.lower()})


months = collections.defaultdict(list)
for line in open(args.posts, encoding='utf-8'):
    if line.strip():
        post = json.loads(line)
        months[post['date'][:7]].append(post)

print('месяц\tпостов\tмедиана просмотров')
for key in sorted(months):
    print(f"{key}\t{len(months[key])}\t{int(statistics.median(p.get('views', 0) for p in months[key]))}")

if args.links:
    print('\nмесяц\tна что ссылаются посты: адрес × постов (пять самых частых)')
    for key in sorted(months):
        counts = collections.Counter(t for p in months[key] for t in targets(p))
        print(key + '\t' + ', '.join(f'{t} ×{n}' for t, n in counts.most_common(5)))

if args.text:
    for key in sorted(months):
        print(f'\n== {key}')
        for p in months[key]:
            text = ' '.join(p['text'].split())[:args.text]
            print(f"{p['date']} | {p.get('views', 0)} | {', '.join(targets(p)) or '—'} | {text}")
