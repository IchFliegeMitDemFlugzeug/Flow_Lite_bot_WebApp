"""Простой HTTP-сервер для Mini App с динамической генерацией банковских ссылок."""

from __future__ import annotations  # Включаем отложенные аннотации для читаемости

import hashlib  # Считаем SHA-256 для чувствительных данных
import json  # Работаем с JSON-телами запросов и ответов
import logging  # Логируем ошибки и служебные события
import os  # Читаем переменные окружения для настройки сервера
import sys  # Настраиваем sys.path для запуска из разных директорий
import time  # Используем unix-время для TTL токенов
import uuid  # Генерируем уникальные токены ссылок
from datetime import datetime  # Создаём человекочитаемые метки времени
from http.server import BaseHTTPRequestHandler, HTTPServer  # Минимальный HTTP-сервер из стандартной библиотеки
from pathlib import Path  # Работаем с путями до конфигураций
from typing import Any, Dict, List, Tuple  # Типизация для читаемости кода
from urllib.parse import parse_qs, urlparse  # Разбираем URL и query-параметры

backend_root = Path(__file__).resolve().parent  # Абсолютный путь до каталога backend
FRONTEND_LOGS_DIR_NAME = "logs"  # Имя папки для логов фронтенда внутри backend
FRONTEND_LOGS_DIR = backend_root / FRONTEND_LOGS_DIR_NAME  # Абсолютный путь до папки Flow_Lite_bot_WebApp_Backend/logs
if str(backend_root) not in sys.path:  # Убеждаемся, что каталог в sys.path
    sys.path.insert(0, str(backend_root))  # Добавляем путь, чтобы локальные модули находились

from db import save_webapp_event  # Импортируем запись событий в БД из локального модуля
from link_builder import default_link_builder  # Подключаем единый конструктор ссылок


logging.basicConfig(  # Настраиваем базовый логгер с подробным форматом
    level=logging.INFO,  # Ставим уровень DEBUG, чтобы видеть каждый шаг
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",  # Подробный формат сообщений
    datefmt="%Y-%m-%d %H:%M:%S",  # Формат даты для удобства чтения
)  # Закрываем конфигурацию базового логгера
logger = logging.getLogger(__name__)  # Получаем логгер этого модуля

DEBUG_LOG_MAX_BODY_BYTES = 256 * 1024  # Ограничиваем размер тела для debug-логов (256 КБ)
DEBUG_LOG_MAX_STRING_LENGTH = 2000  # Ограничиваем длину строк внутри debug-логов


def humanize_bytes(value: bytes | str) -> str:  # Делаем байтовые/экранированные строки читабельными в логах
    text = (  # Приводим вход к строке для дальнейшей обработки
        value.decode("utf-8", errors="replace") if isinstance(value, (bytes, bytearray)) else str(value)
    )  # Если пришли байты — декодируем в UTF-8 с заменой ошибок, иначе просто str()
    try:  # Пробуем понять, нужна ли дополнительная «распаковка» \x-последовательностей
        if "\\x" in text:  # Если в строке есть символы вида "\xHH", значит лог покажет нечитаемую байтовую маску
            return text.encode("latin-1", errors="replace").decode("utf-8", errors="replace")  # Восстанавливаем текст через latin-1 → utf-8
    except Exception:  # Если что-то пошло не так
        return text  # Возвращаем уже подготовленный текст без падения
    return text  # Если дополнительных преобразований не требуется, отдаём базовую строку


def ensure_debug_logs_dir() -> Path:  # Гарантируем наличие папки для debug-логов фронтенда
    FRONTEND_LOGS_DIR.mkdir(parents=True, exist_ok=True)  # Создаём каталог логов, если его ещё нет
    return FRONTEND_LOGS_DIR  # Возвращаем путь до каталога логов фронтенда


def compute_initdata_sha256(value: str) -> str:  # Считаем SHA-256 для строки initData
    payload = value.encode("utf-8", errors="replace")  # Превращаем строку в байты с защитой от ошибок
    return hashlib.sha256(payload).hexdigest()  # Возвращаем hex-представление хеша


