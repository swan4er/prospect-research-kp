"""Открывается ли каждая ссылка страницы: код ответа или ошибка.

python3 -I check_links.py page.html https://site.ru/
Проверяет только ссылки <a>. Якоря, mailto:, tel: и ссылки в приложения пропускает, неизвестные схемы помечает. Ссылки, которые появляются только из JS, не видит —
их ловит page_audit.cjs в настоящем браузере. Кириллицу в домене, пути и запросе проверяет; ссылку, которую проверить не удалось,
печатает с причиной и идёт дальше.
"""
import concurrent.futures
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

KNOWN_SCHEMES = ('http', 'https', 'mailto', 'tel', 'javascript', 'sms', 'tg', 'whatsapp', 'viber', 'skype')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36'


def ascii_url(url):
    # запрос уходит только в ASCII: домен с кириллицей — в punycode, кириллица в пути и запросе — в %-коды
    parts = urllib.parse.urlsplit(url)
    user, at, hostport = parts.netloc.rpartition('@')
    host, colon, port = hostport.partition(':')
    if not host.isascii():
        host = host.encode('idna').decode('ascii')
    safe = "/%:@!$&'()*+,;=~?"
    return urllib.parse.urlunsplit((parts.scheme, user + at + host + colon + port,
                                    urllib.parse.quote(parts.path, safe=safe), urllib.parse.quote(parts.query, safe=safe), ''))


def status(url):
    for method in ('HEAD', 'GET'):
        try:
            req = urllib.request.Request(ascii_url(url), method=method, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return str(resp.status)
        except urllib.error.HTTPError as e:
            # часть сайтов не отвечает на HEAD — повторить через GET
            if method == 'HEAD' and e.code in (403, 405, 501):
                continue
            return str(e.code)
        except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
            return f'ошибка: {getattr(e, "reason", e)}'
        except Exception as e:
            # одна непроверяемая ссылка не должна останавливать проверку остальных
            return f'ошибка: {type(e).__name__}: {e}'
    return '?'


page, base = sys.argv[1], sys.argv[2]
html = open(page, encoding='utf-8', errors='replace').read()
links = []
# только ссылки <a>: шрифты, стили и скрипты из <link> — шум
for href in re.findall(r'<a\b[^>]*?\bhref="([^"]+)"', html, re.I):
    href = href.replace('&amp;', '&')
    # куски шаблонов из кода страницы («%url%», «'+b+'», «{{…}}») — не ссылки;
    # закодированные символы (%D0%91 — кириллица) шаблоном не считать
    if re.search(r"['\"]\s*\+|%\w+%|\{\{|\$\{", re.sub(r'%[0-9A-Fa-f]{2}', '', href)):
        continue
    try:
        scheme = urllib.parse.urlparse(href).scheme
        url = urllib.parse.urljoin(base, href)
    except ValueError as e:
        # например «http://[…» — адрес не разбирается
        print(f'!! ошибка: {e}\t{href}')
        continue
    if scheme and scheme not in KNOWN_SCHEMES:
        # например «mail:» вместо «mailto:» — такая ссылка не откроется
        print(f'!! схема «{scheme}:»\t{href}')
        continue
    if href.startswith(('#', 'mailto:', 'tel:', 'javascript:')) or scheme not in ('', 'http', 'https'):
        continue
    if url.startswith('http') and url not in links:
        links.append(url)

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    for url, code in zip(links, pool.map(status, links)):
        mark = '  ' if code.startswith(('2', '3')) else '!!'
        print(f'{mark} {code}\t{url}')
