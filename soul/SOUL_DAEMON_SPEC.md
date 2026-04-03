# Soul Daemon Spec v1
> Цифровая нервная система Клина. Второй ум. Не спам — сигнал когда момент подходящий.
> Принцип: лучше пропустить 3 слабых, чем прислать 1 лишний шумный.

---

## 1. Архитектура

```
[Cron каждые 60 мин]
       ↓
[soul_collect.py] — БЕЗ LLM
  ├── читает ved/state.json → open_threads, urgency
  ├── wttr.in Москва + Волжский → погода
  ├── PocketBase API radar.looi.ru → новые регистрации/просмотры за сутки
  ├── Telegram bot history → Лера + сын (последнее сообщение + timestamp)
  ├── CronBun stats → подписчики (delta за 24ч)
  └── Результат → soul/signals_latest.json

[soul_decide.py] — БЕЗ LLM
  ├── Читает signals_latest.json
  ├── Сравнивает с soul/signals_prev.json (delta)
  ├── Применяет правила тишины (время, уже отправлено, слабый сигнал)
  ├── Если порог не пройден → выход (ничего не делать)
  └── Если порог пройден → передать данные LLM агенту

[g-flash агент] — ТОЛЬКО если есть сигнал
  ├── Получает: signals_latest.json + контекст open_threads
  ├── Формирует: интерпретированная сводка (что + признаки + на что обратить)
  └── Отправляет в Telegram topic:40 (личное) или topic:39 (система)
```

**Ключевой принцип:** LLM запускается только когда данные уже отфильтрованы. Сбор и решение — чистый Python.

---

## 2. Источники v1 (стабильные, реализуемые сейчас)

| Источник | Метод | Что берём |
|---|---|---|
| `ved/state.json` | `json.load()` | open_threads с urgency=action_needed |
| Погода | `wttr.in/:city?format=j1` | temp, description, Москва + Волжский |
| radar.looi.ru | PocketBase REST API (64.188.74.59:8090) | новые записи/регистрации за 24ч |
| CronBun @cronbun | Telegram Bot API | delta подписчиков (если доступно) |
| Лера + сын | Telegram Bot API sessions history | timestamp последнего сообщения |

**[Скептик]:** PocketBase API — нет auth token, надо добавить. Telegram sessions history — не факт что доступен напрямую, нужно проверить endpoint. Лучше начать с wttr.in + ved + radar как самых надёжных.

---

## 3. Источники v2 (после стабилизации v1)

- YouTube канал Ильи Воробьёва — RSS фид новых видео
- Telegram канал Ильи — парсинг через Bot API или MTProto
- LinkedIn комменты/реакции на статьи Артура — web_fetch + парсинг
- Упоминания "Art Looi" / "Артур Арсенов" — Serper/Tavily поиск 1 раз в день
- Facebook — сложно без API, пока пропустить

---

## 4. Правила тишины (когда НЕ писать)

```python
SILENCE_RULES = [
    # Время
    lambda: 10 <= now_msk.hour < 16,  # рабочий блок
    lambda: 0 <= now_msk.hour < 8,    # ночь (не критично)

    # Уже отправляли сегодня на эту тему
    lambda signal: signal["key"] in sent_today,

    # Слабый сигнал — нет изменений
    lambda signal: signal["delta"] == 0 and signal["urgency"] != "critical",

    # Артур активен в диалоге (есть входящее сообщение <30 мин назад)
    lambda: last_user_message_age_min < 30,
]
```

**[Скептик]:** Определение "Артур активен" — нет прямого API. Заглушка: если heartbeat видел активность в последние 30 мин → молчать. Реализовать через `soul/user_last_seen.json` который пишет heartbeat.

---

## 5. Правила порога (что достаточно сильный сигнал)

```python
THRESHOLDS = {
    "open_thread_urgent": True,           # urgency == "action_needed" → всегда сигнал
    "radar_new_registration": 1,          # ≥1 новая регистрация за 24ч
    "cronbun_subscriber_delta": 5,        # +5 подписчиков за 24ч
    "weather_warning": ["rain", "storm", "ice"],  # опасная погода
    "close_person_silent_days": 3,        # Лера/сын не писали >3 дней
    "close_person_silent_days_son": 7,    # сын не писал >7 дней
}
```

Всё что ниже этих порогов — не отправляем, только логируем в `soul/signals_log.jsonl`.

---

## 6. Расписание

