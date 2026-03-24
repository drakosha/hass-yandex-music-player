# Yandex Music Player для Home Assistant

Интеграция для воспроизведения Яндекс.Музыки на **произвольном** media_player в Home Assistant — не только на Яндекс.Станциях.

## Возможности

- **Браузер библиотеки** — треки, плейлисты, альбомы, исполнители через стандартный Media Browser HA
- **Воспроизведение на любом плеере** — Kodi, DLNA, AirPlay, Chromecast, Sonos, VLC и др.
- **Очередь воспроизведения** — плейлисты и альбомы играются целиком с автоматическим переходом между треками
- **Радио / Моя волна** — бесконечное воспроизведение с подгрузкой новых треков
- **Shuffle / Repeat** — перемешивание и режимы повтора (один трек / весь плейлист)

## Требования

- Home Assistant 2024.1+
- [AlexxIT/YandexStation](https://github.com/AlexxIT/YandexStation) — для авторизации
- Подписка Яндекс.Музыка Плюс (для полных треков)

## Установка

### HACS (рекомендуется)

1. Откройте HACS → Интеграции → ⋮ → Пользовательские репозитории
2. Добавьте URL репозитория, тип: Integration
3. Найдите «Yandex Music Player» и установите
4. Перезагрузите Home Assistant

### Ручная установка

```bash
# Скопируйте папку в custom_components
cp -r custom_components/yandex_music_player /config/custom_components/
```

## Настройка

1. Убедитесь, что AlexxIT/YandexStation установлен и авторизован
2. Настройки → Интеграции → Добавить → **Yandex Music Player**
3. Выберите:
   - **Целевой плеер** — на каком устройстве играть музыку
   - **Аккаунт YandexStation** — для авторизации в Яндекс.Музыке

## Использование

### Через UI

Откройте карточку созданного media_player → кнопка «Медиа» → Яндекс Музыка.
Появится дерево: Мне нравится / Плейлисты / Альбомы / Исполнители / Радио.

### Через сервисы (автоматизации)

```yaml
# Воспроизвести плейлист
service: media_player.play_media
target:
  entity_id: media_player.yandex_music
data:
  media_content_type: ym_playlist
  media_content_id: "12345678:3"  # uid:playlist_kind

# Воспроизвести альбом
service: media_player.play_media
target:
  entity_id: media_player.yandex_music
data:
  media_content_type: ym_album
  media_content_id: "1193829"

# Воспроизвести трек
service: media_player.play_media
target:
  entity_id: media_player.yandex_music
data:
  media_content_type: ym_track
  media_content_id: "10994777"

# Включить Мою волну
service: media_player.play_media
target:
  entity_id: media_player.yandex_music
data:
  media_content_type: ym_radio
  media_content_id: "user:onyourwave"

# Включить радио-станцию
service: media_player.play_media
target:
  entity_id: media_player.yandex_music
data:
  media_content_type: ym_radio
  media_content_id: "genre:rock"
```

### Атрибуты

| Атрибут | Описание |
|---------|----------|
| `target_player` | entity_id целевого плеера |
| `queue_length` | Количество треков в очереди |
| `queue_position` | Текущая позиция в очереди |
| `is_radio` | Режим радио активен |

## Архитектура

```
┌────────────────────┐     ┌──────────────────────┐
│  YandexStation      │────▶│  Auth Token           │
│  (AlexxIT)          │     └──────────┬───────────┘
└────────────────────┘                 │
                                       ▼
┌────────────────────┐     ┌──────────────────────┐
│  Yandex Music API   │◀───│  yandex-music lib     │
│  (api.py)           │     │  (MarshalX)           │
└────────┬───────────┘     └──────────────────────┘
         │
         ▼
┌────────────────────┐     ┌──────────────────────┐
│  Queue Manager      │────▶│  Track URLs (signed)  │
│  (queue.py)         │     └──────────────────────┘
└────────┬───────────┘
         │
         ▼
┌────────────────────┐     ┌──────────────────────┐
│  Virtual Player     │────▶│  Target media_player  │
│  (media_player.py)  │     │  (Kodi, DLNA, etc.)   │
└────────────────────┘     └──────────────────────┘
```

Компонент создаёт **виртуальный** media_player, который:
1. Получает токен из YandexStation
2. Через yandex-music API получает подписанные URL треков
3. Отправляет URL на целевой плеер через `media_player.play_media`
4. Отслеживает состояние целевого плеера (state_changed)
5. При завершении трека автоматически запускает следующий

## Известные ограничения

- URL треков временные (~30 мин), перед воспроизведением запрашиваются свежие
- Некоторые плееры могут не поддерживать формат потока (попробуйте mp3 320kbps)
- Точность определения конца трека зависит от того, как целевой плеер переходит в состояние idle
- Для радио/Моей волны нужна подписка Плюс

## Лицензия

MIT
