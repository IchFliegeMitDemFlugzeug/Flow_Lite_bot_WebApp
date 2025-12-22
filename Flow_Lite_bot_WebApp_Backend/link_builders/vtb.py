"""Строитель deeplink-ссылок для ВТБ."""

from __future__ import annotations  # Включаем отложенные аннотации

import logging  # Добавляем логирование для отслеживания шагов сборки ссылок

from schemas.link_payload import LinkBuilderRequest, LinkBuilderResult  # Импортируем схемы запросов и ответов

logger = logging.getLogger(__name__)  # Готовим логгер модуля


def build_vtb_universal(payload: LinkBuilderRequest) -> LinkBuilderResult:
    """Формирует deeplink и безопасный fallback для ВТБ."""

    logger.debug("VTB builder: входной payload %s", payload)  # Фиксируем входные данные
    identifier_type = payload.get("identifier_type", "")  # Узнаём тип реквизита (phone/card)
    logger.debug("VTB builder: тип реквизита %s", identifier_type)  # Логируем тип реквизита
    identifier_value = payload.get("identifier_value", "")  # Получаем значение реквизита
    logger.debug("VTB builder: исходное значение реквизита %s", identifier_value)  # Показываем значение до очистки
    digits_only = "".join(ch for ch in identifier_value if ch.isdigit())  # Очищаем строку от лишних символов
    logger.debug("VTB builder: только цифры %s", digits_only)  # Логируем очищенный набор цифр

    normalized_digits = digits_only  # Сохраняем очищенные цифры для вставки в ссылку
    deeplink = f"https://online.vtb.ru/i/cell/ppl/{normalized_digits}"  # Используем рабочий deeplink-шаблон ВТБ
    logger.debug("VTB builder: deeplink %s", deeplink)  # Фиксируем итоговый deeplink

    fallback_url = (
        "https://online.vtb.ru/transfers/transferByPhone?isStandaloneScenario=true"
        "&actionType=generalTargetSearch&tab=SWITCH_TO_OP_4808&isForeingNumber=false"
        "&isInternalTargetSearch=false&predefinedValues%5BpredefinedPhoneNumber%5D=%2B7%20916%20079-44-59&stage=INPUT"
    )  # Мягкий fallback, не дающий ошибку в браузерах
    logger.debug("VTB builder: fallback_url %s", fallback_url)  # Логируем fallback URL
    link_id = f"vtb:{identifier_type}:{normalized_digits}"  # Уникальный идентификатор ссылки для логов
    logger.debug("VTB builder: link_id %s", link_id)  # Логируем идентификатор ссылки

    return {
        "deeplink": deeplink,  # Deep link для открытия приложения ВТБ
        "fallback_url": fallback_url,  # Перенаправление в веб при проблемах с deep link
        "link_id": link_id,  # Идентификатор ссылки для телеметрии
    }