def truncate_string(value: str, max_length: int) -> str:  # Обрезаем длинные строки до допустимого размера
    if len(value) <= max_length:  # Если строка уже короче лимита
        return value  # Возвращаем её без изменений
    return value[:max_length]  # Обрезаем строку по лимиту, чтобы запись была безопасной


def sanitize_debug_payload(payload: Any, max_string_length: int) -> Any:  # Удаляем initData и ограничиваем длину строк
    if isinstance(payload, dict):  # Если пришёл словарь
        sanitized: Dict[str, Any] = {}  # Создаём новый словарь для безопасных данных
        for key, value in payload.items():  # Обходим все ключи и значения
            if key == "initData":  # Если ключ содержит сырую initData
                raw_value = value if isinstance(value, str) else str(value)  # Приводим initData к строке
                sanitized["initDataLen"] = len(raw_value)  # Записываем длину initData
                sanitized["initDataSha256"] = compute_initdata_sha256(raw_value)  # Пишем SHA-256 вместо initData
                continue  # Не сохраняем исходный initData
            sanitized[key] = sanitize_debug_payload(value, max_string_length)  # Рекурсивно обрабатываем вложенные поля
        return sanitized  # Возвращаем очищенный словарь
    if isinstance(payload, list):  # Если пришёл список
        return [sanitize_debug_payload(item, max_string_length) for item in payload]  # Очищаем каждый элемент списка
    if isinstance(payload, str):  # Если пришла строка
        return truncate_string(payload, max_string_length)  # Обрезаем строку до лимита
    return payload  # Для остальных типов возвращаем значение без изменений


class LinkTokenStore:  # Простое хранилище токенов deeplink-ссылок с TTL
    def __init__(self, ttl_seconds: int = 300) -> None:  # Конструктор принимает TTL в секундах
        self.ttl_seconds = ttl_seconds  # Сохраняем время жизни токенов
        self._storage: Dict[str, Tuple[float, dict]] = {}  # Словарь token -> (expires_at, payload)
        logger.debug("LinkTokenStore: создан экземпляр с TTL=%s секунд", self.ttl_seconds)  # Логируем инициализацию

    def issue_token(self, payload: dict) -> str:  # Создаём и запоминаем новый токен
        token = uuid.uuid4().hex  # Генерируем случайный токен
        logger.debug("LinkTokenStore: генерируем новый токен %s", token)  # Сообщаем о генерации токена
        expires_at = time.time() + self.ttl_seconds  # Считаем время истечения токена
        logger.debug(
            "LinkTokenStore: рассчитано время истечения %s для токена %s", expires_at, token
        )  # Фиксируем TTL токена
        self._storage[token] = (expires_at, payload)  # Кладём payload вместе с временем истечения
        logger.debug("LinkTokenStore: сохранён payload %s для токена %s", payload, token)  # Логируем сохранение payload
        return token  # Возвращаем токен для клиента

    def get_payload(self, token: str) -> dict | None:  # Получаем payload по токену
        logger.debug("LinkTokenStore: ищем токен %s", token)  # Фиксируем попытку найти токен
        record = self._storage.get(token)  # Ищем запись в словаре
        if not record:  # Если записи нет
            logger.debug("LinkTokenStore: токен %s не найден", token)  # Сообщаем, что записи нет
            return None  # Возвращаем None
        expires_at, payload = record  # Распаковываем запись
        logger.debug(
            "LinkTokenStore: найден токен %s с истечением %s и payload %s", token, expires_at, payload
        )  # Показываем содержимое записи
        if time.time() > expires_at:  # Если TTL истёк
            logger.debug("LinkTokenStore: токен %s устарел, удаляем", token)  # Сообщаем в лог
            self._storage.pop(token, None)  # Удаляем запись
            return None  # Возвращаем None
        logger.debug("LinkTokenStore: токен %s актуален, возвращаем payload", token)  # Подтверждаем актуальность
        return payload  # Отдаём сохранённый payload


