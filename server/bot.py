# SDELKA — бот для мини-аппа. Нужен только Python 3.8+, ничего ставить не надо.
#
# Что делает:
#  1. Спрашивает токен бота (один раз) и хранит его здесь же в config.json.
#  2. Качает картинки обычных подарков Telegram в site/gifts.
#  3. Прописывает имя бота в site/index.html (для реферальных ссылок).
#  4. Создаёт ссылки на оплату звёздами (Telegram Stars) для пакетов пополнения.
#  5. Ставит в боте кнопку «Играть», которая открывает мини-апп.
#  6. Отвечает на /start, принимает оплату звёздами и пишет платежи в payments.json.
#
# Флаги:  --url    заново спросить ссылку на мини-апп
#         --gifts  заново скачать картинки подарков
#         --token  заново спросить токен
#         --server режим для сервера: ничего не спрашивает, токен берёт из config.json

import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / 'site'
CFG = ROOT / 'config.json'
PAYMENTS = ROOT / 'payments.json'
WITHDRAWALS = ROOT / 'withdrawals.json'   # заявки на вывод подарков
CREDITS = ROOT / 'credits.json'           # подарки, присланные владельцу: ждут зачисления в мини-апп
GIFTS_SEEN = ROOT / 'gifts_seen.json'     # подарки на аккаунте владельца, которые бот уже видел
PROMO_USED = ROOT / 'promo_used.json'      # кто какие промокоды активировал
STATS = ROOT / 'stats.json'               # снимки игроков для статистики
FEED = ROOT / 'feed.json'                 # последние игры всех игроков: кто где сколько выиграл
GIFT_POLL = 30                            # как часто проверять новые подарки, секунд
API_PORT = 8787                          # сервер принимает заявки из мини-аппа (Caddy проксирует /api/*)
SUPPORT = os.environ.get('SUPPORT_URL', 'https://t.me/твой_username')
DEFAULT_URL = 'https://ТВОЙ_GITHUB.github.io/ИМЯ_РЕПО/'
PACKS = [50, 100, 250, 500, 1000, 2500]   # пакеты звёзд — такие же, как CONFIG.starPacks в index.html
OWNER_USERNAME = os.environ.get('OWNER_USERNAME', 'твой_username')  # резервный username владельца

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def load_cfg():
    try:
        return json.loads(CFG.read_text('utf-8'))
    except Exception:
        return {}


def save_cfg():
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), 'utf-8')


cfg = load_cfg()
TOKEN = None if '--token' in sys.argv else (os.environ.get('BOT_TOKEN') or cfg.get('token'))
SERVER = '--server' in sys.argv


def api(method, params=None, timeout=40):
    body = json.dumps({k: v for k, v in (params or {}).items() if v is not None}).encode()
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{TOKEN}/{method}',
        data=body,
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        res = json.load(e)
    if not res.get('ok'):
        raise RuntimeError(f"{method}: {res.get('description')}")
    return res['result']


def ask_token():
    global TOKEN
    print('Открой @BotFather → /mybots → свой бот → API Token и скопируй токен.')
    while True:
        t = input('Вставь токен бота и нажми Enter: ').strip()
        if not re.fullmatch(r'\d+:[\w-]{30,}', t):
            print('Это не похоже на токен. Он выглядит так: 123456789:AAH...\n')
            continue
        TOKEN = t
        try:
            me = api('getMe')
        except Exception as e:
            print('Telegram не принял токен:', e, '\n')
            continue
        cfg['token'] = t
        save_cfg()
        print('Токен сохранён в config.json (только на этом компьютере).\n')
        return me


def patch_site(username):
    page = SITE / 'index.html'
    if not page.exists():
        print('Нет файла site/index.html — положи мини-апп в папку site.')
        return
    html = page.read_text('utf-8')
    new = re.sub(r"botUsername:\s*'[^']*'", f"botUsername: '{username}'", html, count=1)
    if new != html:
        page.write_text(new, 'utf-8')
        print(f'В site/index.html прописан бот @{username}.')


