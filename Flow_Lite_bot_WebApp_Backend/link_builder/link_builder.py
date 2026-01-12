# Единый конструктор ссылок для ПОТОК Lite (вариант A: богатый контекст + строковые шаблоны).  # noqa: E501
#                                                                                                      # noqa: E501
# Этот модуль делает 5 вещей:                                                                          # noqa: E501
# 1) Загружает 2 JSON-файла шаблонов (телефон/карта).                                                   # noqa: E501
# 2) Нормализует входные реквизиты (пробелы/дефисы/скобки не важны).                                    # noqa: E501
# 3) Готовит "богатый контекст" (много готовых представлений телефона/карты).                           # noqa: E501
# 4) Подставляет значения в шаблоны и возвращает готовые ссылки.                                        # noqa: E501
# 5) Работает устойчиво: если у банка шаблон = null или банка нет — не падает.                          # noqa: E501

from __future__ import annotations  # Разрешаем отложенные аннотации типов (удобнее для Python 3.10+).    # noqa: E501

import json  # Нужен для чтения JSON и для подготовки JSON-строки в одном из плейсхолдеров.             # noqa: E501
import re  # Нужен для регулярных выражений (нормализация и поиск плейсхолдеров).                       # noqa: E501
from dataclasses import dataclass  # Удобный контейнер настроек (пути до файлов) без "магии".           # noqa: E501
from pathlib import Path  # Надёжная работа с путями, независимо от ОС и текущей директории запуска.    # noqa: E501
from typing import Any  # Тип "любой" для значений, пришедших из JSON.                                  # noqa: E501
from typing import Dict  # Явный тип "словарь" для контекстов и шаблонов.                               # noqa: E501
from typing import Mapping  # Тип для "любого отображения" (dict/MappingProxy и т.п.).                  # noqa: E501
from typing import Optional  # Тип для значений, которые могут быть None (null).                        # noqa: E501
from urllib.parse import quote  # URL-encoding: экранируем +, пробелы, кириллицу в comment и т.д.       # noqa: E501

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_.-]+)\}")  # Ищем плейсхолдеры вида {phone.digits11}.      # noqa: E501


@dataclass(frozen=True)  # frozen=True: после создания нельзя менять поля (меньше случайных ошибок).     # noqa: E501
class LinkBuilderConfig:  # Конфиг: где лежат JSON-файлы с шаблонами.                                    # noqa: E501
    phone_templates_path: Path  # Путь до links_phone.json.                                              # noqa: E501
    card_templates_path: Path  # Путь до links_card.json.                                                # noqa: E501