token_store = LinkTokenStore()  # Глобальное хранилище токенов для страницы редиректа
link_builder = default_link_builder()  # Глобальный экземпляр конструктора ссылок (JSON читается один раз)

def base64_decode(value: str) -> str:  # Вспомогательная функция для base64url
    import base64  # Импортируем локально, чтобы не засорять глобальные импорты

    logger.debug("Base64 decode: входное значение %s", value)  # Логируем входное значение
    decoded_bytes = base64.b64decode(value.encode("utf-8"))  # Декодируем строку в байты
    logger.debug(  # Фиксируем промежуточный результат понятным текстом
        "Base64 decode: получили строку %s", humanize_bytes(decoded_bytes)
    )  # Применяем humanize_bytes, чтобы байты не распечатывались в виде \x-последовательностей
    return decoded_bytes.decode("utf-8")  # Превращаем байты обратно в строку


def decode_transfer_payload(start_param: str) -> dict:  # Раскодируем start_param, чтобы узнать тип реквизита
    if not start_param:  # Если параметр пустой
        logger.debug("Decode transfer payload: пустой start_param, возвращаем {}")  # Сообщаем об отсутствии данных
        return {}  # Возвращаем пустой словарь
    try:  # Пробуем декодировать base64url → JSON
        normalized = start_param.replace("-", "+").replace("_", "/")  # Возвращаем стандартные символы base64
        logger.debug("Decode transfer payload: нормализованное значение %s", normalized)  # Логируем нормализованное значение
        padding = "=" * ((4 - len(normalized) % 4) % 4)  # Считаем недостающие символы '='
        logger.debug("Decode transfer payload: рассчитанная набивка %s", padding)  # Показываем добавочный padding
        decoded = json.loads(base64_decode(normalized + padding))  # Превращаем JSON-строку в объект
        logger.debug("Decode transfer payload: раскодированный объект %s", decoded)  # Демонстрируем результат декодирования
        return decoded if isinstance(decoded, dict) else {}  # Возвращаем dict, иначе пустой объект
    except Exception as exc:  # Если что-то пошло не так
        logger.debug("WebApp API: не удалось раскодировать transfer_id %s: %s", start_param, exc)  # Логируем проблему
        return {}  # Возвращаем пустой объект


