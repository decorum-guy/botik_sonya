# Перенос Botik Sonya на сервер

Этот документ описывает перенос уже настроенного бота с Mac на Linux-сервер без потери ROADMAP, медиа, привязки участницы и сохранённых воспоминаний.

## Что обязательно перенести

Код можно получить через Git, но приватные данные в публичный репозиторий не попадают. На сервер должны попасть отдельно:

- `.env` — токен, прокси и настройки;
- `roadmap/quest.json` — финальная версия сценария, если она ещё не закоммичена;
- `media/` — все фотографии, видео, аудио и документы;
- `data/` — SQLite-база с админом, участницей, прогрессом и воспоминаниями;
- `.cache/telegram_media/` — необязательно, но позволяет не пережимать крупные видео повторно.

Не переносится:

- `.venv/` — виртуальное окружение всегда создаётся заново;
- `__pycache__/`;
- локальные временные файлы редакторов.

## Важное правило перед переносом

Один токен Telegram-бота нельзя одновременно использовать в двух запущенных процессах polling.

Перед запуском сервера останови бот и Roadmap Studio на Mac через `Ctrl+C`. После запуска на сервере не запускай локальную копию с тем же токеном.

## Что происходит с воспоминаниями

В текущей архитектуре база не хранит содержимое сообщений. Для каждого фрагмента она хранит:

- `source_chat_id`;
- `source_message_id`;
- порядок сообщения;
- тип контента.

Во время квеста бот повторно вызывает Telegram `forwardMessage` по этим идентификаторам.

Следствия:

1. **Перенос на сервер не требует заново наполнять воспоминания**, если перенесён весь каталог `data/`, используется тот же `BOT_TOKEN`, а исходные сообщения в админском чате не удалены.
2. **Удалять сообщения, которыми наполнялись воспоминания, нельзя.** После удаления Telegram может сделать исходный `message_id` недоступным, и бот не сможет его переслать.
3. Очистить локальный кэш Telegram на телефоне или Mac можно: это не удаляет облачные сообщения.
4. Архивировать или замьютить чат можно.
5. Нельзя выбирать «Удалить чат», «Очистить историю» или вручную удалять сохранённые пересланные сообщения до окончания квеста.
6. Новый бот с другим токеном не является безопасной заменой: ссылки в базе создавались в чате со старым ботом.

Перед настоящим квестом обязательно проверь каждое воспоминание командой:

```text
/memory_preview <memory_id>
```

## 1. Подготовка Mac

Перейди в окончательную локальную папку проекта:

```bash
cd ~/Projects/botik_sonya
source .venv/bin/activate
```

Обнови код и проверь проект:

```bash
git pull
python -m tools.validate_roadmap roadmap/quest.json
python -m pytest -q
```

Заранее подготовь крупные видео:

```bash
python -m tools.prepare_media
```

Останови все процессы бота и конструктора. После этого создай контрольную копию базы:

```bash
mkdir -p ~/Desktop/botik_sonya_backup
cp -a .env roadmap media data .cache ~/Desktop/botik_sonya_backup/
```

Если `.cache` ещё не существует, убери его из команды.

Проверь размеры:

```bash
du -sh media data .cache/telegram_media 2>/dev/null
```

## 2. Подготовка Linux-сервера

Ниже предполагается Ubuntu или Debian и обычный пользователь `ubuntu`. Замени имя пользователя и путь под свой сервер.

Установи зависимости:

```bash
sudo apt update
sudo apt install -y git ffmpeg python3 python3-venv rsync
```

Проверь версии:

```bash
python3 --version
ffmpeg -version | head -1
ffprobe -version | head -1
```

Проект требует Python 3.12 или новее.

Клонируй код:

```bash
cd ~
git clone https://github.com/decorum-guy/botik_sonya.git
cd ~/botik_sonya
```

Создай окружение:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 3. Передача примерно 1 ГБ медиа

Для больших медиа лучше использовать `rsync`: он показывает прогресс и умеет продолжать оборванную передачу.

На Mac:

```bash
cd ~/Projects/botik_sonya

rsync -a --info=progress2 --partial --append-verify \
  media/ ubuntu@SERVER_IP:/home/ubuntu/botik_sonya/media/
```

Видео и фотографии уже сжаты, поэтому флаг `-z` обычно только тратит процессор и почти не уменьшает трафик.

Передай базу, настройки и ROADMAP:

```bash
rsync -a --info=progress2 \
  .env roadmap/ data/ \
  ubuntu@SERVER_IP:/home/ubuntu/botik_sonya/
```