```cron
# Soul Daemon — каждый час, кроме ночи
0 8-23 * * * python3 /home/looi/.openclaw/workspace/soul/soul_collect.py >> /home/looi/.openclaw/workspace/soul/daemon.log 2>&1
```

**Почему не каждые 30 мин:** большинство источников обновляются раз в несколько часов. Час — разумный баланс между свежестью и шумом. Ночью (00:00-08:00) — не запускаем (кроме critical urgency в ved).

---

## 7. Хранение состояния

**`soul/sent_log.json`** — что уже отправили:
```json
{
  "2026-04-03": {
    "sent": [
      {"key": "radar_registration", "timestamp": "10:15", "summary": "..."},
      {"key": "lera_silent", "timestamp": "19:00", "summary": "..."}
    ]
  }
}
```

**`soul/signals_latest.json`** — последний срез данных (перезаписывается каждый раз):
```json
{
  "timestamp": "2026-04-03T15:00:00",
  "open_threads_urgent": 2,
  "radar_registrations_24h": 3,
  "cronbun_delta": 0,
  "weather_moscow": {"temp": 12, "desc": "Облачно"},
  "weather_volzhsky": {"temp": 18, "desc": "Ясно"},
  "lera_last_message_hours_ago": 6,
  "son_last_message_hours_ago": 72
}
```

**`soul/signals_prev.json`** — предыдущий срез для подсчёта delta.

**`soul/signals_log.jsonl`** — все срезы для отладки и анализа.

---

## 8. Token cost оценка

| Сценарий | Токены | Стоимость |
|---|---|---|
| Нет сигнала (только Python) | 0 | $0 |
| Есть сигнал → g-flash синтез | ~800 in + ~300 out | ~$0.0005 |
| **1 день активный (3-4 сигнала)** | ~4400 | **~$0.002** |
| **1 день тихий (0-1 сигнал)** | ~800 | **~$0.0004** |

Это на порядок дешевле heartbeat. Основная экономия: сбор и фильтрация без LLM.

---

## 9. v1 план — что реализовать первым

**Неделя 1 — только сбор и тишина:**
```python
# soul/soul_collect.py
import json, requests, datetime

WORKSPACE = "/home/looi/.openclaw/workspace"

def collect():
    signals = {}

    # 1. ved/state.json
    with open(f"{WORKSPACE}/ved/state.json") as f:
        ved = json.load(f)
    urgent = [t for t in ved.get("open_threads", [])
              if t.get("urgency") == "action_needed"]
    signals["open_threads_urgent"] = len(urgent)
    signals["open_threads_urgent_titles"] = [t.get("title") for t in urgent]

    # 2. Погода
    for city, name in [("Moscow", "moscow"), ("Volzhsky", "volzhsky")]:
        r = requests.get(f"https://wttr.in/{city}?format=j1", timeout=5)
        if r.ok:
            w = r.json()["current_condition"][0]
            signals[f"weather_{name}"] = {
                "temp": w["temp_C"],
                "desc": w["weatherDesc"][0]["value"]
            }

    # 3. Сохранить
    prev_path = f"{WORKSPACE}/soul/signals_latest.json"
    if os.path.exists(prev_path):
        import shutil
        shutil.copy(prev_path, f"{WORKSPACE}/soul/signals_prev.json")

    signals["timestamp"] = datetime.datetime.now().isoformat()
    with open(prev_path, "w") as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)

    print(f"Collected: {len(signals)} signals")

if __name__ == "__main__":
    collect()
```

**Неделя 2:** добавить soul_decide.py + правила тишины + первый LLM синтез (g-flash).
**Неделя 3:** подключить radar PocketBase API + Telegram sessions для Леры/сына.

---

## Риски (Скептик, финальное слово)

1. **Telegram sessions** — нет прямого API для чтения диалогов с конкретными людьми. Нужен MTProto или специальный endpoint. Без этого — Лера/сын остаются вне v1.
2. **CronBun stats** — нет публичного API для delta подписчиков. Нужно кастомное решение.
3. **Drift порогов** — через месяц "3 новые регистрации" может быть нормой, а не сигналом. Пороги нужно пересматривать вручную раз в месяц.
4. **Шум от погоды** — "Облачно в Волжском" не является сигналом. Фильтровать только экстремальные условия.
5. **LLM галлюцинация** — g-flash может "додумать" интерпретацию. Давать ему только сырые факты, не просить интерпретировать намерения людей.

---

*Создан: 2026-04-03. Автор: Клин + Совет (Скептик/Практик/Архитектор).*