def detect_identifier(transfer_id: str, payload: dict) -> Tuple[str, str]:  # Определяем тип и значение реквизита
    inner_payload = payload.get("payload") if isinstance(payload, dict) else {}  # Берём вложенный payload, если передан внешний контейнер
    logger.debug("Detect identifier: передан внешний payload %s", payload)  # Показываем исходные данные целиком
    if not isinstance(inner_payload, dict):  # Если вложенный payload не является словарём
        inner_payload = payload if isinstance(payload, dict) else {}  # Используем исходный объект как рабочий
    logger.debug("Detect identifier: используем внутренний payload %s", inner_payload)  # Фиксируем выбранный слой данных

    raw_option = (inner_payload.get("option") if isinstance(inner_payload, dict) else None) or (  # Пробуем взять option из основной схемы
        inner_payload.get("inline_option") if isinstance(inner_payload, dict) else None
    )  # Если основного option нет, ищем inline_option
    option = raw_option if isinstance(raw_option, dict) else {}  # Гарантируем, что option — словарь
    logger.debug("Detect identifier: разобранный option %s", option)  # Показываем итоговый option

    if "identifier" in option:  # Новая схема: идентификатор передаётся в поле identifier
        raw_identifier = str(option.get("identifier"))  # Фиксируем исходное значение как строку
        payment_type = (option.get("payment_type") or "").lower()  # Считываем тип платежа, если он указан
        logger.debug(
            "Detect identifier: найден identifier=%s с payment_type=%s",
            raw_identifier,
            payment_type,
        )  # Сообщаем, что используем новую схему

        normalized_phone = "".join(ch for ch in raw_identifier if ch.isdigit() or ch == "+")  # Для телефона оставляем + и цифры
        normalized_card = "".join(ch for ch in raw_identifier if ch.isdigit())  # Для карты оставляем только цифры
        logger.debug(
            "Detect identifier: нормализованный телефон=%s, карта=%s",
            normalized_phone,
            normalized_card,
        )  # Показываем варианты нормализации

        identifier_type: str | None = None  # Подготовим переменную для типа реквизита
        identifier_value: str | None = None  # И переменную для значения

        if payment_type == "phone":  # Если явно указан телефон
            identifier_type = "phone"  # Фиксируем тип phone
            identifier_value = normalized_phone  # Используем телефонную нормализацию
        elif payment_type == "card":  # Если явно указана карта
            identifier_type = "card"  # Фиксируем тип card
            identifier_value = normalized_card  # Используем карточную нормализацию
        else:  # Если тип не указан, определяем по длине цифр
            digits_only = "".join(ch for ch in raw_identifier if ch.isdigit())  # Берём только цифры для подсчёта длины
            if 10 <= len(digits_only) <= 15:  # Диапазон телефона
                identifier_type = "phone"  # Считаем идентификатор телефоном
                identifier_value = normalized_phone  # Оставляем + и цифры
            elif len(digits_only) >= 16:  # Минимальная длина, похожая на номер карты
                identifier_type = "card"  # Считаем идентификатор картой
                identifier_value = normalized_card  # Берём только цифры

        if identifier_type and identifier_value:  # Если нам удалось классифицировать
            logger.debug(  # Фиксируем успешную классификацию
                "Detect identifier: классифицировано как %s со значением %s",
                identifier_type,
                identifier_value,
            )
            return identifier_type, identifier_value  # Возвращаем найденные данные

    if "phone" in option:  # Старая схема: телефон лежит в поле phone
        logger.debug("Detect identifier: найден phone %s", option.get("phone"))  # Логируем найденный телефон
        return "phone", str(option.get("phone"))  # Возвращаем тип phone и его значение
    if "card" in option:  # Старая схема: карта лежит в поле card
        logger.debug("Detect identifier: найдена карта %s", option.get("card"))  # Логируем найденную карту
        return "card", str(option.get("card"))  # Возвращаем тип card и значение

    digits_only = "".join(ch for ch in transfer_id if ch.isdigit() or ch == "+")  # Fallback: берём только цифры из transfer_id
    logger.debug("Detect identifier: fallback очищенное значение transfer_id %s", digits_only)  # Показываем очищенные данные
    if 10 <= len(digits_only) <= 15:  # Если похоже на телефон
        logger.debug("Detect identifier: классифицируем fallback как phone %s", digits_only)  # Фиксируем классификацию телефона
        return "phone", digits_only  # Возвращаем тип phone
    if len(digits_only) >= 16:  # Если похоже на карту
        logger.debug("Detect identifier: классифицируем fallback как card %s", digits_only)  # Фиксируем классификацию карты
        return "card", digits_only  # Возвращаем тип card

    raise ValueError("Невозможно определить тип идентификатора")  # Сообщаем о невозможности распознать реквизит


def load_banks_config() -> List[dict]:  # Загружаем banks.json из конфигурации
    config_path = Path(__file__).resolve().parent / "config" / "banks.json"  # Формируем путь до файла относительно backend.py
    logger.debug("Load banks config: путь к конфигурации %s", config_path)  # Логируем путь до файла конфигурации
    with config_path.open("r", encoding="utf-8") as fp:  # Открываем файл в кодировке UTF-8
        data = json.load(fp)  # Парсим JSON и возвращаем список банков
        logger.debug("Load banks config: считаны данные %s", data)  # Показываем прочитанные данные
        return data  # Возвращаем список банков


