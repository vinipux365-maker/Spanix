"""Обновляет prices.json: самая дешёвая цена продажи каждой коллекции на Fragment.

Список коллекций берётся из массива NFTS в index.html, так что новые коллекции
подхватываются сами. Запускается GitHub Actions по расписанию (.github/workflows/prices.yml).
"""
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRICES = ROOT / 'prices.json'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
PRICE_RE = re.compile(r'tm-grid-item-value[^"]*icon-ton[^"]*"[^>]*>\s*([\d][\d,\s]*(?:\.\d+)?)')


def slugs():
    html = (ROOT / 'index.html').read_text('utf-8')
    block = html[html.index('const NFTS = ['):]
    block = block[:block.index('];')]
    return re.findall(r"\['([a-z0-9]+)', ", block)


def floor(slug):
    url = f'https://fragment.com/gifts/{slug}?sort=price_asc&filter=sale'
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en'})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode('utf-8', 'replace')
    m = PRICE_RE.search(html)
    return float(m.group(1).replace(',', '').replace(' ', '')) if m else None


def main():
    try:
        old = json.loads(PRICES.read_text('utf-8')).get('prices', {})
    except Exception:
        old = {}
    prices, fails = dict(old), []
    for s in slugs():
        for attempt in range(3):
            try:
                v = floor(s)
                if v:
                    prices[s] = int(v) if v == int(v) else v
                else:
                    fails.append(s)
                break
            except Exception as e:  # сеть / лимит запросов — пробуем ещё раз
                if attempt == 2:
                    fails.append(f'{s} ({e})')
                time.sleep(2 + attempt * 3)
        time.sleep(0.4)
    got = len(prices) - len([f for f in fails if f.split(' ')[0] not in old])
    print(f'Цены: {got} коллекций, без цены: {len(fails)}')
    if fails:
        print('Не получилось:', ', '.join(fails))
    if got < 10:
        raise SystemExit('Fragment не ответил — оставляю старые цены')
    PRICES.write_text(json.dumps({
        'updated': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'source': 'fragment.com — самая дешёвая цена продажи',
        'prices': prices,
    }, ensure_ascii=False, indent=1), 'utf-8')


if __name__ == '__main__':
    main()