def fetch_gifts():
    print('Качаю картинки обычных подарков Telegram…')
    folder = SITE / 'gifts'
    folder.mkdir(parents=True, exist_ok=True)
    gifts = api('getAvailableGifts')['gifts']
    out = []
    for g in gifts:
        st = g.get('sticker') or {}
        thumb = st.get('thumbnail') or st.get('thumb')
        out.append({
            'id': g['id'],
            'stars': g.get('star_count'),
            'emoji': st.get('emoji', ''),
            'limited': bool(g.get('total_count')),
        })
        if not thumb:
            continue
        f = api('getFile', {'file_id': thumb['file_id']})
        url = f"https://api.telegram.org/file/bot{TOKEN}/{f['file_path']}"
        with urllib.request.urlopen(url, timeout=30) as r:
            (folder / f"{g['id']}.webp").write_bytes(r.read())
    (folder / 'gifts.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), 'utf-8')
    print(f'Готово: {len(out)} подарков в site/gifts.\n')


def ask_url():
    print('Ссылка на мини-апп. Сейчас он лежит на GitHub Pages:', DEFAULT_URL)
    while True:
        u = input('Нажми Enter, чтобы оставить её, или вставь свою https:// ссылку: ').strip()
        if not u:
            u = DEFAULT_URL
        if u.startswith('https://'):
            cfg['webapp_url'] = u
            save_cfg()
            print()
            return u
        print('Telegram открывает мини-аппы только по https:// — проверь ссылку.\n')


def load_packs(base):
    # пакеты звёзд берём из settings.json (их меняют в админ-панели), иначе — стандартные
    try:
        url = urllib.parse.urljoin(base, 'settings.json') + f'?t={int(time.time())}'
        with urllib.request.urlopen(url, timeout=15) as r:
            packs = [int(n) for n in json.load(r).get('stars', {}).get('packs', []) if int(n) > 0]
        if packs:
            return packs
    except Exception:
        pass
    return PACKS


def make_invoices(packs):
    links = {}
    for n in packs:
        link = api('createInvoiceLink', {
            'title': f'{n} звёзд на баланс',
            'description': f'Пополнение баланса SDELKA на {n} ⭐',
            'payload': f'topup:{n}',
            'currency': 'XTR',
            'prices': [{'label': f'{n} ⭐', 'amount': n}],
        })
        links[n] = link
    print(f'Оплата звёздами готова: {len(links)} пакетов ({", ".join(map(str, packs))} ⭐).')
    return links


def app_url(base, username, links):
    # мини-апп получает имя бота и ссылки на оплату прямо в адресе кнопки «Играть»
    parts = urllib.parse.urlsplit(base)
    q = dict(urllib.parse.parse_qsl(parts.query))
    q['bot'] = username
    if links:
        q['inv'] = ','.join(f"{n}.{link.split('$', 1)[-1]}" for n, link in links.items())
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q, safe=',.$-_')))


def owner_commands(uid):
    # у владельца в меню есть /admin, у всех остальных его нет
    api('setMyCommands', {'scope': {'type': 'chat', 'chat_id': uid}, 'commands': [
        {'command': 'start', 'description': 'Открыть игры'},
        {'command': 'admin', 'description': 'Админ-панель'},
        {'command': 'stats', 'description': 'Статистика'},
        {'command': 'id', 'description': 'Мой Telegram ID'},
        {'command': 'paysupport', 'description': 'Помощь с оплатой'},
    ]})


def admin_ids():
    ids = list(cfg.get('admins', []))
    try:
        for a in json.loads((SITE / 'settings.json').read_text('utf-8')).get('admins', []):
            if a not in ids:
                ids.append(a)
    except Exception:
        pass
    return ids


def is_owner(who):
    uid = who.get('id')
    admins = cfg.setdefault('admins', [])
    if uid in admin_ids():
        return True
    # по username пускаем только самый первый раз, пока ID владельца ещё не записан
    if not admins and (who.get('username') or '').lower() == OWNER_USERNAME.lower():
        admins.append(uid)   # запоминаем числовой ID — дальше работает, даже если сменишь username
        save_cfg()
        print(f'Владелец @{OWNER_USERNAME} записан по ID {uid}.')
        try:
            owner_commands(uid)
        except Exception:
            pass
        return True
    return False


def setup(url):
    api('setMyCommands', {'commands': [
        {'command': 'start', 'description': 'Открыть игры'},
        {'command': 'id', 'description': 'Мой Telegram ID'},
        {'command': 'paysupport', 'description': 'Помощь с оплатой'},
    ]})
    for uid in cfg.get('admins', []):
        try:
            owner_commands(uid)
        except Exception:
            pass
    if url:
        api('setChatMenuButton', {'menu_button': {'type': 'web_app', 'text': 'Играть', 'web_app': {'url': url}}})
        print('Кнопка «Играть» поставлена в меню бота.')