Опционально передай подготовленный видеокэш:

```bash
rsync -a --info=progress2 --partial --append-verify \
  .cache/telegram_media/ \
  ubuntu@SERVER_IP:/home/ubuntu/botik_sonya/.cache/telegram_media/
```

Кэш новых версий привязан к содержимому файла, а не к абсолютному пути, поэтому может переехать с Mac на сервер. Если кэш не переносить, сервер подготовит крупные видео заново.

## 4. Проверка файлов на сервере

На сервере:

```bash
cd ~/botik_sonya
chmod 600 .env

ls -la .env
ls -lh data/bot.db
find media -type f | wc -l
du -sh media
```

Проверь крупные файлы:

```bash
find media -type f -size +40M -exec ls -lh {} \;
```

Проверь проект:

```bash
source .venv/bin/activate
python -m tools.validate_roadmap roadmap/quest.json
python -m tools.prepare_media --dry-run
python -m pytest -q
```

Если часть крупных видео ещё не подготовлена:

```bash
python -m tools.prepare_media
```

## 5. Первый ручной запуск

На сервере:

```bash
cd ~/botik_sonya
source .venv/bin/activate
python -m app.main
```

В Telegram с админского аккаунта:

```text
/ping
/status
/memory_list
/memory_preview <memory_id>
```

Проверь также один блок с фото и один блок с видео.

После успешной проверки останови процесс через `Ctrl+C` и настрой systemd.

## 6. Постоянный запуск через systemd

Узнай своего пользователя и путь:

```bash
whoami
pwd
```

Создай сервис:

```bash
sudo nano /etc/systemd/system/botik-sonya.service
```

Пример для пользователя `ubuntu` и пути `/home/ubuntu/botik_sonya`:

```ini
[Unit]
Description=Botik Sonya Telegram Quest Bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/botik_sonya
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/ubuntu/botik_sonya/.venv/bin/python -m app.main
Restart=always
RestartSec=5
TimeoutStopSec=30
KillSignal=SIGINT

[Install]
WantedBy=multi-user.target
```

Активируй:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now botik-sonya
sudo systemctl status botik-sonya
```

Логи:

```bash
journalctl -u botik-sonya -f
```

Перезапуск после обновления:

```bash
cd ~/botik_sonya
git pull
source .venv/bin/activate
python -m pip install -r requirements.txt
sudo systemctl restart botik-sonya
```

## 7. Проверка прокси и исправности

Команда администратора:

```text
/ping
```

Она проверяет:

- получение команды через polling;
- запрос к Telegram API через текущую прокси-сессию;
- доступ к SQLite;
- загрузку ROADMAP;
- привязку участницы.

После перезагрузки сервера убедись, что сервис поднялся:

```bash
sudo systemctl is-active botik-sonya
```

И снова отправь `/ping`.

## 8. Резервное копирование

Самые важные приватные данные:

```text
.env
data/
roadmap/quest.json
media/
```

Минимальная ручная резервная копия на сервере:

```bash
sudo systemctl stop botik-sonya
cd ~/botik_sonya
tar -czf ~/botik-sonya-backup-$(date +%F-%H%M).tar.gz \
  .env data roadmap media
sudo systemctl start botik-sonya
```

Не публикуй этот архив: в нём находятся токен, личная переписка в виде ссылок на сообщения и приватные медиа.

## 9. Возврат с сервера на Mac

Не запускай обе копии одновременно.

1. Останови сервер:

```bash
sudo systemctl stop botik-sonya
```

2. Скопируй актуальный каталог `data/` обратно на Mac, потому что там может находиться новый прогресс квеста.
3. Только после этого запускай локальную копию.

Пример на Mac:

```bash
rsync -a ubuntu@SERVER_IP:/home/ubuntu/botik_sonya/data/ \
  ~/Projects/botik_sonya/data/
```

## Финальный чек-лист

- [ ] Локальный бот остановлен.
- [ ] На сервере используется тот же `BOT_TOKEN`.
- [ ] `.env` перенесён и имеет права `600`.
- [ ] `data/bot.db` перенесён.
- [ ] Все исходные сообщения воспоминаний остались в админском чате.
- [ ] `media/` перенесена полностью.
- [ ] `python -m tools.prepare_media` выполнен.
- [ ] `/ping` показывает успешный Telegram API и прокси.
- [ ] Все `/memory_preview <id>` успешно проигрываются.
- [ ] Проверены фото, вертикальное видео и медиагруппа.
- [ ] systemd-сервис включён и переживает перезагрузку сервера.
