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


logging.basicConfig(level=logging.INFO)  # Настраиваем базовый логгер
logger = logging.getLogger(__name__)  # Получаем логгер этого модуля


class LinkTokenStore:  # Простое хранилище токенов deeplink-ссылок с TTL
    def __init__(self, ttl_seconds: int = 300) -> None:  # Конструктор принимает TTL в секундах
        self.ttl_seconds = ttl_seconds  # Сохраняем время жизни токенов
        self._storage: Dict[str, Tuple[float, dict]] = {}  # Словарь token -> (expires_at, payload)

    def issue_token(self, payload: dict) -> str:  # Создаём и запоминаем новый токен
        token = uuid.uuid4().hex  # Генерируем случайный токен
        expires_at = time.time() + self.ttl_seconds  # Считаем время истечения токена
        self._storage[token] = (expires_at, payload)  # Кладём payload вместе с временем истечения
        logger.debug("LinkTokenStore: создан токен %s с истечением %s", token, expires_at)  # Логируем создание токена
        return token  # Возвращаем токен для клиента

    def get_payload(self, token: str) -> dict | None:  # Получаем payload по токену
        record = self._storage.get(token)  # Ищем запись в словаре
        if not record:  # Если записи нет
            return None  # Возвращаем None
        expires_at, payload = record  # Распаковываем запись
        if time.time() > expires_at:  # Если TTL истёк
            logger.debug("LinkTokenStore: токен %s устарел, удаляем", token)  # Сообщаем в лог
            self._storage.pop(token, None)  # Удаляем запись
            return None  # Возвращаем None
        return payload  # Отдаём сохранённый payload


token_store = LinkTokenStore()  # Глобальное хранилище токенов для страницы редиректа

def base64_decode(value: str) -> str:  # Вспомогательная функция для base64url
    import base64  # Импортируем локально, чтобы не засорять глобальные импорты

    decoded_bytes = base64.b64decode(value.encode("utf-8"))  # Декодируем строку в байты
    return decoded_bytes.decode("utf-8")  # Превращаем байты обратно в строку


def decode_transfer_payload(start_param: str) -> dict:  # Раскодируем start_param, чтобы узнать тип реквизита
    if not start_param:  # Если параметр пустой
        return {}  # Возвращаем пустой словарь
    try:  # Пробуем декодировать base64url → JSON
        normalized = start_param.replace("-", "+").replace("_", "/")  # Возвращаем стандартные символы base64
        padding = "=" * ((4 - len(normalized) % 4) % 4)  # Считаем недостающие символы '='
        decoded = json.loads(base64_decode(normalized + padding))  # Превращаем JSON-строку в объект
        return decoded if isinstance(decoded, dict) else {}  # Возвращаем dict, иначе пустой объект
    except Exception as exc:  # Если что-то пошло не так
        logger.debug("WebApp API: не удалось раскодировать transfer_id %s: %s", start_param, exc)  # Логируем проблему
        return {}  # Возвращаем пустой объект


def detect_identifier(transfer_id: str, payload: dict) -> Tuple[str, str]:  # Определяем тип и значение реквизита
    option = payload.get("option") or {}  # Берём опцию из полезной нагрузки
    if "phone" in option:  # Если в опции есть телефон
        return "phone", str(option.get("phone"))  # Возвращаем тип phone и его значение
    if "card" in option:  # Если есть карта
        return "card", str(option.get("card"))  # Возвращаем тип card и значение

    digits_only = "".join(ch for ch in transfer_id if ch.isdigit() or ch == "+")  # Фильтруем transfer_id до цифр
    if len(digits_only) >= 10 and len(digits_only) <= 15:  # Если похоже на телефон
        return "phone", digits_only  # Возвращаем тип phone
    if len(digits_only) >= 16:  # Если похоже на карту
        return "card", digits_only  # Возвращаем тип card

    raise ValueError("Невозможно определить тип идентификатора")  # Сообщаем о невозможности распознать реквизит


def load_banks_config() -> List[dict]:  # Загружаем banks.json из конфигурации
    config_path = Path(__file__).resolve().parent / "config" / "banks.json"  # Формируем путь до файла относительно backend.py
    with config_path.open("r", encoding="utf-8") as fp:  # Открываем файл в кодировке UTF-8
        return json.load(fp)  # Парсим JSON и возвращаем список банков