def log_payment(m):
    sp = m['successful_payment']
    who = m.get('from', {})
    try:
        rows = json.loads(PAYMENTS.read_text('utf-8'))
    except Exception:
        rows = []
    rows.append({
        'user_id': who.get('id'),
        'username': who.get('username'),
        'stars': sp.get('total_amount'),
        'payload': sp.get('invoice_payload'),
        'charge_id': sp.get('telegram_payment_charge_id'),
        'date': m.get('date'),
    })
    PAYMENTS.write_text(json.dumps(rows, ensure_ascii=False, indent=2), 'utf-8')
    return sp.get('total_amount')


# ---------- вывод подарков: заявка из мини-аппа → админу с кнопками ----------
WD_LOCK = threading.Lock()


def wd_load():
    try:
        return json.loads(WITHDRAWALS.read_text('utf-8'))
    except Exception:
        return {}


def wd_save(rows):
    WITHDRAWALS.write_text(json.dumps(rows, ensure_ascii=False, indent=2), 'utf-8')


def check_init(init_data):
    """Проверяет подпись Telegram у данных мини-аппа. Возвращает пользователя или None."""
    try:
        pairs = dict(urllib.parse.parse_qsl(init_data or '', keep_blank_values=True))
        got = pairs.pop('hash', '')
        dcs = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
        secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
        if not got or not hmac.compare_digest(hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest(), got):
            return None
        if time.time() - int(pairs.get('auth_date', 0)) > 86400:
            return None
        return json.loads(pairs.get('user', '{}')) or None
    except Exception:
        return None


STATUS_TEXT = {'pending': '⏳ Ждёт решения', 'done': '✅ Выдано', 'rejected': '❌ Отклонено'}


def wd_text(r):
    who = html.escape(r.get('first_name') or 'Игрок')
    user = f'<a href="tg://user?id={r["user_id"]}">{who}</a>'
    if r.get('username'):
        user += f' (@{html.escape(r["username"])})'
    it = r['item']
    num = f' #{it["num"]}' if it.get('num') else ''
    text = (f'📤 <b>Заявка на вывод #{r["id"]}</b>\n\n'
            f'Игрок: {user}\nID: <code>{r["user_id"]}</code>\n'
            f'Подарок: <b>{html.escape(str(it.get("name", "?")))}{num}</b>\n'
            f'Цена в игре: {it.get("value", "?")} TON\n\n{STATUS_TEXT[r["status"]]}')
    if r.get('by'):
        text += f' — {html.escape(r["by"])}'
    return text


def wd_create(user, item):
    if not isinstance(item, dict) or not item.get('name'):
        return {'ok': False, 'error': 'Нет данных о подарке'}
    admins = admin_ids()
    if not admins:
        return {'ok': False, 'error': 'Админ ещё не подключён — напиши боту /admin'}
    with WD_LOCK:
        rows = wd_load()
        if sum(1 for r in rows.values() if r['user_id'] == user['id'] and r['status'] == 'pending') >= 20:
            return {'ok': False, 'error': 'Слишком много заявок, дождись решения по старым'}
        rid = secrets.token_hex(4)
        r = {'id': rid, 'user_id': user['id'], 'username': user.get('username'), 'first_name': user.get('first_name'),
             'item': {k: item.get(k) for k in ('uid', 'id', 'name', 'num', 'value')},
             'status': 'pending', 't': int(time.time()), 'msgs': []}
        kb = {'inline_keyboard': [[{'text': '✅ Выдать', 'callback_data': f'wd:ok:{rid}'},
                                   {'text': '❌ Отклонить', 'callback_data': f'wd:no:{rid}'}]]}
        for a in admins:
            try:
                m = api('sendMessage', {'chat_id': a, 'text': wd_text(r), 'parse_mode': 'HTML', 'reply_markup': kb})
                r['msgs'].append([m['chat']['id'], m['message_id']])
            except Exception as e:
                print(f'Заявку не получилось отправить админу {a}:', e)
        if not r['msgs']:
            return {'ok': False, 'error': 'Не получилось отправить заявку админу'}
        rows[rid] = r
        wd_save(rows)
    print(f"📤 Заявка на вывод #{rid}: {r['item']['name']} от {user.get('username') or user['id']}")
    return {'ok': True, 'id': rid}


def wd_status(user, ids):
    rows = wd_load()
    out = {}
    for i in (ids or [])[:50]:
        r = rows.get(str(i))
        out[str(i)] = r['status'] if r and r['user_id'] == user['id'] else 'unknown'
    return {'ok': True, 'items': out}