class LinkBuilder:  # Основной класс конструктора ссылок.                                                # noqa: E501
    def __init__(self, config: LinkBuilderConfig) -> None:  # Создаём объект и сразу читаем шаблоны.     # noqa: E501
        self._config = config  # Сохраняем конфиг (пути до JSON-файлов).                                 # noqa: E501
        self._phone_templates: Dict[str, Dict[str, Any]] = {}  # bank_id -> dict шаблонов по телефону.   # noqa: E501
        self._card_templates: Dict[str, Dict[str, Any]] = {}  # bank_id -> dict шаблонов по карте.       # noqa: E501
        self.reload()  # Загружаем шаблоны в память (после этого сборка ссылок очень быстрая).           # noqa: E501

    def reload(self) -> None:  # Позволяет "перечитать" JSON, если ты поменял файлы на диске.            # noqa: E501
        self._phone_templates = self._load_templates(self._config.phone_templates_path)  # phone JSON.  # noqa: E501
        self._card_templates = self._load_templates(self._config.card_templates_path)  # card JSON.     # noqa: E501

    def build_links(  # Собираем ссылки для ОДНОГО банка и ОДНОГО типа реквизита.                        # noqa: E501
        self,  # self — текущий экземпляр конструктора.                                                  # noqa: E501
        bank_id: str,  # Идентификатор банка (например, "sber").                                         # noqa: E501
        identifier_type: str,  # Тип реквизита: "phone" или "card".                                      # noqa: E501
        identifier_value: str,  # Значение реквизита: телефон/карта (в любом читабельном виде).          # noqa: E501
        amount: Optional[str] = None,  # Сумма перевода (строкой), может быть None.                      # noqa: E501
        comment: Optional[str] = None,  # Комментарий к переводу, может быть None.                       # noqa: E501
    ) -> Dict[str, Optional[str]]:  # Возвращаем {ключ_ссылки: строка_или_None}.                         # noqa: E501

        if identifier_type == "phone":  # Ветка для телефона.                                            # noqa: E501
            templates_for_bank = self._phone_templates.get(bank_id, {})  # Шаблоны банка (или {}).        # noqa: E501
            ctx = self._build_phone_context(identifier_value, amount, comment)  # Контекст телефона.     # noqa: E501
        elif identifier_type == "card":  # Ветка для карты.                                              # noqa: E501
            templates_for_bank = self._card_templates.get(bank_id, {})  # Шаблоны банка (или {}).         # noqa: E501
            ctx = self._build_card_context(identifier_value, amount, comment)  # Контекст карты.         # noqa: E501
        else:  # Любой другой тип реквизита считаем некорректным.                                        # noqa: E501
            return {}  # Возвращаем пусто, чтобы не падать и не ломать бэкенд.                            # noqa: E501

        result: Dict[str, Optional[str]] = {}  # Итоговые готовые ссылки банка.                          # noqa: E501

        for link_key, template_value in templates_for_bank.items():  # Идём по всем ключам в JSON банка.  # noqa: E501
            if template_value is None:  # Если шаблон = null => ссылки нет.                               # noqa: E501
                result[link_key] = None  # Возвращаем None без ошибок.                                   # noqa: E501
                continue  # Переходим к следующему типу ссылки.                                           # noqa: E501

            if not isinstance(template_value, str):  # Если значение не строка (битый JSON) — fail-soft.  # noqa: E501
                result[link_key] = None  # Считаем, что ссылки нет.                                      # noqa: E501
                continue  # Идём дальше.                                                                 # noqa: E501

            rendered = self._render_template(template_value, ctx)  # Подставляем плейсхолдеры.            # noqa: E501
            result[link_key] = rendered  # Сохраняем готовую строку ссылки.                               # noqa: E501

        return result  # Возвращаем все найденные/собранные ссылки.                                       # noqa: E501

    def _load_templates(self, path: Path) -> Dict[str, Dict[str, Any]]:  # Читаем JSON и берём секцию banks.  # noqa: E501
        if not path.exists():  # Если файла нет — это не фатально (просто нет шаблонов).                 # noqa: E501
            return {}  # Возвращаем пустой словарь.                                                      # noqa: E501

        raw = path.read_text(encoding="utf-8")  # Читаем файл как UTF-8 текст.                           # noqa: E501
        parsed = json.loads(raw)  # Превращаем JSON-строку в Python-объект.                               # noqa: E501

        banks_section = parsed.get("banks", {})  # Берём секцию с банками (или {}).                       # noqa: E501
        if not isinstance(banks_section, dict):  # Если banks не dict — считаем файл битым.               # noqa: E501
            return {}  # Возвращаем пусто, чтобы система не упала.                                        # noqa: E501

        out: Dict[str, Dict[str, Any]] = {}  # Итог: bank_id -> dict шаблонов.                            # noqa: E501

        for bank_id, bank_templates in banks_section.items():  # Перебираем все банки из JSON.            # noqa: E501
            if isinstance(bank_templates, dict):  # Если структура банка корректна.                       # noqa: E501
                out[str(bank_id)] = bank_templates  # Кладём шаблоны как есть (рендеринг позже).          # noqa: E501
            else:  # Если структура банка некорректна.                                                    # noqa: E501
                out[str(bank_id)] = {}  # Подставляем пустой набор, чтобы не падать.                      # noqa: E501

        return out  # Возвращаем шаблоны, готовые для быстрого использования.                              # noqa: E501

    def _render_template(self, template: str, ctx: Mapping[str, str]) -> str:  # Подстановка {key} -> value.  # noqa: E501
        def _replace(match: re.Match[str]) -> str:  # Функция замены одного плейсхолдера.                 # noqa: E501
            key = match.group(1)  # Достаём имя переменной без фигурных скобок.                           # noqa: E501
            return ctx.get(key, "")  # Если ключа нет — возвращаем пустую строку (устойчивость).           # noqa: E501

        return _PLACEHOLDER_RE.sub(_replace, template)  # Заменяем ВСЕ плейсхолдеры за один проход.        # noqa: E501

    def _build_phone_context(self, phone_raw: str, amount: Optional[str], comment: Optional[str]) -> Dict[str, str]:  # noqa: E501
        phone_raw_str = phone_raw or ""  # Защита: если пришла пустота/None — делаем пустую строку.       # noqa: E501
        digits = re.sub(r"\D", "", phone_raw_str)  # Оставляем только цифры (убираем +, пробелы, дефисы).  # noqa: E501

        if len(digits) == 11 and digits.startswith("8"):  # Если номер в виде 8XXXXXXXXXX.               # noqa: E501
            digits = "7" + digits[1:]  # Заменяем 8 на 7, чтобы привести к единому RU-формату.            # noqa: E501

        if len(digits) == 10:  # Если пришли только 10 цифр без кода страны (редко, но поддержим).        # noqa: E501
            digits = "7" + digits  # Превращаем в 11 цифр с 7 в начале.                                  # noqa: E501

        digits11 = digits  # Считаем это базовым представлением "11 цифр" (если меньше — будет короче).  # noqa: E501
        e164 = f"+{digits11}" if digits11 else ""  # Формируем E.164: "+7..." (если вообще есть цифры).  # noqa: E501
        e164_url = quote(e164, safe="") if e164 else ""  # URL-encode: '+' станет '%2B'.                  # noqa: E501
        digits10 = digits11[1:] if len(digits11) >= 11 else ""  # 10 цифр без первой 7 (для некоторых банков).  # noqa: E501

        ctx: Dict[str, str] = {}  # Сюда положим все плейсхолдеры телефона.                               # noqa: E501
        ctx["phone.raw"] = phone_raw_str  # Исходная строка телефона (как пришла).                        # noqa: E501
        ctx["phone.e164"] = e164  # "+7XXXXXXXXXX".                                                      # noqa: E501
        ctx["phone.e164_url"] = e164_url  # "%2B7XXXXXXXXXX".                                            # noqa: E501
        ctx["phone.digits11"] = digits11  # "7XXXXXXXXXX".                                               # noqa: E501
        ctx["phone.digits10"] = digits10  # "XXXXXXXXXX" (без первой 7).                                  # noqa: E501

        for i in range(11):  # Генерируем d1..d11 (по одной цифре).                                       # noqa: E501
            digit = digits11[i] if len(digits11) > i else ""  # Берём цифру или пусто, если номера не хватает.  # noqa: E501
            ctx[f"phone.d{i+1}"] = digit  # Сохраняем "phone.d1" ... "phone.d11".                          # noqa: E501

        amount_str = "" if amount is None else str(amount)  # Сумма в строку (или пусто).                 # noqa: E501
        comment_str = "" if comment is None else str(comment)  # Комментарий в строку (или пусто).         # noqa: E501
        ctx["amount"] = amount_str  # Плейсхолдер суммы.                                                  # noqa: E501
        ctx["amount_url"] = quote(amount_str, safe="") if amount_str else ""  # URL-encoded сумма.        # noqa: E501
        ctx["comment"] = comment_str  # Плейсхолдер комментария.                                          # noqa: E501
        ctx["comment_url"] = quote(comment_str, safe="") if comment_str else ""  # URL-encoded комментарий.  # noqa: E501

        json_phone = json.dumps({"phone": e164}, ensure_ascii=False, separators=(",", ":")) if e164 else ""  # noqa: E501
        ctx["phone.json_phone"] = json_phone  # Компактный JSON вида {"phone":"+7..."}.                    # noqa: E501
        ctx["phone.json_phone_url"] = quote(json_phone, safe="") if json_phone else ""  # URL-encoded JSON.  # noqa: E501

        return ctx  # Возвращаем контекст для подстановки в шаблоны.                                       # noqa: E501

    def _build_card_context(self, card_raw: str, amount: Optional[str], comment: Optional[str]) -> Dict[str, str]:  # noqa: E501
        card_raw_str = card_raw or ""  # Защита от пустоты/None.                                          # noqa: E501
        digits = re.sub(r"\D", "", card_raw_str)  # Оставляем только цифры карты.                           # noqa: E501

        ctx: Dict[str, str] = {}  # Сюда положим все плейсхолдеры карты.                                   # noqa: E501
        ctx["card.raw"] = card_raw_str  # Как пришло.                                                     # noqa: E501
        ctx["card.digits"] = digits  # Только цифры (16–19 обычно).                                        # noqa: E501
        ctx["card.last4"] = digits[-4:] if len(digits) >= 4 else ""  # Последние 4 цифры.                  # noqa: E501

        groups = [digits[i:i + 4] for i in range(0, len(digits), 4)] if digits else []  # Режем по 4.     # noqa: E501
        for idx, g in enumerate(groups, start=1):  # Нумеруем группы с 1, чтобы удобнее ссылаться.        # noqa: E501
            ctx[f"card.g{idx}"] = g  # Плейсхолдеры card.g1, card.g2, ...                                  # noqa: E501

        amount_str = "" if amount is None else str(amount)  # Сумма строкой.                               # noqa: E501
        comment_str = "" if comment is None else str(comment)  # Комментарий строкой.                      # noqa: E501
        ctx["amount"] = amount_str  # Сумма.                                                              # noqa: E501
        ctx["amount_url"] = quote(amount_str, safe="") if amount_str else ""  # URL-encoded сумма.         # noqa: E501
        ctx["comment"] = comment_str  # Комментарий.                                                      # noqa: E501
        ctx["comment_url"] = quote(comment_str, safe="") if comment_str else ""  # URL-encoded комментарий.  # noqa: E501

        return ctx  # Возвращаем контекст карты.                                                           # noqa: E501


def default_link_builder() -> LinkBuilder:  # Фабрика: создаёт LinkBuilder рядом с JSON-файлами.          # noqa: E501
    here = Path(__file__).resolve().parent  # Папка, где лежит этот файл (и рядом лежат JSON-шаблоны).    # noqa: E501
    cfg = LinkBuilderConfig(  # Собираем конфиг путей до шаблонов.                                        # noqa: E501
        phone_templates_path=here / "links_phone.json",  # links_phone.json рядом с модулем.              # noqa: E501
        card_templates_path=here / "links_card.json",  # links_card.json рядом с модулем.                # noqa: E501
    )  # Закрываем конструктор конфигурации.                                                              # noqa: E501
    return LinkBuilder(cfg)  # Возвращаем готовый объект конструктора ссылок.                              # noqa: E501
