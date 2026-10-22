/* Страница в настоящем браузере — глазами посетителя с компьютера и с телефона.
 *
 * NODE_PATH=<node_modules с playwright> node page_audit.cjs <адрес> <папка для результатов>
 * CHROME_PATH=<путь к Chromium> — если у Playwright нет своей версии браузера.
 *
 * Сохраняет {desktop,mobile}-first-screen.png, {desktop,mobile}-full.jpg (до 8000 px) и report.json:
 * время загрузки, ошибки консоли и скриптов, упавшие запросы и ответы 4xx/5xx,
 * заголовок и теги превью, горизонтальный скролл, текст за краем экрана,
 * мелкие зоны нажатия, кнопки первого экрана, формы с полями, на каком экране цена, форма и
 * главная кнопка, адреса, к которым ходит страница (по ним видна аналитика, которую подгружает скрипт).
 * Перед снимком всей страницы прокручивает её, чтобы подгрузились блоки, появляющиеся при прокрутке.
 */
const { chromium, devices } = require('playwright');
const fs = require('fs');
const path = require('path');

const [url, out] = process.argv.slice(2);
if (!url || !out) {
  console.error('node page_audit.cjs <адрес> <папка для результатов>');
  process.exit(2);
}
fs.mkdirSync(out, { recursive: true });

const VIEWS = {
  desktop: { viewport: { width: 1440, height: 900 } },
  // плотность 3, как у iPhone, превращает длинную страницу в снимок на сотни мегабайт памяти
  mobile: { ...devices['iPhone 13'], deviceScaleFactor: 2 },
};
const FULL_PAGE_LIMIT = 8000; // css px

async function audit(browser, name, options) {
  const context = await browser.newContext({ ...options, locale: 'ru-RU' });
  const page = await context.newPage();
  const errors = { console: [], scripts: [], failedRequests: [], httpErrors: [] };
  page.on('console', m => m.type() === 'error' && errors.console.push(m.text().slice(0, 300)));
  page.on('pageerror', e => errors.scripts.push(String(e).slice(0, 300)));
  page.on('requestfailed', r => errors.failedRequests.push(`${r.failure()?.errorText} ${r.url().slice(0, 200)}`));
  page.on('response', r => r.status() >= 400 && errors.httpErrors.push(`${r.status()} ${r.url().slice(0, 200)}`));
  const hosts = new Set();
  page.on('request', r => hosts.add(new URL(r.url()).hostname));

  const started = Date.now();
  await page.goto(url, { waitUntil: 'load', timeout: 60000 });
  const loadMs = Date.now() - started;
  await page.waitForTimeout(2000); // ленивые блоки, счётчики, всплывающие окна

  const facts = await page.evaluate(() => {
    const meta = key => document.querySelector(`meta[name="${key}"], meta[property="${key}"]`)?.content || null;
    const box = el => el.getBoundingClientRect();
    const shown = el => box(el).width > 0 && box(el).height > 0;
    const words = el => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    const clickable = [...document.querySelectorAll('a, button, input, select, textarea')].filter(shown);
    // карусели и бегущие строки шире экрана намеренно — их не считать
    const inScroller = el => {
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        if (getComputedStyle(a).overflowX !== 'visible' && a.scrollWidth > a.clientWidth + 1) return true;
      }
      return false;
    };
    // на каком экране от верха страницы стоит элемент
    const screen = el => (el ? Math.round(((box(el).top + window.scrollY) / window.innerHeight) * 10) / 10 : null);
    const price = [...document.querySelectorAll('body *')]
      .find(el => el.children.length === 0 && shown(el) && /\d\s?(₽|руб)/.test(el.textContent));
    const mainButton = clickable
      .find(el => el.matches('a, button') && /запис|купить|заказ|оформ|заявк|начать|оплат/i.test(words(el)));
    const overflows = el => {
      // вылез за край экрана или за свой блок: отступы съедены, наклонные буквы обрезаются
      const right = box(el).right;
      if (right > window.innerWidth + 0.5 || right > box(el.parentElement).right + 1) return true;
      // внутри блока считать только спрятанное переполнение — то есть обрезанный текст
      const s = getComputedStyle(el);
      return s.display !== 'inline' && s.overflowX !== 'visible' && el.scrollWidth > el.clientWidth + 1;
    };
    return {
      title: document.title || null,
      description: meta('description'),
      ogTitle: meta('og:title'),
      ogImage: meta('og:image'),
      horizontalScroll: document.documentElement.scrollWidth > window.innerWidth + 1,
      // текст за краем экрана или обрезан внутри блока — сверить со скриншотом
      overflowingText: [...new Set(
        [...document.querySelectorAll('h1, h2, h3, h4, h5, h6, p, a, button, li, span')]
          .filter(el => shown(el) && words(el) && !inScroller(el) && overflows(el))
          .map(words),
      )].slice(0, 10),
      pageHeight: document.documentElement.scrollHeight,
      screens: { price: screen(price), form: screen(document.querySelector('form, input[type=email], input[type=tel]')), mainButton: screen(mainButton) },
      // меньше 44×44 — трудно попасть пальцем; смотреть в отчёте телефона
      smallTargets: clickable.filter(el => box(el).width < 44 || box(el).height < 44).length,
      firstScreen: clickable
        .filter(el => box(el).top < window.innerHeight && el.matches('a, button'))
        .map(el => ({ text: words(el), href: el.getAttribute('href') }))
        .filter(x => x.text)
        .slice(0, 40),
      forms: [...document.querySelectorAll('form')].map(f => ({
        action: f.getAttribute('action'),
        fields: [...f.querySelectorAll('input, textarea, select')]
          .filter(i => i.type !== 'hidden')
          .map(i => ({ type: i.type, name: i.name || null, placeholder: i.placeholder || null, required: i.required })),
        buttons: [...f.querySelectorAll('button, input[type=submit]')].map(words),
      })),
    };
  });

  await page.screenshot({ path: path.join(out, `${name}-first-screen.png`) });
  // блоки, которые появляются при прокрутке, без неё на снимке пустые
  for (let y0 = 0; y0 < Math.min(facts.pageHeight, FULL_PAGE_LIMIT); y0 += 600) {
    await page.evaluate(y => window.scrollTo(0, y), y0);
    await page.waitForTimeout(150);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  await page.screenshot({
    path: path.join(out, `${name}-full.jpg`),
    type: 'jpeg',
    quality: 70,
    fullPage: true,
    clip: { x: 0, y: 0, width: page.viewportSize().width, height: Math.min(facts.pageHeight, FULL_PAGE_LIMIT) },
  });
  await context.close();
  return { loadMs, ...facts, ...errors, domains: [...hosts].filter(Boolean).sort() };
}

(async () => {
  const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
  const report = { url, checkedAt: new Date().toISOString() };
  for (const [name, options] of Object.entries(VIEWS)) report[name] = await audit(browser, name, options);
  await browser.close();
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
})().catch(e => {
  console.error(e);
  process.exit(1);
});
