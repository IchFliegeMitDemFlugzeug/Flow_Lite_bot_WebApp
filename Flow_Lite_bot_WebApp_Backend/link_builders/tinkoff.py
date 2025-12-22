"""Строитель deeplink-ссылок для Т-Банка (бывший Тинькофф)."""

from __future__ import annotations  # Поддерживаем отложенные аннотации для согласованности

import json  # Сериализуем объект predefined
import logging  # Добавляем логирование шагов конструктора
from urllib.parse import quote  # Кодируем JSON параметра predefined в URL

from schemas.link_payload import LinkBuilderRequest, LinkBuilderResult  # Импортируем схемы запросов и ответов

logger = logging.getLogger(__name__)  # Создаём логгер для текущего файла


def build_tinkoff_phone(payload: LinkBuilderRequest) -> LinkBuilderResult:
    """Собирает ссылку на оплату по телефону в Т-Банк."""

    logger.debug("Tinkoff builder: входной payload %s", payload)  # Фиксируем входные данные
    raw_phone = payload.get("identifier_value", "")  # Забираем номер телефона из запроса
    logger.debug("Tinkoff builder: сырой телефон %s", raw_phone)  # Показываем номер до нормализации
    digits_only = "".join(ch for ch in raw_phone if ch.isdigit())  # Убираем пробелы и посторонние символы
    logger.debug("Tinkoff builder: только цифры %s", digits_only)  # Логируем очищенный номер
    normalized_phone = digits_only if digits_only.startswith("7") else "7" + digits_only.lstrip("8")  # Приводим к виду 7XXXXXXX
    logger.debug("Tinkoff builder: нормализованный телефон %s", normalized_phone)  # Показываем итоговый формат телефона
    predefined_json = {"phone": f"+{normalized_phone}"}  # Готовим объект для параметра predefined
    logger.debug("Tinkoff builder: объект predefined %s", predefined_json)  # Логируем объект predefined
    encoded_predefined = quote(json.dumps(predefined_json, ensure_ascii=False))  # Кодируем JSON в URL без потери символов
    logger.debug("Tinkoff builder: закодированный predefined %s", encoded_predefined)  # Показываем кодированный параметр

    deeplink = (
        "https://www.tbank.ru/mybank/payments/persons/phone/"
        "?internal_source=homePayments_transferByPhoneSmall_suggest"
        f"&predefined={encoded_predefined}"
    )  # Строим ссылку, совпадающую с публичным шаблоном
    logger.debug("Tinkoff builder: deeplink %s", deeplink)  # Логируем итоговый deeplink
    fallback_url = deeplink  # Для Т-Банка веб-ссылка совпадает с deeplink и открывается в браузере
    logger.debug("Tinkoff builder: fallback совпадает с deeplink %s", fallback_url)  # Подтверждаем fallback
    link_id = f"tbank:phone:{normalized_phone}"  # Уникальный идентификатор для логов
    logger.debug("Tinkoff builder: link_id %s", link_id)  # Логируем идентификатор ссылки

    return {
        "deeplink": deeplink,  # Deeplink/веб-ссылка на оплату по телефону
        "fallback_url": fallback_url,  # Запасной URL для браузера
        "link_id": link_id,  # Идентификатор ссылки для телеметрии
    }
