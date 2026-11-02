# deploy/ — выкатка Quack на сервер

Это инструкция владельцу (ТЗ Фазы 4 WP9, Д-§13 P0). Скрипты сдаются готовыми; шаги с оплатой, DNS и
секретами делает владелец.

## Что здесь

| Файл | Назначение |
| :-- | :-- |
| `Caddyfile` | TLS, редирект 80 → 443, прокси на `api`. Наружу только `/healthz`, `/auth/*`, `/v1/*`; остальное, в том числе `/health/*` и `/internal/*`, отвечает 404 (Д-§3.1, Д-§9.1) |
| `env.example` | Имена переменных `.env` без значений |
| `setup-server.sh` | Первичная настройка чистого Ubuntu 24.04 (Д-§10) |
| `deploy.sh <sha>` | Выкатка и откат по Д-§6.1 и Д-§6.3 |

## Порядок первого запуска

1. **Сервер.** Contabo Cloud VPS 6, Ubuntu 24.04, EU. Перед оплатой сверить тариф (Д-§14.2).
2. **Файрвол в панели провайдера:** входящие 22, 80, 443. Скрипт настраивает ещё и `ufw`.
3. **DNS в Cloudflare** (серое облако): `api` A на IPv4 сервера, TTL 300. AAAA для `api` не ставить (Д-§3.1). Остальные записи — по таблице Д-§3.1.
4. **Настройка сервера** под root:
   ```bash
   ADMIN_SSH_PUBKEY='ssh-ed25519 …' DEPLOY_SSH_PUBKEY='ssh-ed25519 …' bash setup-server.sh
   ```
   До закрытия сессии проверить из другого терминала `ssh admin@<сервер>`: вход под root и по паролю отключён.
5. **GitHub Environment `production`:** секреты `DEPLOY_HOST`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` (`ssh-keyscan -t ed25519 <сервер>`) и секреты из `env.example`. Job выкатки — отдельный пакет (WP9.3/9.4), он рендерит `/srv/quack/.env` с правами 600.
6. **Файлы на сервере.** В `/srv/quack` должны лежать `compose.yaml`, `deploy/` и `.env`.
7. **Образы** с тегом `<sha>` в GHCR; пакеты публичные, `docker pull` проверить без входа (Д-§5.1).
8. **Первая выкатка** (баз ещё нет, дампить нечего):
   ```bash
   ALLOW_NO_DUMP=1 ./deploy/deploy.sh <sha>
   ```
   Дальше `ALLOW_NO_DUMP` не нужен: перед миграцией скрипт делает дамп (`ops backup now`).

Журнал выкаток — `/srv/quack/deploy.log`, текущий релиз — `/srv/quack/release.env`.

## Бэкап

`ops backup` (сервис `backup`, профиль `backup`: `docker compose up` его не стартует). Таймер `quack-backup.timer` ставит `setup-server.sh`, раз в 6 часов. Поток: `pg_dump -Fc --compress=zstd` → `age` (публичный ключ `BACKUP_AGE_PUBLIC_KEY`) → бакет `quack-backups/dumps/`; две последние копии без шифрования лежат в `/srv/quack/backups` (700/600). После успеха — пинг `HEARTBEAT_BACKUP_URL`, после неудачи — вебхук `ALERT_WEBHOOK_URL`. Приватный ключ `age` на сервере не хранится. Дамп читает базу ролью `quack_reader`: её создаёт `ops db-roles`, `deploy.sh` запускает его перед дампом и миграцией.

Пробная проверка без R2: `BACKUP_S3_ENDPOINT=file:///путь` пишет в каталог.

## Откат

`./deploy/deploy.sh <предыдущий sha>`. Скрипт видит, что этот SHA уже выкатывался, пропускает дамп и миграции и спрашивает `ops can-rollback`. Откат запрещён, если в журнале появились новые типы событий или сменилась `rules@N` (Д-§6.3): тогда только исправление вперёд. После ручного отката со сменой правил: `ops rebuild --stale-rules`.

Проверка после выкатки не прошла — автоматический откат делается только для релиза без новых событий, без смены `rules@N` и без новых миграций.

## Что пока не готово

- **Тревоги** (`ops alerts`) и таймер systemd для `alerts` (WP9.5).
- **Перевод `api`, `workers`, `projector` и `migrate` на роли `quack_app` и `quack_migrator`**: ждёт перехода слоя данных на dbmate (поток A), пока они работают под `quack`.
- **Команды восстановления** `restore-check`, `replay-deletions`, `orphan-objects` (WP9.6); сценарии — Д-§8.3.
- **Job выкатки** в GitHub Actions и публикация образов в GHCR: WP9.3/9.4.
- **CORS** API (`cors_origins` уже есть в конфиге, подключение к приложению — отдельный пакет).

## Локальная проверка

Caddyfile:

```bash
docker run --rm -v "$PWD/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.10 \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

Весь стек с локальным сертификатом: в `.env` `API_DOMAIN=localhost`, затем `docker compose up`; `https://localhost/healthz` отвечает 200, `https://localhost/health/ready` — 404.