def wd_decide(cq):
    who = cq.get('from', {})
    _, act, rid = (cq.get('data') or '::').split(':', 2)
    if not is_owner(who):
        api('answerCallbackQuery', {'callback_query_id': cq['id'], 'text': 'Нет доступа'})
        return
    with WD_LOCK:
        rows = wd_load()
        r = rows.get(rid)
        if not r:
            api('answerCallbackQuery', {'callback_query_id': cq['id'], 'text': 'Заявка не найдена'})
            return
        if r['status'] != 'pending':
            api('answerCallbackQuery', {'callback_query_id': cq['id'], 'text': 'Уже решено: ' + STATUS_TEXT[r['status']]})
            return
        r['status'] = 'done' if act == 'ok' else 'rejected'
        r['by'] = '@' + who['username'] if who.get('username') else str(who.get('id'))
        wd_save(rows)
    api('answerCallbackQuery', {'callback_query_id': cq['id'], 'text': STATUS_TEXT[r['status']]})
    for chat_id, msg_id in r['msgs']:
        try:
            api('editMessageText', {'chat_id': chat_id, 'message_id': msg_id, 'text': wd_text(r), 'parse_mode': 'HTML'})
        except Exception:
            pass
    name = r['item']['name']
    note = (f'✅ Подарок «{name}» выведен — проверь свой профиль в Telegram.' if r['status'] == 'done'
            else f'❌ Заявка на вывод «{name}» отклонена. Подарок вернулся в инвентарь.')
    try:
        api('sendMessage', {'chat_id': r['user_id'], 'text': note})
    except Exception:
        pass
    print(f"Заявка #{rid}: {STATUS_TEXT[r['status']]} ({r['by']})")


class ApiHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            n = min(int(self.headers.get('Content-Length') or 0), 20000)
            data = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return self.reply(400, {'ok': False, 'error': 'Плохой запрос'})
        user = check_init(data.get('initData'))
        if not user:
            return self.reply(403, {'ok': False, 'error': 'Открой мини-апп через бота заново'})
        path = self.path.split('?')[0].rstrip('/')
        try:
            if path == '/api/withdraw':
                return self.reply(200, wd_create(user, data.get('item')))
            if path == '/api/withdraw/status':
                return self.reply(200, wd_status(user, data.get('ids')))
            if path == '/api/promo':
                return self.reply(200, promo_activate(user, data.get('code')))
            if path == '/api/stat':
                return self.reply(200, stat_save(user, data))
            if path == '/api/admin/stats':
                if not is_owner(user):
                    return self.reply(403, {'ok': False, 'error': 'Нет доступа'})
                return self.reply(200, stats_summary())
            if path == '/api/credits':
                return self.reply(200, credits_for(user))
            if path == '/api/credits/ack':
                return self.reply(200, credits_ack(user, data.get('ids')))
        except Exception as e:
            print('Ошибка API:', e)
            return self.reply(500, {'ok': False, 'error': 'Ошибка сервера'})
        self.reply(404, {'ok': False, 'error': 'Не найдено'})


def start_api():
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', API_PORT), ApiHandler)
    except OSError as e:
        print(f'Сервер заявок на порту {API_PORT} не запустился:', e)
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=gifts_loop, daemon=True).start()
    print(f'Заявки на вывод принимаются (порт {API_PORT}).')


# ---------- приём подарков: Telegram Business → инвентарь игрока ----------
CR_LOCK = threading.Lock()


def jload(path, default):
    try:
        return json.loads(path.read_text('utf-8'))
    except Exception:
        return default