def build_links_for_transfer(transfer_id: str) -> Tuple[List[dict], List[str]]:  # Генерируем ссылки для всех банков
    logger.debug("Build links: стартуем генерацию для transfer_id %s", transfer_id)  # Сообщаем о старте генерации
    payload = decode_transfer_payload(transfer_id)  # Пытаемся распаковать transfer_id
    logger.debug("Build links: декодированный payload %s", payload)  # Логируем результат декодирования
    inner_payload = payload.get("payload") if isinstance(payload, dict) else {}  # Берём вложенный payload, если он есть
    if not isinstance(inner_payload, dict):  # Если вложенный слой оказался не словарём
        inner_payload = payload if isinstance(payload, dict) else {}  # Используем внешний payload как рабочий
    logger.debug("Build links: внутренний payload для опций %s", inner_payload)  # Фиксируем слой данных для option

    identifier_type, identifier_value = detect_identifier(transfer_id, payload)  # Определяем тип реквизита на полном payload
    logger.debug(
        "Build links: определили идентификатор type=%s value=%s", identifier_type, identifier_value
    )  # Фиксируем тип и значение реквизита

    option = (inner_payload.get("option") if isinstance(inner_payload, dict) else None) or (  # Берём option или inline_option
        inner_payload.get("inline_option") if isinstance(inner_payload, dict) else None
    )  # Это позволит корректно передать сумму/комментарий из новой схемы
    option = option if isinstance(option, dict) else {}  # Гарантируем, что option — словарь даже при странных данных

    banks = load_banks_config()  # Читаем метаданные банков из файла
    logger.debug("Build links: загружено банков %s", len(banks))  # Сообщаем количество банков
    results: List[dict] = []  # Список ответов по банкам
    errors: List[str] = []  # Список ошибок для диагностики

    for bank in banks:  # Перебираем все банки из конфигурации
        bank_id = bank.get("id") or "unknown"  # Забираем id банка
        supported = bank.get("supported_identifiers") or []  # Узнаём поддерживаемые типы реквизитов
        logger.debug(
            "Build links: обрабатываем банк id=%s supported=%s", bank_id, supported
        )  # Подробно логируем параметры банка

        if identifier_type not in supported:  # Если данный банк не умеет обрабатывать тип реквизита
            logger.debug(
                "Build links: банк %s не поддерживает тип %s, пропускаем", bank_id, identifier_type
            )  # Сообщаем о пропуске банка
            continue  # Пропускаем банк

        try:  # Пытаемся собрать ссылки через единый конструктор
            built_links = link_builder.build_links(  # Собираем набор ссылок для банка
                bank_id,  # Идентификатор банка
                identifier_type,  # Тип реквизита (phone/card)
                identifier_value,  # Значение реквизита
                str(option.get("amount") or ""),  # Передаём сумму из корректного option
                str(option.get("comment") or ""),  # Передаём комментарий из корректного option
            )
            logger.debug("Build links: link_builder вернул %s для банка %s", built_links, bank_id)  # Логируем результат
        except Exception as exc:  # Ловим любые неожиданные ошибки конструктора
            logger.warning("WebApp API: ошибка сборки ссылок для %s: %s", bank_id, exc)  # Логируем проблему
            errors.append(f"link_builder failed for {bank_id}")  # Добавляем ошибку
            built_links = {}  # Используем пустой набор ссылок, чтобы не ломать ответ

        token_payload = {  # Собираем payload для токена редиректа
            "bank_id": bank_id,
            "transfer_id": transfer_id,
            "links": built_links,
            "deeplink": built_links.get("deeplink_android") or built_links.get("deeplink_ios") or "",
            "fallback_url": built_links.get("web") or "",
        }
        logger.debug(
            "Build links: формируем токен с payload %s для банка %s", token_payload, bank_id
        )  # Показываем содержимое токена
        token = token_store.issue_token(token_payload)  # Создаём токен и кладём в хранилище
        logger.debug("Build links: выпущен токен %s для банка %s", token, bank_id)  # Логируем созданный токен

        result_item = {  # Формируем итоговый объект для фронтенда
            "bank_id": bank_id,
            "title": bank.get("title", "Банк"),
            "logo": bank.get("logo", ""),
            "notes": bank.get("notes", ""),
            "link_id": bank.get("id", bank_id),
            "link_token": token,
        }
        results.append(result_item)  # Добавляем объект в список результатов
        logger.debug("Build links: итоговая запись для банка %s: %s", bank_id, result_item)  # Фиксируем результат

    return results, errors  # Возвращаем сформированные ссылки и ошибки


