"""Посты из страниц публичного превью t.me/s/<канал>: по строке JSON на пост, без дублей, по возрастанию номера.

python3 -I tg_posts.py pages/*.html > posts.jsonl
"""
import html
import json
import re
import sys


def count(views):
    # «4.08K» → 4080, «1.2M» → 1200000
    if not views:
        return 0
    if views[-1] in 'KM':
        return int(float(views[:-1]) * (1000 if views[-1] == 'K' else 1_000_000))
    return int(float(views))


def posts(path):
    page = open(path, encoding='utf-8', errors='replace').read()
    for p in re.split(r'<div class="tgme_widget_message_wrap', page)[1:]:
        num = re.search(r'data-post="[^/"]+/(\d+)"', p)
        date = re.search(r'<time datetime="([^"]+)"', p)
        if not (num and date):
            continue
        body = re.search(r'<div class="tgme_widget_message_text js-message_text"[^>]*>(.*?)</div>', p, re.S)
        raw = body.group(1) if body else ''
        views = re.search(r'<span class="tgme_widget_message_views">([^<]+)</span>', p)
        yield {
            'id': int(num.group(1)),
            'date': date.group(1)[:10],
            'views': count(views.group(1) if views else ''),
            'reactions': sum(int(x) for x in re.findall(r'<span class="tgme_reaction">.*?</i>(\d+)</span>', p, re.S)),
            'media': 'video' if 'tgme_widget_message_video' in p else 'photo' if 'tgme_widget_message_photo' in p else '',
            'forwarded': 'tgme_widget_message_forwarded_from' in p,
            'text': html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', '\n', raw))).strip(),
            'links': re.findall(r'href="([^"]+)"', raw),
        }


found = {}
for path in sys.argv[1:]:
    for post in posts(path):
        found[post['id']] = post
for num in sorted(found):
    print(json.dumps(found[num], ensure_ascii=False))
