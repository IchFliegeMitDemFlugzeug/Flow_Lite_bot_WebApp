"""Утилиты работы с базой данных для backend Mini App."""

from __future__ import annotations  # Включаем отложенные аннотации

import importlib.util  # Проверяем наличие зависимостей
import json  # Сериализуем тела событий
import logging  # Логируем ошибки и пропуски записи
import os  # Читаем строку подключения из переменных окружения
from datetime import datetime  # Формируем метку времени для JSON-лога
from pathlib import Path  # Работаем с путями к файлам пользователей
from typing import Any  # Типизация параметров для SQL

if importlib.util.find_spec("sqlalchemy") is not None:  # Проверяем, доступна ли SQLAlchemy в окружении
    from sqlalchemy import create_engine, text  # type: ignore  # Создаём подключение и формируем SQL
    from sqlalchemy.engine import Engine  # type: ignore  # Тип движка для аннотаций
    from sqlalchemy.exc import SQLAlchemyError  # type: ignore  # Отлавливаем ошибки работы с БД
else:  # Если зависимости нет, отключаем запись
    create_engine = None  # type: ignore
    text = None  # type: ignore
    Engine = Any  # type: ignore

    class SQLAlchemyError(Exception):  # Заглушка исключения
        """Плейсхолдер для отсутствующей SQLAlchemy."""

logger = logging.getLogger(__name__)  # Локальный логгер модуля

_engine: Engine | None = None  # Кешируем созданный движок


def _get_engine() -> Engine | None:  # Возвращает движок SQLAlchemy или None, если строка подключения не задана
    global _engine  # Используем модульную переменную для кеша

    if _engine is not None:  # Если движок уже создан
        return _engine  # Возвращаем его

    if create_engine is None or text is None:  # Если SQLAlchemy недоступна
        logger.warning("WebApp API: SQLAlchemy не установлена, запись событий недоступна")  # Сообщаем в лог
        return None  # Не пытаемся подключаться к БД

    database_url = os.getenv("DATABASE_URL")  # Читаем строку подключения из окружения
    if not database_url:  # Если переменная не указана
        logger.warning("WebApp API: DATABASE_URL не задан, запись событий пропущена")  # Логируем предупреждение
        return None  # Возвращаем None, чтобы вызывающий код пропустил запись

    _engine = create_engine(database_url)  # Создаём движок SQLAlchemy
    return _engine  # Возвращаем созданный движок


def _get_users_dir() -> Path:  # Получаем путь до папки users рядом с db.py
    base_dir = Path(__file__).resolve().parent  # Определяем папку, где лежит db.py
    users_dir = base_dir / "users"  # Формируем путь до подпапки users
    users_dir.mkdir(parents=True, exist_ok=True)  # Создаём папку, если её ещё нет
    return users_dir  # Возвращаем готовый путь


def _format_event_time() -> str:  # Формируем строку даты/времени в нужном формате
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")  # Возвращаем дату и время как строку


def _append_user_event(payload: dict[str, Any]) -> None:  # Добавляем событие в JSON-файл пользователя
    creator_id = payload.get("inline_creator_tg_user_id")  # Берём ID отправителя инлайн-сообщения
    if not creator_id:  # Если ID отправителя не передан
        logger.info("WebApp API: creator_tg_user_id не найден, запись в users пропущена")  # Логируем пропуск
        return  # Ничего не записываем

    users_dir = _get_users_dir()  # Получаем путь до папки users
    safe_filename = f"{creator_id}.json"  # Формируем имя файла по ID отправителя
    user_file = users_dir / safe_filename  # Формируем полный путь к файлу пользователя

    event_record = {  # Формируем запись события
        "event_time": _format_event_time(),  # Добавляем время события в формате ДД.ММ.ГГГГ ЧЧ:ММ:СС
        "payload": payload,  # Сохраняем полный входящий payload без изменений
    }  # Закрываем словарь записи

    existing_events: list[dict[str, Any]] = []  # Готовим контейнер под существующие события
    if user_file.exists():  # Если файл уже существует
        try:  # Пробуем прочитать текущие данные
            raw_text = user_file.read_text(encoding="utf-8")  # Читаем содержимое файла
            parsed = json.loads(raw_text)  # Парсим JSON в объект Python
            if isinstance(parsed, list):  # Если файл хранит список событий
                existing_events = parsed  # Используем текущий список
            else:  # Если структура файла неожиданная
                logger.warning("WebApp API: файл %s имеет неверный формат, создаём новый список", user_file)  # Логируем проблему
        except Exception as exc:  # Если чтение или парсинг не удались
            logger.warning("WebApp API: не удалось прочитать %s: %s", user_file, exc)  # Пишем предупреждение

    existing_events.append(event_record)  # Добавляем новую запись к списку событий
    user_file.write_text(  # Записываем список обратно в файл
        json.dumps(existing_events, ensure_ascii=False, indent=2),  # Сохраняем читабельный JSON
        encoding="utf-8",  # Пишем файл в UTF-8
    )  # Завершаем запись файла


