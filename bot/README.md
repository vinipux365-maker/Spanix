# SPANIX bot

Runs on Railway (service `spanix-bot`) from the root `Dockerfile`.
Secrets live in Railway variables: `BOT_TOKEN`, `MINI_APP_URL`, `DB_PATH=/data/bot.db`, `SESSION_SECRET`.
SQLite database is on the persistent volume mounted at `/data`.
