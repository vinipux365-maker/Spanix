МИНИ-АПП С ИГРАМИ ДЛЯ TELEGRAM — УСТАНОВКА
==========================================

Что внутри
----------
index.html               — мини-апп: кейсы, Ракетка, PVP, Mines, Plinko, Dice, Улучшение, Крафт,
                           инвентарь, рейтинг, награды, рефералы, админ-панель со статистикой
deposit.html             — отдельная страница пополнения через TON Connect
tonconnect-manifest.json — манифест TON Connect (на сервере создаётся сам)
settings.json            — настройки (меняются из админ-панели)
server/bot.py            — бот: кнопка «Играть», оплата звёздами, заявки на вывод,
                           автозачисление присланных подарков (Telegram Business), /stats
server/install.sh        — установка бота на сервер Ubuntu
server/site.sh           — установка мини-аппа на сервер с HTTPS (Caddy)
scripts/, .github/       — автообновление цен подарков с Fragment (GitHub Actions)


1. Впиши свои данные
--------------------
Замени заглушки на свои:

index.html (блок CONFIG в начале скрипта):
  botUsername  — username бота без @
  giftAccount  — аккаунт, куда игроки отправляют подарки
  repo         — твой репозиторий на GitHub (ТВОЙ_GITHUB/ИМЯ_РЕПО)
  owner        — твой username без @ (он всегда админ)
  tonWallet    — твой TON-кошелёк для пополнений

deposit.html:  OWNER_WALLET и MINI_APP_LINK
server/bot.py: SUPPORT, DEFAULT_URL, OWNER_USERNAME
server/install.sh и server/site.sh: ТВОЙ_GITHUB/ИМЯ_РЕПО
settings.json: app.giftAccount и owner

Быстро найти всё: поиск по словам «ВСТАВЬ», «ТВОЙ», «твой_», «ИМЯ_».


2. Залей на GitHub
------------------
Создай репозиторий и загрузи туда все файлы.


3. Сервер (Ubuntu)
------------------
Бот:
  curl -fsSL https://raw.githubusercontent.com/ТВОЙ_GITHUB/ИМЯ_РЕПО/main/server/install.sh | bash
  (спросит токен бота из @BotFather)

Мини-апп с HTTPS:
  curl -fsSL https://raw.githubusercontent.com/ТВОЙ_GITHUB/ИМЯ_РЕПО/main/server/site.sh | bash
  В конце покажет ссылку на мини-апп и страницу пополнения.

Если репозиторий закрытый: скрипт покажет строку ssh-ed25519 — добавь её на GitHub в
Settings → Deploy keys (без права записи) и запусти команду ещё раз.


4. Первый запуск
----------------
- Напиши боту /admin со своего аккаунта — он запомнит тебя владельцем.
- Админ-панель: кнопка «Админ» в мини-аппе. Для сохранения настроек нужен ключ GitHub
  (Fine-grained token → только свой репозиторий → Contents: Read and write).
- Автозачисление подарков: нужен Telegram Premium. Настройки → Telegram для бизнеса →
  Чат-боты → свой бот → включи доступ к подаркам и звёздам.


Обновить бота после изменений
-----------------------------
  cp /opt/sdelka/site/server/bot.py /opt/sdelka/bot.py && systemctl restart sdelka-bot


SPANIX Games — integration notes (2026-10)
=========================================
- Branding: SPANIX Games.
- Bot menu has 3 buttons in each of the first three rows and a full-width game button in row four; Support is in row three.
- The main bot already has admin settings for the game button's text, Telegram Premium Emoji ID and button style/color.
- Mini App admin access includes the Telegram ID 8759868224 found in the supplied bot source, plus configured username/admin list.
- Exchange display rate is 100 Stars = 1 TON.
- Mini App top-ups (Stars, TON and demo credits) are disabled in the interface; users are directed to the main bot.
- New browser profiles start with 0 balance.

IMPORTANT PRODUCTION LIMITATION:
The existing game engine still performs gameplay balance changes in browser localStorage. This package does not yet implement a single authoritative transactional ledger shared with the bot, verified blockchain deposit settlement, or a full Stars/TON withdrawal workflow with atomic reservation and admin payout completion. Disabling Mini App top-ups prevents false client-side deposit claims, but it does not create server-side balance synchronization. Do not accept real-money game deposits or pay withdrawals until that backend is implemented and tested. Set the actual HTTPS MINI_APP_URL, BOT_TOKEN, OWNER_USERNAME, repository, wallet and support settings before deployment. Never commit bot/GitHub tokens.
