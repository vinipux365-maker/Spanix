#!/usr/bin/env bash
# Мини-апп SDELKA на своём сервере (HTTPS через Caddy). Запуск одной командой:
#   curl -fsSL https://raw.githubusercontent.com/ТВОЙ_GITHUB/ИМЯ_РЕПО/main/server/site.sh | bash
# Повторный запуск безопасен. Если репозиторий стал приватным — спросит ключ GitHub (только чтение).
set -e
REPO=ТВОЙ_GITHUB/ИМЯ_РЕПО
DIR=/opt/sdelka
SITE=$DIR/site
KEYFILE=$DIR/github_key

IP=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | grep -vE '^(10|127|192\.168|172\.(1[6-9]|2[0-9]|3[01]))\.' | head -n1)
[ -n "$IP" ] || IP=$(curl -fsS4 https://api.ipify.org)
HOST="$(echo "$IP" | tr . -).sslip.io"
echo "== SDELKA: ставлю мини-апп на сервер → https://$HOST/ =="

export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y git caddy >/dev/null
mkdir -p "$DIR"

# --- ключ сервера для закрытого репозитория (открытая часть — не секрет) ---
[ -s $DIR/deploy_key ] || ssh-keygen -q -t ed25519 -N "" -C "sdelka-server" -f $DIR/deploy_key

# --- синхронизация с GitHub: сначала ключ сервера, потом ключ GitHub, потом без ключа ---
cat > $DIR/sync.sh <<'SYNC'
#!/usr/bin/env bash
DIR=/opt/sdelka; SITE=$DIR/site; REPO=ТВОЙ_GITHUB/ИМЯ_РЕПО
run() {
  local url=$1; shift
  if [ -d "$SITE/.git" ]; then git "$@" -C "$SITE" pull -q --ff-only "$url" main
  else rm -rf "$SITE" && git "$@" clone -q --depth 1 "$url" "$SITE"; fi
}
export GIT_TERMINAL_PROMPT=0
if [ -s $DIR/deploy_key ]; then
  GIT_SSH_COMMAND="ssh -i $DIR/deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes" \
    run "git@github.com:$REPO.git" 2>/dev/null && exit 0
fi
if [ -s $DIR/github_key ]; then
  B64=$(printf 'x-access-token:%s' "$(cat $DIR/github_key)" | base64 -w0)
  run "https://github.com/$REPO.git" -c "http.extraHeader=Authorization: Basic $B64" && exit 0
fi
run "https://github.com/$REPO.git"
SYNC
chmod 700 $DIR/sync.sh

if ! $DIR/sync.sh 2>/dev/null; then
  echo
  echo "Репозиторий закрыт, а ключ сервера ещё не добавлен на GitHub."
  echo "Скопируй строку ниже (начинается с ssh-ed25519) и отправь её Claude:"
  echo
  cat $DIR/deploy_key.pub
  echo
  exit 1
fi
echo "✓ Файлы мини-аппа скачаны"

cat > /etc/systemd/system/sdelka-sync.service <<'UNIT'
[Unit]
Description=SDELKA: подтянуть мини-апп, настройки и цены с GitHub
[Service]
Type=oneshot
Environment=GIT_TERMINAL_PROMPT=0
ExecStart=/opt/sdelka/sync.sh
UNIT
cat > /etc/systemd/system/sdelka-sync.timer <<'UNIT'
[Unit]
Description=SDELKA: синхронизация раз в минуту
[Timer]
OnBootSec=30
OnUnitActiveSec=60
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now sdelka-sync.timer >/dev/null 2>&1

# --- манифест TON Connect с адресом этого сервера (его читают кошельки при оплате в deposit.html) ---
mkdir -p $DIR/public
cat > $DIR/public/tonconnect-manifest.json <<JSON
{
  "url": "https://$HOST",
  "name": "SDELKA",
  "iconUrl": "https://$HOST/icon.png"
}
JSON
chmod 644 $DIR/public/tonconnect-manifest.json

# --- веб-сервер с автоматическим HTTPS ---
cat > /etc/caddy/Caddyfile <<CADDY
$HOST {
	root * $SITE
	encode gzip
	@private path /.git* /server/* /scripts/* /.github/* /.gitignore /.nojekyll
	respond @private 404
	@live path /settings.json /prices.json
	header @live Cache-Control "no-store"
	handle /api/* {
		reverse_proxy 127.0.0.1:8787
	}
	handle /tonconnect-manifest.json {
		root * $DIR/public
		header Access-Control-Allow-Origin "*"
		header Cache-Control "no-store"
		file_server
	}
	file_server
}
CADDY
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then ufw allow 80,443/tcp >/dev/null; fi
systemctl restart caddy

# --- бот: новая ссылка на мини-апп ---
if [ -f $DIR/config.json ]; then
  python3 - "https://$HOST/" <<'PY'
import json, sys
p = '/opt/sdelka/config.json'; c = json.load(open(p)); c['webapp_url'] = sys.argv[1]
json.dump(c, open(p, 'w'), indent=2)
PY
  systemctl restart sdelka-bot 2>/dev/null || true
  echo "✓ Бот переключён на новую ссылку"
fi

echo "Жду сертификат HTTPS…"
ok=0
for i in $(seq 1 20); do
  if curl -fsS -o /dev/null "https://$HOST/"; then ok=1; break; fi
  sleep 3
done
echo
if [ $ok = 1 ]; then
  echo "✅ Мини-апп работает: https://$HOST/"
  echo "   Бот уже открывает его по кнопке «Играть». Настройки и цены подтягиваются с GitHub раз в минуту."
  echo "   Пополнение через TON: https://$HOST/deposit.html"
  echo
  echo "Чтобы закрыть репозиторий на GitHub, отправь Claude эту строку (это открытая часть ключа, её можно пересылать):"
  echo
  cat $DIR/deploy_key.pub
else
  echo "⚠️ Сайт пока не открывается по HTTPS. Проверь в панели хостинга (Firewall), что открыты порты 80 и 443,"
  echo "   и запусти эту команду ещё раз. Подробности: journalctl -u caddy -n 30 --no-pager"
fi
