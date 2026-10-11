#!/usr/bin/env bash
# Установка бота SDELKA на сервер (Ubuntu). Запуск одной командой:
#   curl -fsSL https://raw.githubusercontent.com/ТВОЙ_GITHUB/ИМЯ_РЕПО/main/server/install.sh | bash
# Повторный запуск обновляет бота и не трогает токен.
set -e
DIR=/opt/sdelka
RAW=https://raw.githubusercontent.com/ТВОЙ_GITHUB/ИМЯ_РЕПО/main/server

echo "== SDELKA: ставлю бота на сервер =="
if ! command -v python3 >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y python3
fi
mkdir -p "$DIR" && cd "$DIR"
curl -fsSL "$RAW/bot.py?t=$(date +%s)" -o bot.py

if [ ! -f config.json ] || ! grep -q '"token"' config.json; then
  echo
  echo "Открой @BotFather → /mybots → свой бот → API Token и скопируй токен."
  read -rp "Вставь токен бота и нажми Enter: " TOKEN </dev/tty
  python3 - "$TOKEN" <<'PY'
import json, sys
json.dump({"token": sys.argv[1].strip(), "webapp_url": "https://ТВОЙ_GITHUB.github.io/ИМЯ_РЕПО/"}, open("config.json", "w"), indent=2)
PY
  chmod 600 config.json
fi

cat > /etc/systemd/system/sdelka-bot.service <<'UNIT'
[Unit]
Description=SDELKA Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/sdelka
ExecStart=/usr/bin/python3 -u /opt/sdelka/bot.py --server
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable sdelka-bot >/dev/null 2>&1
systemctl restart sdelka-bot
sleep 6
echo
journalctl -u sdelka-bot -n 12 --no-pager -o cat || true
echo
if systemctl is-active --quiet sdelka-bot; then
  echo "✅ Бот работает на сервере и сам перезапустится после перезагрузки."
  echo "   Закрой окно start.bat на компьютере — два бота с одним токеном мешают друг другу."
else
  echo "❌ Бот не запустился. Пришли текст выше."
fi
echo "Логи: journalctl -u sdelka-bot -f    Обновить бота: запусти эту же команду ещё раз."
