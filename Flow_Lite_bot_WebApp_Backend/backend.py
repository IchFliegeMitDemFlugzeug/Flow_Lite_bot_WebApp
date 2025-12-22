"""Простой HTTP-сервер для Mini App с динамической генерацией банковских ссылок."""

from __future__ import annotations  # Включаем отложенные аннотации для читаемости

import json  # Работаем с JSON-телами запросов и ответов
import logging  # Логируем ошибки и служебные события
import sys  # Настраиваем sys.path для запуска из разных директорий
import time  # Используем unix-время для TTL токенов
import uuid  # Генерируем уникальные токены ссылок
from datetime import datetime  # Создаём человекочитаемые метки времени
from http.server import BaseHTTPRequestHandler, HTTPServer  # Минимальный HTTP-сервер из стандартной библиотеки
from pathlib import Path  # Работаем с путями до конфигураций
from typing import Dict, List, Tuple  # Типизация для читаемости кода
from urllib.parse import parse_qs, urlparse  # Разбираем URL и query-параметры

backend_root = Path(__file__).resolve().parent  # Абсолютный путь до каталога backend
if str(backend_root) not in sys.path:  # Убеждаемся, что каталог в sys.path
    sys.path.insert(0, str(backend_root))  # Добавляем путь, чтобы локальные модули находились

from db import save_webapp_event  # Импортируем запись событий в БД из локального модуля
from link_builders import get_builder  # Подключаем реестр конструкторов deeplink-ссылок
from schemas.link_payload import LinkBuilderRequest  # Тип запроса к конструктору ссылок


logging.basicConfig(  # Настраиваем базовый логгер с подробным форматом
    level=logging.INFO,  # Ставим уровень DEBUG, чтобы видеть каждый шаг
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",  # Подробный формат сообщений
    datefmt="%Y-%m-%d %H:%M:%S",  # Формат даты для удобства чтения
)  # Закрываем конфигурацию базового логгера
logger = logging.getLogger(__name__)  # Получаем логгер этого модуля


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
        close_only = bool(bank.get("close_only"))  # Узнаём, нужно ли только закрывать Mini App без ссылок
        supported = bank.get("supported_identifiers") or []  # Узнаём поддерживаемые типы реквизитов
        logger.debug(
            "Build links: обрабатываем банк id=%s close_only=%s supported=%s", bank_id, close_only, supported
        )  # Подробно логируем параметры банка

        if close_only:  # Если банк пока работает как заглушка
            results.append(  # Сразу добавляем его в итоговый список
                {
                    "bank_id": bank_id,  # Возвращаем id банка
                    "title": bank.get("title", "Банк"),  # Название для кнопки
                    "logo": bank.get("logo", ""),  # Путь к логотипу
                    "notes": bank.get("notes", ""),  # Дополнительное описание
                    "close_only": True,  # Флаг для фронта, что нужно просто закрыть Mini App
                    "link_id": bank.get("id", bank_id),  # Устанавливаем link_id для логирования
                    "link_token": "",  # Токен пустой, так как редирект не нужен
                    "deeplink": "",  # Deeplink отсутствует
                    "fallback_url": "",  # Fallback тоже отсутствует
                }
            )
            logger.debug("Build links: банк %s работает в режиме close_only", bank_id)  # Сообщаем о режиме заглушки
            continue  # Переходим к следующему банку

        if identifier_type not in supported:  # Если данный банк не умеет обрабатывать тип реквизита
            logger.debug(
                "Build links: банк %s не поддерживает тип %s, пропускаем", bank_id, identifier_type
            )  # Сообщаем о пропуске банка
            continue  # Пропускаем банк

        builder = get_builder(bank.get("builder", ""))  # Ищем конструктор по имени
        if not builder:  # Если конструктор не найден
            logger.debug("Build links: конструктор для банка %s не найден", bank_id)  # Логируем отсутствие конструктора
            errors.append(f"builder not found for {bank_id}")  # Записываем ошибку
            continue  # Переходим к следующему банку

        request_payload: LinkBuilderRequest = {  # Готовим payload для конструктора
            "identifier_type": identifier_type,
            "identifier_value": identifier_value,
            "amount": str(option.get("amount") or ""),  # Передаём сумму из корректного option
            "comment": str(option.get("comment") or ""),  # Передаём комментарий из корректного option
            "extra": payload,
        }
        logger.debug(
            "Build links: подготовили payload %s для банка %s", request_payload, bank_id
        )  # Показываем запрос в конструктор

        try:  # Пытаемся собрать ссылку
            built = builder(request_payload)  # Вызываем конструктор
            logger.debug("Build links: конструктор %s вернул %s", builder.__name__, built)  # Логируем результат конструктора
        except Exception as exc:  # Ловим любые ошибки конструктора
            logger.warning("WebApp API: ошибка сборки ссылки для %s: %s", bank_id, exc)  # Логируем проблему
            errors.append(f"builder failed for {bank_id}")  # Добавляем ошибку
            fallback_payload = {  # Готовим безопасный fallback с пустым deeplink
                "bank_id": bank_id,
                "title": bank.get("title", "Банк"),
                "logo": bank.get("logo", ""),
                "notes": bank.get("notes", ""),
                "deeplink": "",
                "fallback_url": "https://www.google.com",
                "link_id": f"fallback:{bank_id}",
                "link_token": token_store.issue_token(
                    {
                        "bank_id": bank_id,
                        "deeplink": "",
                        "fallback_url": "https://www.google.com",
                        "transfer_id": transfer_id,
                    }
                ),
            }
            results.append(fallback_payload)  # Добавляем fallback в список
            logger.debug("Build links: добавлен fallback %s для банка %s", fallback_payload, bank_id)  # Логируем fallback
            continue  # Переходим к следующему банку

        token_payload = {  # Собираем payload для токена редиректа
            "bank_id": bank_id,
            "deeplink": built.get("deeplink") or "",
            "fallback_url": built.get("fallback_url") or "",
            "transfer_id": transfer_id,
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
            "link_id": built.get("link_id", bank_id),
            "link_token": token,
            "deeplink": built.get("deeplink", ""),
            "fallback_url": built.get("fallback_url", ""),
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

    def do_OPTIONS(self) -> None:  # Отвечаем на preflight-запросы браузера
        self.send_response(204)  # Отдаём статус 204 No Content
        self.send_header("Content-Length", "0")  # Сообщаем, что тела нет
        self.end_headers()  # Закрываем заголовки с включёнными CORS

    def do_POST(self) -> None:  # Обрабатываем POST-запросы
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
    server = HTTPServer(("0.0.0.0", 8080), WebAppEventHandler)  # Создаём HTTP-сервер на 8080 порту
    logger.info("WebApp API: сервер запущен на http://0.0.0.0:8080")  # Сообщаем адрес сервера
    try:  # Запускаем цикл обработки запросов
        server.serve_forever()  # Работаем бесконечно
    except KeyboardInterrupt:  # Корректно завершаем по Ctrl+C
        logger.info("WebApp API: остановка по сигналу клавиатуры")  # Логируем остановку
    finally:  # В любом случае закрываем сервер
        server.server_close()  # Освобождаем порт


if __name__ == "__main__":  # Запуск из командной строки
    run_server()  # Стартуем HTTP-сервер
