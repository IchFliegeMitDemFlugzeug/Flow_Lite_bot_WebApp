"""Тесты для единого конструктора ссылок."""  # Докстрока модуля

import json  # Работаем с JSON в тестовых шаблонах
import tempfile  # Создаём временные каталоги для тестовых файлов
import unittest  # Стандартный модуль тестов
from pathlib import Path  # Работаем с путями к временным файлам

from link_builder.link_builder import LinkBuilder  # Импортируем класс конструктора ссылок
from link_builder.link_builder import LinkBuilderConfig  # Импортируем конфиг для конструктора


class LinkBuilderTests(unittest.TestCase):  # Группа тестов для конструктора ссылок
    def _make_builder(self, phone_banks, card_banks):  # Вспомогательный метод для создания конструктора
        temp_dir = tempfile.TemporaryDirectory()  # Создаём временную папку для JSON-файлов
        phone_path = Path(temp_dir.name) / "links_phone.json"  # Путь до временного файла телефона
        card_path = Path(temp_dir.name) / "links_card.json"  # Путь до временного файла карты

        phone_path.write_text(  # Записываем JSON-шаблоны для телефонов
            json.dumps({"banks": phone_banks}, ensure_ascii=False),  # Сериализуем данные в JSON
            encoding="utf-8",  # Явно задаём кодировку
        )  # Завершаем запись файла
        card_path.write_text(  # Записываем JSON-шаблоны для карт
            json.dumps({"banks": card_banks}, ensure_ascii=False),  # Сериализуем данные в JSON
            encoding="utf-8",  # Явно задаём кодировку
        )  # Завершаем запись файла

        builder = LinkBuilder(LinkBuilderConfig(phone_path, card_path))  # Создаём конструктор из временных файлов
        builder._temp_dir = temp_dir  # Сохраняем ссылку на temp_dir, чтобы он не удалился раньше времени
        return builder  # Возвращаем готовый конструктор

    def test_null_template_returns_none(self):  # Проверяем, что null-шаблон превращается в None
        phone_banks = {  # Подготавливаем тестовый банк
            "demo": {  # Идентификатор банка
                "deeplink_ios": None,  # Deeplink отсутствует
                "web": "https://example.test/{phone.digits11}",  # Веб-ссылка с подстановкой
            }  # Закрываем словарь банка
        }  # Закрываем словарь банков
        builder = self._make_builder(phone_banks, {})  # Создаём конструктор с шаблонами телефона

        result = builder.build_links("demo", "phone", "+7 (999) 888-77-66")  # Собираем ссылки по телефону

        self.assertIn("deeplink_ios", result)  # Убеждаемся, что ключ присутствует
        self.assertIsNone(result["deeplink_ios"])  # Проверяем, что значение None
        self.assertIn("web", result)  # Убеждаемся, что web присутствует
        self.assertIn("79998887766", result["web"])  # Телефон должен быть нормализован

    def test_missing_bank_returns_empty_dict(self):  # Проверяем отсутствие банка в шаблонах
        builder = self._make_builder({}, {})  # Создаём конструктор без шаблонов

        result = builder.build_links("unknown", "phone", "79998887766")  # Пробуем собрать ссылки

        self.assertEqual(result, {})  # Ожидаем пустой словарь без ошибок

    def test_new_link_key_is_preserved(self):  # Проверяем, что новые ключи попадают в результат
        phone_banks = {  # Готовим тестовые шаблоны
            "demo": {  # Идентификатор банка
                "web_alt": "https://example.test/alt/{phone.digits10}",  # Дополнительный ключ ссылки
            }  # Закрываем шаблон банка
        }  # Закрываем словарь банков
        builder = self._make_builder(phone_banks, {})  # Создаём конструктор

        result = builder.build_links("demo", "phone", "+7 (912) 345-67-89")  # Собираем ссылки

        self.assertIn("web_alt", result)  # Новый ключ должен присутствовать
        self.assertEqual(result["web_alt"], "https://example.test/alt/9123456789")  # Проверяем подстановку


if __name__ == '__main__':  # Запуск тестов напрямую
    unittest.main()  # Выполняем тесты