def save_webapp_event(payload: dict[str, Any]) -> None:  # Пишем событие Mini App в таблицу inline_webapp_events
    _append_user_event(payload)  # Сохраняем событие в JSON-файл пользователя

    engine = _get_engine()  # Получаем движок БД
    if engine is None:  # Если нет строки подключения
        return  # Просто выходим, запись в БД не производится

    transfer_id: str = str(payload.get("transfer_id") or "")  # Извлекаем transfer_id из пакета
    inline_payload_json: str = json.dumps(payload.get("transfer_payload") or {}, ensure_ascii=False)  # Сохраняем исходный пакет
    inline_context_json: str = json.dumps(  # Собираем контекст инлайна отдельно
        {
            "creator_tg_user_id": payload.get("inline_creator_tg_user_id"),  # Автор инлайн-сообщения
            "generated_at": payload.get("inline_generated_at"),  # Время генерации сообщения
            "parsed": payload.get("inline_parsed") or {},  # Распарсенный контент
            "option": payload.get("inline_option") or {},  # Выбранная опция перевода
        },
        ensure_ascii=False,
    )

    opener = (payload.get("initDataUnsafe") or {}).get("user") or {}  # Достаём информацию об открывшем Mini App
    opener_tg_user_id = opener.get("id")  # Telegram ID открывшего
    opener_json = json.dumps(opener, ensure_ascii=False)  # Полный объект открывшего
    raw_init_data: str = payload.get("initData") or ""  # Сырая строка initData

    sql = text(  # Формируем UPSERT для таблицы inline_webapp_events
        """
        INSERT INTO inline_webapp_events
            (transfer_id, inline_payload_json, inline_context_json, opener_tg_user_id, opener_json, raw_init_data, created_at)
        VALUES
            (:transfer_id, :inline_payload_json, :inline_context_json, :opener_tg_user_id, :opener_json, :raw_init_data, CURRE
NT_TIMESTAMP)
        ON DUPLICATE KEY UPDATE
            inline_payload_json = VALUES(inline_payload_json),
            inline_context_json = VALUES(inline_context_json),
            opener_tg_user_id  = COALESCE(VALUES(opener_tg_user_id), opener_tg_user_id),
            opener_json        = COALESCE(VALUES(opener_json), opener_json),
            raw_init_data      = COALESCE(VALUES(raw_init_data), raw_init_data),
            created_at         = created_at;
        """
    )

    params = {  # Параметры для подстановки в SQL
        "transfer_id": transfer_id,
        "inline_payload_json": inline_payload_json,
        "inline_context_json": inline_context_json,
        "opener_tg_user_id": opener_tg_user_id,
        "opener_json": opener_json,
        "raw_init_data": raw_init_data,
    }

    try:  # Пытаемся записать событие
        with engine.begin() as connection:  # Создаём транзакцию
            connection.execute(sql, params)  # Выполняем UPSERT
        logger.info("WebApp API: событие %s записано в БД", transfer_id)  # Логируем успешную запись
    except SQLAlchemyError as exc:  # Ловим ошибки БД
        logger.warning("WebApp API: ошибка БД при сохранении transfer_id=%s: %s", transfer_id, exc)  # Сообщаем о проблеме
    except Exception as exc:  # Ловим любые другие исключения
        logger.warning("WebApp API: неожиданная ошибка при сохранении transfer_id=%s: %s", transfer_id, exc)  # Пишем предупреждение
