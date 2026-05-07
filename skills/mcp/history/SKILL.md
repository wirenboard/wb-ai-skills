---
name: history
description: История данных и статистика с контроллеров WB через MCP — wb_history (точки + min/max/avg из wb-mqtt-db).
allowed-tools: Bash Read WebFetch
---

# history (MCP)

История данных с контроллеров Wiren Board. Сервис `wb-mqtt-db` логирует MQTT-каналы в SQLite. MCP-tool `wb_history` инкапсулирует RPC `db_logger/history/get_values`.

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Точки по каналам за период | `wb_history` (sn, channels — массив пар, time-range, min_interval, limit) |
| **Готовый SVG-чарт** | `wb_history_chart` (line/bar/area/point/histogram/heatmap/boxplot, 1/2/3+ единиц с двойной осью или нормализацией) |
| min/max/avg за период | агрегируй полученные `min`/`max`/`value` бакетов локально |
| Список устройств | `wb_mqtt_devices` |
| Список контролов устройства | `wb_mqtt_controls` |
| Жив ли wb-mqtt-db | `wb_failed` (упал?), `wb_logs unit=wb-mqtt-db` |
| Проверка пакета | `wb_ssh_exec` `dpkg -l wb-mqtt-db; systemctl is-active wb-mqtt-db` |

## Шаг 1 — найди каналы

**Никогда не угадывай имена.** RPC принимает пары `[device_id, control_name]`:

- `wb_mqtt_devices sn=<SN>` — все устройства.
- `wb_mqtt_controls sn=<SN> device=<device_id>` — каналы устройства.

Имена часто с пробелами: `CPU Temperature`, `Board Temperature` — используй дословно.

## Шаг 2 — запроси данные (multi-channel за один вызов)

```
wb_history sn=<SN> channels=[["hwmon","CPU Temperature"],["hwmon","Board Temperature"],["wb-mr6c_2","K1"]] from=<unix_ts> to=<unix_ts> min_interval=0 limit=200
```

`channels` — **массив пар**: запрашивай сразу все интересующие каналы за один RPC. `limit` применяется per-channel (не суммарно). Это и быстрее, и удобнее для построения сравнительных графиков.

Параметры периода (timestamp, секунды):

| Период | from |
|--------|------|
| За час | `now - 3600` |
| За сутки | `now - 86400` |
| За неделю | `now - 604800` |
| За месяц | `now - 2592000` |

## Прореживание и формат ответа

| Диапазон | min_interval | limit |
|----------|--------------|-------|
| ≤ 1 час | 0 | 200 |
| ≤ 24 часа | 60 | 500 |
| > 24 часов | 600 | 1000 |

Каждая точка — **бакет**, не отдельное измерение. Поля: `t` (timestamp начала бакета), `value` (сглаженное среднее), `min`, `max`. Даже при `min_interval=0` сервер агрегирует ~120 с — поэтому 30 точек на час норма.

Для поиска **скачков и пиков** смотри `max` (или `max - min` внутри бакета), не `value` соседних бакетов: `value` сглажен и пропустит транзиентные пики 5-10 единиц, длящиеся <1 минуты.

## Визуализация: разные единицы на одном графике

Это **не бессмысленно** — нужно правильно нарисовать. Стандартные стратегии:

| Сколько разных единиц | Что делать |
|----------------------|-----------|
| 1 (например, две температуры в `°C`) | Одна Y-шкала, обе линии на ней |
| 2 (`°C` + `%`) | Двойная Y-шкала: левая ось для одной единицы, правая для другой |
| 3+ | Нормализуй каждый канал в `[0;1]` (по своему `min..max`), оригинальные диапазоны — в легенде. Альтернатива: faceted (subplot на единицу) |

Варианты рендера:
- **`wb_history_chart` (рекомендуемый)** — встроен в MCP-сервер на Vega-Lite. Один вызов: получает данные через `db_logger/history/get_values`, строит SVG. Поддерживает: `line` (default), `bar`, `area`, `point`, `histogram`, `heatmap`, `boxplot`. Логика осей:
   - 1 unit → одна Y-шкала.
   - 2 units → двойная ось (`resolve.scale.y: independent`, левая+правая).
   - 3+ units → нормализация в [0;1], оригинальные диапазоны в легенде.

  ```
  wb_history_chart sn=<SN> channels=[["hwmon","CPU Temperature"],["hwmon","Board Temperature"]] period=1h chartType=line title="Temps last hour"
  # → возвращает {svg, svgBytes, totalPoints, channels, from, to}; SVG inline (если <200КБ)
  wb_history_chart sn=<SN> channels=[...] period=24h chartType=heatmap outputPath=/tmp/cpu.svg
  # → записывает в файл, в ответе только {ok, outputPath, ...}
  ```

  **Когда отдавать `outputPath`:** если прошёл день/неделя на 3+ каналах, SVG может быть >200 КБ — inline-ответ MCP-сервер откажется отдавать. Сохраняй в файл и пользователю отдай путь.

- **Mermaid `xychart-beta`** (с v10) — рендерится в Markdown (Claude Code, Github, Mermaid-совместимые просмотрщики). **Только одна Y-шкала** — для одной серии или серий с одинаковой единицей. Подходит, когда не хочется генерить SVG-файл.
  ```mermaid
  xychart-beta
      title "CPU Temperature, °C"
      x-axis [16:55, 17:10, 17:25, 17:40, 17:55]
      y-axis "°C" 65 --> 85
      line [69.9, 71.1, 75.3, 76.0, 70.5]
  ```

- **Python + matplotlib** или внешний UI — если нужен другой стиль/формат. Отдай JSON-результат `wb_history`, обработай локально.

Для bash-сводки достаточно min/max/avg + ASCII sparkline.

## Проверка wb-mqtt-db

```
wb_ssh_exec sn=<SN> cmd='systemctl is-active wb-mqtt-db'
```

Если `inactive` — **не ставь сам**, отчитайся пользователю и согласуй: установка идёт через `/software-install` (рекомендуем не нативно через apt, а оставить wb-mqtt-db как stock-пакет — он есть в WB-репо).

Если `wb_history` возвращает пусто — проверь, что:
- `wb-mqtt-db` живой (`wb_failed`, `wb_logs unit=wb-mqtt-db`).
- Канал не в исключениях `/etc/wb-mqtt-db.conf` (читай через `wb_read_file`).
- `wb-mqtt-db` не установлен недавно — данных за прошлое нет.

## Грабли

- Имена каналов обрезать нельзя: `"CPU"` ≠ `"CPU Temperature"`.
- Если `wb-mqtt-db` недавно установлен — данных за прошлое нет.
- `value` сглажен по бакету, `min`/`max` показывают реальные пики — для поиска скачков смотри `max`.
- `limit` per-channel — при 5 каналах и `limit:200` вернётся до 1000 точек.
- Большие диапазоны без `min_interval` забивают ответ — указывай прореживание.
