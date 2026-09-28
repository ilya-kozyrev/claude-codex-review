# codex-review

**Codex CLI как отсоединённый ревьюер кода для Claude Code.**

*English: a Claude Code plugin that runs OpenAI Codex CLI detached from the Claude session, for code
review and narrow implementation tasks. It checks your Codex limits before it starts, streams events
line by line to a watcher, and supports follow-up review rounds on the author's fixes.*

Claude пишет код, а ревьюер из другой модели находит то, что Claude-ревьюер пропускает. Codex CLI
запускается отдельным процессом, Claude тем временем работает дальше, следит за потоком событий и
забирает результат из `final.md`. Ревью тратит лимиты подписки OpenAI, а не Claude.

У нас этот скилл провёл больше 250 прогонов ревью за три недели. Пример: на одном MR Codex нашёл high — путь,
в обход проверки прав меняющий данные других подразделений. Два независимых ревью Claude по тому же
брифу этот дефект не нашли.

## Установка

Как плагин, из этого репозитория как маркетплейса:

```bash
claude plugin marketplace add ilya-kozyrev/claude-codex-review
claude plugin install codex-review@codex-review
```

Внутри сессии то же делают `/plugin marketplace add ilya-kozyrev/claude-codex-review` и
`/plugin install codex-review@codex-review`. Скилл вызывается как `/codex-review:codex-review`, или
можно просто попросить «отдай ревью Codex'у».

Вручную, как обычный скилл:

```bash
git clone https://github.com/ilya-kozyrev/claude-codex-review
mkdir -p ~/.claude/skills
cp -R claude-codex-review/plugins/codex-review/skills/codex-review ~/.claude/skills/
```

Что нужно:
- [Codex CLI](https://github.com/openai/codex): `npm i -g @openai/codex` или `brew install codex`,
  вход через `codex login`. Проверено на версиях 0.153–0.155.
- `python3`, `git`, `bash`.

## Первый запуск: Codex должен знать то, что знает Claude

Голый Codex ничего не знает о проекте: он либо ревьюит вслепую, либо тратит лимиты на чтение
документации. `codex-init.py` подключает к Codex настройки Claude симлинками, без копирования:

- глобальные правила — `~/.codex/AGENTS.md` ссылается на `~/.claude/CLAUDE.md`;
- `CLAUDE.md` каждого репо — через `project_doc_fallback_filenames` в `~/.codex/config.toml`;
- лимит `project_doc_max_bytes` поднимается так, чтобы правила влезли. По умолчанию он 32 КБ, и
  более длинные правила Codex молча обрезает. У нас глобальные и проектные правила вместе — 57 КБ;
- память проектов Claude (`~/.claude/projects`) — через ссылку и `developer_instructions`;
- скиллы Claude, свои и из включённых плагинов, — ссылками в `~/.agents/skills`;
- скиллы проекта — `<repo>/.agents/skills` ссылается на `.claude/skills`, ссылка скрыта через
  `.git/info/exclude`.

```bash
python3 ~/.claude/skills/codex-review/scripts/codex-init.py --repo ~/code/myrepo
```

Команда делает бэкап `config.toml` и не трогает ничего чужого: свой `AGENTS.md`, свои папки
скиллов, уже заданные ключи. Повторяй её после установки или обновления плагинов Claude, чтобы
ссылки на скиллы не протухали. `codex-run.sh` зовёт её перед каждым запуском как предусловие:
часть на уровне репо ставит сам, а если глобальная не настроена, отказывает и печатает точную
команду. `--check` только показывает, чего не хватает.

## Использование

```bash
S=~/.claude/skills/codex-review/scripts        # у плагина путь внутри ~/.claude/plugins/cache/…
$S/codex-run.sh -C ~/code/myrepo -b review.md -m gpt-6-sol -e high -s read-only -n mr42
python3 $S/codex-watch.py ~/.codex/runs/mr42-<время>   # построчный поток; в Claude Code — под Monitor
cat ~/.codex/runs/mr42-<время>/final.md

# второй раунд, после правок автора: только дифф правок плюс прежние находки
$S/codex-run.sh -C ~/code/myrepo -b review.md -m gpt-6-sol -e high -s read-only -n mr42 --delta <sha-до-правок>

python3 $S/codex-limits.py                      # сколько осталось в 5-часовом и недельном окне
```

Бриф пишется по образцу
[`examples/review-brief.md`](plugins/codex-review/skills/codex-review/examples/review-brief.md): узкий
дифф по sha, что именно проверить, формат находок и строка вердикта.

## Что умеет скрипт

- **Проверяет лимиты до старта.** Если в 5-часовом окне Codex осталось меньше 5 % для ревью
  (`-s read-only`) или меньше 30 % для исполнения, либо в недельном меньше 5 %, скрипт отказывает с
  кодом 3. Так прогон не обрывается на середине. Порог меняется через `CODEX_MIN_LEFT`.
- **Не больше двух живых прогонов одновременно** (`CODEX_MAX_RUNS`).
- **Не запускает effort xhigh/max.** У нас xhigh однажды съел всё 5-часовое окно и не выдал
  `final.md`. Перебить можно через `CODEX_ALLOW_XHIGH=1`.
- **`--delta <sha>`**: второй раунд смотрит только дифф правок и получает прежние находки из
  `final.md` прошлого прогона с тем же `-n`.
- **`--dry-run`**: все проверки и итоговый бриф без запуска Codex.
- **Файлы прогона** в `~/.codex/runs/<имя>-<время>/`: `brief.md`, `events.jsonl`, `final.md`,
  `stderr.log`, `pid`, `meta`.

## Грабли `codex exec`, которые скрипт уже обходит

- У `codex exec` нет `--full-auto`. Effort задаётся через `-c model_reasoning_effort="…"`.
- Без `</dev/null` exec молча висит: он ждёт stdin.
- Без `--json` в stdout приходит только финальный ответ, а ход работы уходит в stderr.
- Sandbox `workspace-write` не может коммитить и ходить в сеть: коммит делает вызывающий.

## Когда у Codex кончились лимиты

Запасной вариант — ревью Claude. До 5 ноября 2026 его можно бесплатно сделать в облачной сессии за
облачный кредит: [claude-cloud-review](https://github.com/ilya-kozyrev/claude-cloud-review).

## Лицензия

MIT
