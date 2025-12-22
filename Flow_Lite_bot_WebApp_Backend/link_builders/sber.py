"""Строитель deeplink-ссылок для Сбербанка.

На основе переданного идентификатора собираем рабочую ссылку формата
`https://www.sberbank.com/sms/pbpn?requisiteNumber=<значение>`, которая
подходит и для номера телефона, и для номера карты. Fallback совпадает
с deeplink, поэтому пользователь всегда откроет корректную страницу.
"""

from __future__ import annotations  # Включаем отложенные аннотации для читаемости

import logging  # Подключаем логирование для пошаговой отладки

from schemas.link_payload import LinkBuilderRequest, LinkBuilderResult  # Импортируем типы запросов и ответов

logger = logging.getLogger(__name__)  # Готовим логгер модуля


def build_sber_universal(payload: LinkBuilderRequest) -> LinkBuilderResult:
    """Собирает ссылку для Сбера по телефону или карте."""

    logger.debug("Sber builder: входной payload %s", payload)  # Фиксируем входные данные конструктора
    raw_value = payload.get("identifier_value", "")  # Берём исходное значение реквизита
    logger.debug("Sber builder: исходное значение реквизита %s", raw_value)  # Показываем значение до очистки
    digits_only = "".join(ch for ch in raw_value if ch.isdigit())  # Оставляем только цифры
    logger.debug("Sber builder: очищенное значение %s", digits_only)  # Логируем очищенный реквизит
    normalized_value = digits_only  # Сохраняем очищенное значение как единый формат для ссылки

    deeplink = (
        f"https://www.sberbank.com/sms/pbpn?requisiteNumber={normalized_value}"
    )  # Формируем ссылку с параметром requisitNumber
    logger.debug("Sber builder: сформированный deeplink %s", deeplink)  # Логируем сформированный deeplink
    fallback_url = deeplink  # Fallback совпадает с deeplink и работает в браузере
    logger.debug("Sber builder: fallback совпадает с deeplink %s", fallback_url)  # Подтверждаем fallback
    link_id = f"sber:{payload.get('identifier_type', 'unknown')}:{normalized_value}"  # Уникальный идентификатор для телеметрии
    logger.debug("Sber builder: итоговый link_id %s", link_id)  # Логируем идентификатор ссылки

    return {
        "deeplink": deeplink,  # Deep link/веб-ссылка Сбера
        "fallback_url": fallback_url,  # Запасной URL при проблемах с deep link
        "link_id": link_id,  # Идентификатор ссылки для логов
    }