def jsave(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')


def gift_catalog():
    """Каталог подарков из index.html: id Telegram → наш id, название NFT → наш id."""
    try:
        page = (SITE / 'index.html').read_text('utf-8')
    except Exception:
        return {}, {}
    by_tg = {tg: gid for gid, tg in re.findall(r"\['(\w+)',\s*'[^']*',\s*\d+,\s*'(\d+)'", page)}
    by_name = {}
    for gid, name in re.findall(r"\['(\w+)',\s*(?:'([^']*)'|\"[^\"]*\"),\s*[\d.]+\]", page):
        by_name[gid] = gid
        if name:
            by_name[re.sub(r'[^a-z0-9]', '', name.lower())] = gid
    return by_tg, by_name


def biz_connection(bc):
    """Владелец подключил (или отключил) бота в «Telegram для бизнеса»."""
    uid = bc.get('user', {}).get('id')
    if uid not in admin_ids():
        print(f'Подключение Business от чужого аккаунта {uid} — пропускаю')
        return
    rights = bc.get('rights') or {}
    on = bool(bc.get('is_enabled'))
    cfg['biz'] = {'id': bc['id'], 'user_id': uid, 'on': on}
    save_cfg()
    if not on:
        text = '⏸ Бот отключён от твоего аккаунта — подарки больше не зачисляются автоматически.'
    elif not rights.get('can_view_gifts_and_stars'):
        text = ('⚠️ Бот подключён, но без доступа к подаркам.\n\nНастройки → Telegram для бизнеса → Чат-боты → '
                'этот бот → включи «Подарки и звёзды» (просмотр подарков).')
    else:
        text = '✅ Бот подключён к аккаунту. Подарки, которые тебе пришлют, будут сами зачисляться игрокам в мини-апп.'
    print(text)
    try:
        api('sendMessage', {'chat_id': uid, 'text': text})
    except Exception:
        pass


def owner_msg(text):
    for a in admin_ids():
        try:
            api('sendMessage', {'chat_id': a, 'text': text, 'parse_mode': 'HTML'})
        except Exception:
            pass


def gift_credit(g, by_tg, by_name):
    """Что зачислить за подарок: {'gift': id} или {'ton': сумма}; None — не знаем, что это."""
    gift = g.get('gift') or {}
    if g.get('type') == 'unique':
        key = re.sub(r'[^a-z0-9]', '', (gift.get('base_name') or '').lower())
        gid = by_name.get(key)
        return ({'gift': gid, 'num': gift.get('number')} if gid else None), f"{gift.get('base_name', '?')} #{gift.get('number', '?')}"
    gid = by_tg.get(str(gift.get('id', '')))
    stars = gift.get('star_count') or 0
    label = f'подарок за {stars} ⭐'
    if gid:
        return {'gift': gid}, label
    if stars:
        per_ton = 150
        try:
            per_ton = float(json.loads((SITE / 'settings.json').read_text('utf-8'))['stars']['perTon']) or 150
        except Exception:
            pass
        return {'ton': round(stars / per_ton, 4)}, label
    return None, label


def gifts_check():
    biz = cfg.get('biz') or {}
    if not biz.get('on'):
        return
    res = api('getBusinessAccountGifts', {'business_connection_id': biz['id'], 'limit': 100})
    gifts = res.get('gifts', [])
    seen = jload(GIFTS_SEEN, None)
    if seen is None:   # первый запуск: всё, что уже было на аккаунте, не зачисляем
        jsave(GIFTS_SEEN, [g.get('owned_gift_id') for g in gifts])
        print(f'Подарки: запомнил {len(gifts)} уже полученных, слежу за новыми.')
        return
    seen = set(seen)
    new = [g for g in gifts if g.get('owned_gift_id') and g['owned_gift_id'] not in seen]
    if not new:
        return
    by_tg, by_name = gift_catalog()
    for g in reversed(new):   # от старых к новым
        seen.add(g['owned_gift_id'])
        who = g.get('sender_user') or {}
        what, label = gift_credit(g, by_tg, by_name)
        name = html.escape(who.get('first_name') or 'Игрок')
        who_txt = f'<a href="tg://user?id={who["id"]}">{name}</a>' + (f' (@{html.escape(who["username"])})' if who.get('username') else '') if who.get('id') else 'аноним'
        if not who.get('id') or not what:
            reason = 'отправитель скрыт' if not who.get('id') else 'такого подарка нет в каталоге мини-аппа'
            owner_msg(f'⚠️ Пришёл {html.escape(label)} от {who_txt}, но зачислить сам не могу: {reason}. Выдай вручную в админ-панели.')
            continue
        cid = secrets.token_hex(5)
        with CR_LOCK:
            rows = jload(CREDITS, {})
            rows[cid] = {'id': cid, 'user_id': who['id'], **what, 'label': label, 'owned_gift_id': g['owned_gift_id'],
                         't': int(time.time()), 'status': 'new'}
            jsave(CREDITS, rows)
        got = f"{what['ton']} TON на баланс" if 'ton' in what else 'подарок в инвентарь'
        owner_msg(f'🎁 {who_txt} прислал {html.escape(label)} → зачислено: {got}.')
        print(f"🎁 {who.get('username') or who['id']}: {label} → {got}")
        try:
            done = f"{what['ton']} TON уже на балансе" if 'ton' in what else 'подарок уже в инвентаре'
            api('sendMessage', {'chat_id': who['id'], 'text': f'🎁 Подарок получен! Открой мини-апп — {done}.'})
        except Exception:
            pass
    jsave(GIFTS_SEEN, sorted(seen))


def gifts_loop():
    while True:
        try:
            gifts_check()
        except Exception as e:
            print('Проверка подарков:', e)
        time.sleep(GIFT_POLL)


def credits_for(user):
    rows = jload(CREDITS, {})
    items = [{k: r.get(k) for k in ('id', 'gift', 'num', 'ton', 'label')} for r in rows.values()
             if r['user_id'] == user['id'] and r['status'] == 'new']
    return {'ok': True, 'items': items}


def credits_ack(user, ids):
    ids = set(map(str, ids or []))
    with CR_LOCK:
        rows = jload(CREDITS, {})
        for i in ids:
            r = rows.get(i)
            if r and r['user_id'] == user['id'] and r['status'] == 'new':
                r['status'] = 'done'
                r['done_t'] = int(time.time())
        jsave(CREDITS, rows)
    return {'ok': True}


# ---------- статистика ----------
ST_LOCK = threading.Lock()


def num(x, nd=2):
    try:
        x = float(x)
    except Exception:
        return 0.0
    return round(x, nd) if x == x and abs(x) < 1e15 else 0.0


def stat_save(user, d):
    st = d.get('st') or {}
    games = {}
    for k, g in list((st.get('games') or {}).items())[:30]:
        if isinstance(g, dict):
            games[str(k)[:40]] = {'n': int(num(g.get('n'), 0)), 'bet': num(g.get('bet'), 4), 'won': num(g.get('won'), 4)}
    now = int(time.time())
    with ST_LOCK:
        rows = jload(STATS, {})
        old = rows.get(str(user['id'])) or {'first': now}
        old.update({'id': user['id'], 'name': user.get('first_name') or '', 'username': user.get('username') or '',
                    'bal': num(d.get('bal'), 4), 'inv': num(d.get('inv'), 4), 'invN': int(num(d.get('invN'), 0)),
                    'games': games, 'depTon': num(st.get('depTon'), 4), 'depStars': int(num(st.get('depStars'), 0)), 'last': now})
        rows[str(user['id'])] = old
        jsave(STATS, rows)
        hist = [h for h in (d.get('hist') or [])[:30] if isinstance(h, dict)]
        if hist:
            feed = jload(FEED, [])
            have = {(f['id'], f['t']) for f in feed}
            for h in hist:
                t = int(num(h.get('t'), 0))
                if not t or (user['id'], t) in have or t > (now + 60) * 1000:
                    continue
                feed.append({'id': user['id'], 'name': user.get('first_name') or '', 'username': user.get('username') or '',
                             'g': str(h.get('g') or '?')[:40], 'a': num(h.get('a'), 4), 'w': num(h.get('w'), 4), 't': t})
            feed.sort(key=lambda f: f['t'], reverse=True)
            jsave(FEED, feed[:1000])
    return {'ok': True}


def stats_summary():
    rows = list(jload(STATS, {}).values())
    now = time.time()
    games = {}
    for r in rows:
        for k, g in (r.get('games') or {}).items():
            x = games.setdefault(k, {'name': k, 'n': 0, 'bet': 0.0, 'won': 0.0})
            x['n'] += g['n']; x['bet'] += g['bet']; x['won'] += g['won']
    pays = jload(PAYMENTS, [])
    wds = jload(WITHDRAWALS, {}).values()
    per_ton = 150
    try:
        per_ton = float(json.loads((SITE / 'settings.json').read_text('utf-8'))['stars']['perTon']) or 150
    except Exception:
        pass
    for r in rows:
        r['dep'] = r.get('depTon', 0) + r.get('depStars', 0) / per_ton
    top = sorted(rows, key=lambda r: (r['dep'], r.get('bal', 0)), reverse=True)[:10]
    return {
        'ok': True, 't': int(now),
        'players': len(rows),
        'new24': sum(1 for r in rows if now - r.get('first', 0) < 86400),
        'active24': sum(1 for r in rows if now - r.get('last', 0) < 86400),
        'active7': sum(1 for r in rows if now - r.get('last', 0) < 7 * 86400),
        'bal': sum(r.get('bal', 0) for r in rows),
        'invV': sum(r.get('inv', 0) for r in rows),
        'depTon': sum(r.get('depTon', 0) for r in rows),
        'stars': sum(p.get('stars') or 0 for p in pays),
        'giftsIn': len(jload(CREDITS, {})),
        'wdPending': sum(1 for w in wds if w['status'] == 'pending'),
        'wdDone': sum(1 for w in wds if w['status'] == 'done'),
        'games': sorted(games.values(), key=lambda g: g['bet'], reverse=True),
        'top': [{'id': r['id'], 'name': r.get('name'), 'username': r.get('username'), 'dep': r['dep'], 'bal': r.get('bal', 0),
                 'bet': sum(g['bet'] for g in (r.get('games') or {}).values()), 'won': sum(g['won'] for g in (r.get('games') or {}).values())} for r in top],
        'feed': jload(FEED, [])[:300],
        'promoUsed': {k: len(v) for k, v in jload(PROMO_USED, {}).items()},
    }


def stats_text():
    s = stats_summary()
    prof = sum(g['bet'] - g['won'] for g in s['games'])
    lines = [f"📊 <b>Статистика</b>\n",
             f"👥 Игроков: <b>{s['players']}</b> (новых за сутки {s['new24']}, активных {s['active24']}, за 7 дней {s['active7']})",
             f"💎 Пополнено TON: <b>{s['depTon']:.2f}</b>   ⭐ Звёздами: <b>{s['stars']}</b>",
             f"📈 Профит с игр: <b>{prof:.2f} TON</b>",
             f"👛 На балансах: {s['bal']:.2f} TON   🎁 В инвентарях: {s['invV']:.2f} TON",
             f"🎁 Прислали подарков: {s['giftsIn']}   📤 Выводов: ждут {s['wdPending']}, выдано {s['wdDone']}\n"]
    for g in s['games'][:10]:
        lines.append(f"• {html.escape(g['name'])}: {g['n']} игр, ставки {g['bet']:.2f}, профит {g['bet'] - g['won']:.2f}")
    big = [f for f in s['feed'] if f['w'] > f['a']][:10]
    if big:
        lines.append('\n🏆 <b>Последние выигрыши</b>')
        for f in big:
            who = '@' + f['username'] if f['username'] else (f['name'] or str(f['id']))
            lines.append(f"• {html.escape(who)} — {html.escape(f['g'])}: ставка {f['a']:.2f}, выиграл {f['w']:.2f} TON")
    return '\n'.join(lines)


# ---------- промокоды: 1 аккаунт = 1 активация, общий лимит активаций ----------
PR_LOCK = threading.Lock()


def promo_activate(user, code):
    code = str(code or '').strip().upper()
    if not code or len(code) > 64:
        return {'ok': False, 'error': 'Введи промокод'}
    try:
        promos = json.loads((SITE / 'settings.json').read_text('utf-8')).get('promos') or []
    except Exception:
        promos = []
    h = hashlib.sha256(code.encode()).hexdigest()
    pr = next((p for p in promos if p.get('h') == h), None)
    if not pr:
        return {'ok': False, 'error': 'Такого промокода нет'}
    uid = user['id']
    with PR_LOCK:
        used = jload(PROMO_USED, {})
        lst = used.setdefault(pr['id'], [])
        if uid in lst:
            return {'ok': False, 'error': 'Ты уже активировал этот промокод'}
        if len(lst) >= int(pr.get('max') or 0):
            return {'ok': False, 'error': 'Промокод закончился'}
        lst.append(uid)
        jsave(PROMO_USED, used)
    print(f"🎟 Промокод {pr.get('mask')}: {user.get('username') or uid} ({len(lst)}/{pr.get('max')})")
    return {'ok': True, 'left': int(pr.get('max') or 0) - len(lst)}


def send_start(chat_id, name, url):
    if url:
        text = (f'Привет, {name}! 👋\n\nЭто SPANIX Games — игры, PVP и подарки Telegram. '
                f'\n\nЖми «Играть» 👇')
        kb = {'inline_keyboard': [
            [{'text': '🎮 Играть в SPANIX Games', 'web_app': {'url': url}}],
            [{'text': '💬 Поддержка', 'url': SUPPORT}],
        ]}
    else:
        text = 'Мини-апп ещё не подключён: запусти start.bat --url и вставь ссылку на него.'
        kb = None
    api('sendMessage', {'chat_id': chat_id, 'text': text, 'reply_markup': kb})


def poll(url):
    api('deleteWebhook')
    print('Бот работает. Напиши ему /start в Telegram. Остановить — закрой окно или Ctrl+C.\n')
    offset = None
    while True:
        try:
            updates = api('getUpdates', {'timeout': 30, 'offset': offset, 'allowed_updates': ['message', 'pre_checkout_query', 'callback_query', 'business_connection']}, timeout=45)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print('Нет связи с Telegram, пробую снова через 3 с:', e)
            time.sleep(3)
            continue
        for u in updates:
            offset = u['update_id'] + 1
            if u.get('business_connection'):
                try:
                    biz_connection(u['business_connection'])
                except Exception as e:
                    print('Ошибка подключения Business:', e)
                continue
            cq = u.get('callback_query')
            if cq:
                if (cq.get('data') or '').startswith('wd:'):
                    try:
                        wd_decide(cq)
                    except Exception as e:
                        print('Ошибка обработки заявки:', e)
                continue
            q = u.get('pre_checkout_query')
            if q:
                # Telegram ждёт подтверждения перед списанием звёзд (не дольше 10 секунд)
                try:
                    api('answerPreCheckoutQuery', {'pre_checkout_query_id': q['id'], 'ok': True})
                    print(f"Оплата: @{q['from'].get('username') or q['from']['id']} — {q['total_amount']} ⭐")
                except Exception as e:
                    print('Не смог подтвердить оплату:', e)
                continue
            m = u.get('message')
            if not m:
                continue
            who = m.get('from', {})
            if m.get('successful_payment'):
                stars = log_payment(m)
                print(f"✅ Оплачено {stars} ⭐ от @{who.get('username') or who.get('id')} (записано в payments.json)")
                try:
                    api('sendMessage', {'chat_id': m['chat']['id'], 'text': f'✅ Оплата получена: {stars} ⭐. Платёж сохранён. Зачисление в общий игровой баланс требует серверного кошелька; не трать эти средства повторно до включения синхронизации.'})
                except Exception:
                    pass
                continue
            text = m.get('text', '')
            print(f"@{who.get('username') or who.get('id')}: {text}")
            if text.startswith('/id'):
                api('sendMessage', {'chat_id': m['chat']['id'], 'text': f"Твой Telegram ID: {who.get('id')}"})
                continue
            if text.startswith('/admin'):
                if not is_owner(who):
                    print('  ↳ /admin от чужого аккаунта — без ответа')
                    continue
                if url:
                    sep = '&' if '?' in url else '?'
                    api('sendMessage', {'chat_id': m['chat']['id'], 'text': f"⚙️ Админ-панель. Твой ID: {who.get('id')}",
                                        'reply_markup': {'inline_keyboard': [[{'text': '⚙️ Открыть админ-панель', 'web_app': {'url': url + sep + 'admin=1'}}]]}})
                continue
            if text.startswith('/stats'):
                if is_owner(who):
                    api('sendMessage', {'chat_id': m['chat']['id'], 'text': stats_text(), 'parse_mode': 'HTML'})
                continue
            if text.startswith('/paysupport'):
                api('sendMessage', {'chat_id': m['chat']['id'], 'text': f'По вопросам оплаты и возврата звёзд пиши в поддержку: {SUPPORT}'})
                continue
            if text.startswith('/start'):
                try:
                    send_start(m['chat']['id'], who.get('first_name') or 'друг', url)
                except Exception as e:
                    print('Не смог ответить:', e)


def main():
    global TOKEN
    me = None
    if TOKEN:
        try:
            me = api('getMe')
        except Exception as e:
            print('Сохранённый токен не работает:', e)
            TOKEN = None
    if not TOKEN:
        if SERVER:
            print('Нет токена бота. Запусти установщик ещё раз — он спросит токен.')
            sys.exit(1)
        me = ask_token()
    print(f"Бот: @{me['username']}\n")
    if not SERVER:
        patch_site(me['username'])
        if '--gifts' in sys.argv or not (SITE / 'gifts' / 'gifts.json').exists():
            try:
                fetch_gifts()
            except Exception as e:
                print('Картинки подарков не скачались:', e, '\n')
    base = cfg.get('webapp_url', '')
    if SERVER:
        base = base or DEFAULT_URL
        print(f'Мини-апп: {base}')
    elif '--url' in sys.argv or not base:
        base = ask_url()
    else:
        print(f'Мини-апп: {base}  (сменить: start.bat --url)')
    try:
        links = make_invoices(load_packs(base))
    except Exception as e:
        print('Ссылки на оплату звёздами не создались:', e)
        links = {}
    url = app_url(base, me['username'], links) if base else ''
    setup(url)
    start_api()
    poll(url)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nБот остановлен.')