class WebAppEventHandler(BaseHTTPRequestHandler):  # Основной обработчик HTTP-запросов
    def _apply_cors_headers(self) -> None:  # Добавляем CORS-заголовки во все ответы
        origin = self.headers.get("Origin") or "*"  # Определяем Origin клиента или ставим * по умолчанию
        self.send_header("Access-Control-Allow-Origin", origin)  # Разрешаем доступ с указанного Origin (или со всех)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")  # Перечисляем разрешённые методы
        self.send_header("Access-Control-Allow-Headers", "Content-Type")  # Разрешаем заголовок Content-Type
        self.send_header("Vary", "Origin")  # Сообщаем кэшу, что ответ зависит от Origin

    def end_headers(self) -> None:  # Переопределяем закрытие заголовков, чтобы всегда добавлять CORS
        self._apply_cors_headers()  # Вставляем CORS перед отправкой заголовков клиенту
        super().end_headers()  # Вызываем стандартную реализацию завершения заголовков

    def _send_json(self, payload: dict, status_code: int = 200) -> None:  # Отправляем JSON-ответ
        logger.debug("HTTP: готовим отправку JSON %s со статусом %s", payload, status_code)  # Логируем ответ перед отправкой
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")  # Сериализуем payload в байты
        self.send_response(status_code)  # Ставим HTTP-статус
        self.send_header("Content-Type", "application/json; charset=utf-8")  # Указываем тип содержимого
        self.send_header("Content-Length", str(len(body)))  # Передаём длину тела
        self.end_headers()  # Закрываем заголовки
        self.wfile.write(body)  # Пишем тело ответа
        logger.debug("HTTP: JSON отправлен, байт=%s", len(body))  # Подтверждаем отправку

    def _read_json_body_with_limit(self, max_bytes: int) -> dict | None:  # Читаем JSON-тело с лимитом размера
        content_length = int(self.headers.get("content-length", 0))  # Узнаём длину тела запроса
        if content_length > max_bytes:  # Если тело больше допустимого лимита
            self.send_response(400)  # Возвращаем 400 Bad Request
            self.end_headers()  # Закрываем заголовки
            logger.info(  # Логируем причину отказа
                "Debug log: тело запроса слишком большое (%s байт > %s)", content_length, max_bytes
            )
            return None  # Сигнализируем, что обработку нужно остановить

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""  # Читаем тело запроса
        if len(raw_body) > max_bytes:  # Дополнительная проверка на случай неверного Content-Length
            self.send_response(400)  # Возвращаем 400 Bad Request
            self.end_headers()  # Закрываем заголовки
            logger.info("Debug log: тело запроса превышает лимит после чтения")  # Логируем нарушение лимита
            return None  # Останавливаем обработку

        try:  # Пробуем распарсить JSON
            payload = json.loads(raw_body.decode("utf-8") or "{}")  # Декодируем строку JSON или пустой объект
            logger.debug("Debug log: распарсили JSON %s", payload)  # Логируем разобранный payload
            return payload  # Возвращаем распарсенный объект
        except json.JSONDecodeError:  # Если JSON некорректный
            self.send_response(400)  # Отдаём 400 Bad Request
            self.end_headers()  # Закрываем заголовки
            logger.info("Debug log: некорректный JSON в теле запроса")  # Фиксируем ошибку формата
            return None  # Останавливаем обработку

    def _handle_debug_log(self) -> None:  # Обрабатываем POST /api/debug/log
        payload = self._read_json_body_with_limit(DEBUG_LOG_MAX_BODY_BYTES)  # Читаем JSON с лимитом 256 КБ
        if payload is None:  # Если чтение завершилось ошибкой
            return  # Уже отправили ответ, выходим
        if not isinstance(payload, dict):  # Проверяем, что пришёл объект
            self.send_response(400)  # Возвращаем 400 Bad Request
            self.end_headers()  # Закрываем заголовки
            logger.info("Debug log: ожидался JSON-объект, получено %s", type(payload))  # Логируем проблему
            return  # Завершаем обработку

        sanitized_payload = sanitize_debug_payload(payload, DEBUG_LOG_MAX_STRING_LENGTH)  # Удаляем initData и режем строки
        logs_dir = ensure_debug_logs_dir()  # Гарантируем наличие папки для логов
        date_tag = datetime.utcnow().strftime("%Y-%m-%d")  # Получаем текущую дату по UTC
        log_path = logs_dir / f"frontend_{date_tag}.jsonl"  # Формируем путь до файла JSONL
        with log_path.open("a", encoding="utf-8") as log_file:  # Открываем файл на дозапись
            log_file.write(json.dumps(sanitized_payload, ensure_ascii=False) + "\n")  # Пишем одну JSON-строку

        self.send_response(202)  # Возвращаем 202 Accepted
        self.end_headers()  # Закрываем заголовки
        logger.info("Debug log: запись сохранена в %s", log_path)  # Сообщаем о сохранении логов

    def do_OPTIONS(self) -> None:  # Отвечаем на preflight-запросы браузера
        self.send_response(204)  # Отдаём статус 204 No Content
        self.send_header("Content-Length", "0")  # Сообщаем, что тела нет
        self.end_headers()  # Закрываем заголовки с включёнными CORS

    def do_POST(self) -> None:  # Обрабатываем POST-запросы
        if self.path == "/api/debug/log":  # Проверяем debug-эндпоинт для логов фронтенда
            return self._handle_debug_log()  # Передаём управление в обработчик debug-лога
        if self.path != "/api/webapp":  # Проверяем путь
            self.send_response(404)  # Если путь неизвестен — отдаём 404
            self.end_headers()  # Закрываем заголовки
            return  # Завершаем обработку

        content_length = int(self.headers.get("content-length", 0))  # Узнаём длину тела запроса
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""  # Читаем тело запроса
        logger.info("WebApp API: POST %s, bytes=%s", self.path, content_length)  # Логируем путь и размер тела
        logger.debug(  # Показываем сырое тело запроса в человекочитаемом виде
            "WebApp API: сырое тело POST %s", humanize_bytes(raw_body)
        )  # Преобразуем байты через humanize_bytes, чтобы избежать \x-выводов

        try:  # Пробуем распарсить JSON
            payload = json.loads(raw_body.decode("utf-8") or "{}")  # Получаем словарь из тела
            logger.debug("WebApp API: распарсили JSON %s", payload)  # Фиксируем разобранный payload
        except json.JSONDecodeError:  # Если JSON некорректный
            self.send_response(400)  # Отдаём 400 Bad Request
            self.end_headers()  # Закрываем заголовки
            logger.info("WebApp API: POST %s завершён с 400 (некорректный JSON)", self.path)  # Фиксируем ошибку формата
            return  # Завершаем обработку

        save_webapp_event(payload)  # Пишем событие в БД (без падения при ошибках)
        logger.debug("WebApp API: событие сохранено в БД %s", payload)  # Подтверждаем сохранение события

        self.send_response(202)  # Возвращаем 202 Accepted
        self.end_headers()  # Закрываем заголовки
        logger.info("WebApp API: POST %s завершён с 202 Accepted", self.path)  # Фиксируем успешный приём события

    def do_GET(self) -> None:  # Обрабатываем GET-запросы
        parsed = urlparse(self.path)  # Разбираем URL
        logger.debug("WebApp API: GET %s разобран в %s", self.path, parsed)  # Логируем структуру URL
        if parsed.path == "/api/links":  # Эндпоинт для получения списка ссылок
            return self._handle_links_list(parsed)  # Передаём управление в отдельный метод
        if parsed.path.startswith("/api/links/"):  # Эндпоинт для получения ссылки по токену
            token = parsed.path.split("/api/links/")[-1]  # Извлекаем токен из пути
            return self._handle_link_token(token)  # Обрабатываем запрос
        if parsed.path == "/api/webapp":  # Пинг-эндпоинт для проверки доступности из браузера
            return self._send_json({"ok": True}, status_code=200)  # Возвращаем успешный ответ

        self.send_response(404)  # Неизвестный путь — 404
        self.end_headers()  # Закрываем заголовки

    def _handle_links_list(self, parsed) -> None:  # Обрабатываем GET /api/links
        query = parse_qs(parsed.query)  # Разбираем query-параметры
        logger.debug("Handle links list: query-параметры %s", query)  # Логируем разобранные параметры
        transfer_id = (query.get("transfer_id") or [""])[0]  # Извлекаем transfer_id
        logger.debug("Handle links list: получен transfer_id %s", transfer_id)  # Сообщаем, что получили transfer_id
        if not transfer_id:  # Если параметр не передан
            return self._send_json({"error": "transfer_id is required"}, status_code=400)  # Возвращаем ошибку

        try:  # Пытаемся построить ссылки
            links, errors = build_links_for_transfer(transfer_id)  # Генерируем deeplink-объекты
            logger.debug("Handle links list: собранные ссылки %s, ошибки %s", links, errors)  # Показываем результат сборки
        except ValueError as exc:  # Если не удалось определить реквизиты
            logger.debug("Handle links list: ошибка валидации %s", exc)  # Логируем ошибку валидации
            return self._send_json({"error": str(exc)}, status_code=400)  # Возвращаем 400 с описанием
        except Exception as exc:  # Если возникла неожиданная ошибка
            logger.warning("WebApp API: внутренний сбой при сборке ссылок %s", exc)  # Логируем проблему
            return self._send_json({"error": "internal_error"}, status_code=500)  # Отдаём 500

        response = {  # Готовим ответ для фронтенда
            "transfer_id": transfer_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "links": links,
            "errors": errors,
        }
        logger.debug("Handle links list: финальный ответ %s", response)  # Показываем сформированный ответ
        return self._send_json(response)  # Отправляем JSON-ответ

    def _handle_link_token(self, token: str) -> None:  # Обрабатываем GET /api/links/{token}
        payload = token_store.get_payload(token)  # Пытаемся найти токен в хранилище
        logger.debug("Handle link token: запрос токена %s вернул %s", token, payload)  # Логируем результат поиска токена
        if not payload:  # Если токен не найден или устарел
            return self._send_json({"error": "token not found"}, status_code=404)  # Возвращаем 404

        return self._send_json(payload)  # Отправляем deeplink и fallback