def build_links_for_transfer(transfer_id: str) -> Tuple[List[dict], List[str]]:  # Генерируем ссылки для всех банков
    payload = decode_transfer_payload(transfer_id)  # Пытаемся распаковать transfer_id
    identifier_type, identifier_value = detect_identifier(transfer_id, payload)  # Определяем тип реквизита

    banks = load_banks_config()  # Читаем метаданные банков из файла
    results: List[dict] = []  # Список ответов по банкам
    errors: List[str] = []  # Список ошибок для диагностики

    for bank in banks:  # Перебираем все банки из конфигурации
        bank_id = bank.get("id") or "unknown"  # Забираем id банка
        close_only = bool(bank.get("close_only"))  # Узнаём, нужно ли только закрывать Mini App без ссылок
        supported = bank.get("supported_identifiers") or []  # Узнаём поддерживаемые типы реквизитов

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
            continue  # Переходим к следующему банку

        if identifier_type not in supported:  # Если данный банк не умеет обрабатывать тип реквизита
            continue  # Пропускаем банк

        builder = get_builder(bank.get("builder", ""))  # Ищем конструктор по имени
        if not builder:  # Если конструктор не найден
            errors.append(f"builder not found for {bank_id}")  # Записываем ошибку
            continue  # Переходим к следующему банку

        request_payload: LinkBuilderRequest = {  # Готовим payload для конструктора
            "identifier_type": identifier_type,
            "identifier_value": identifier_value,
            "amount": str((payload.get("option") or {}).get("amount") or ""),
            "comment": str((payload.get("option") or {}).get("comment") or ""),
            "extra": payload,
        }

        try:  # Пытаемся собрать ссылку
            built = builder(request_payload)  # Вызываем конструктор
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
            continue  # Переходим к следующему банку

        token_payload = {  # Собираем payload для токена редиректа
            "bank_id": bank_id,
            "deeplink": built.get("deeplink") or "",
            "fallback_url": built.get("fallback_url") or "",
            "transfer_id": transfer_id,
        }
        token = token_store.issue_token(token_payload)  # Создаём токен и кладём в хранилище

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
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")  # Сериализуем payload в байты
        self.send_response(status_code)  # Ставим HTTP-статус
        self.send_header("Content-Type", "application/json; charset=utf-8")  # Указываем тип содержимого
        self.send_header("Content-Length", str(len(body)))  # Передаём длину тела
        self.end_headers()  # Закрываем заголовки
        self.wfile.write(body)  # Пишем тело ответа

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

        try:  # Пробуем распарсить JSON
            payload = json.loads(raw_body.decode("utf-8") or "{}")  # Получаем словарь из тела
        except json.JSONDecodeError:  # Если JSON некорректный
            self.send_response(400)  # Отдаём 400 Bad Request
            self.end_headers()  # Закрываем заголовки
            logger.info("WebApp API: POST %s завершён с 400 (некорректный JSON)", self.path)  # Фиксируем ошибку формата
            return  # Завершаем обработку

        save_webapp_event(payload)  # Пишем событие в БД (без падения при ошибках)

        self.send_response(202)  # Возвращаем 202 Accepted
        self.end_headers()  # Закрываем заголовки
        logger.info("WebApp API: POST %s завершён с 202 Accepted", self.path)  # Фиксируем успешный приём события

    def do_GET(self) -> None:  # Обрабатываем GET-запросы
        parsed = urlparse(self.path)  # Разбираем URL
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
        transfer_id = (query.get("transfer_id") or [""])[0]  # Извлекаем transfer_id
        if not transfer_id:  # Если параметр не передан
            return self._send_json({"error": "transfer_id is required"}, status_code=400)  # Возвращаем ошибку

        try:  # Пытаемся построить ссылки
            links, errors = build_links_for_transfer(transfer_id)  # Генерируем deeplink-объекты
        except ValueError as exc:  # Если не удалось определить реквизиты
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
        return self._send_json(response)  # Отправляем JSON-ответ

    def _handle_link_token(self, token: str) -> None:  # Обрабатываем GET /api/links/{token}
        payload = token_store.get_payload(token)  # Пытаемся найти токен в хранилище
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