def run_server() -> None:  # Точка запуска сервера
    host = os.getenv("HOST", "127.0.0.1")  # По умолчанию слушаем localhost для работы за IIS proxy
    port_raw = os.getenv("PORT", "8080")  # Читаем порт из переменной окружения или используем 8080
    try:  # Пытаемся привести порт к числу
        port = int(port_raw)  # Преобразуем порт к int
    except ValueError:  # Если значение не число
        logger.warning("WebApp API: некорректный PORT=%s, используем 8080", port_raw)  # Логируем проблему
        port = 8080  # Переходим на порт по умолчанию
    server = HTTPServer((host, port), WebAppEventHandler)  # Создаём HTTP-сервер на указанном хосте и порту
    logger.info("WebApp API: сервер запущен на http://%s:%s", host, port)  # Сообщаем адрес сервера
    try:  # Запускаем цикл обработки запросов
        server.serve_forever()  # Работаем бесконечно
    except KeyboardInterrupt:  # Корректно завершаем по Ctrl+C
        logger.info("WebApp API: остановка по сигналу клавиатуры")  # Логируем остановку
    finally:  # В любом случае закрываем сервер
        server.server_close()  # Освобождаем порт


if __name__ == "__main__":  # Запуск из командной строки
    run_server()  # Стартуем HTTP-сервер
