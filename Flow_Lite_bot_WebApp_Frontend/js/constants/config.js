(function (window, document) { // Изолируем конфиг в IIFE, чтобы не засорять глобальную область
  const DEFAULT_BACKEND_BASE_URL = 'https://shadow-verification-acm-river.trycloudflare.com'; // Базовый HTTPS-адрес по умолчанию

  function readBackendFromWindow() { // Пробуем взять адрес из window.__BACKEND_BASE_URL__
    const rawValue = (window.__BACKEND_BASE_URL__ || '').toString(); // Приводим значение к строке, даже если оно не строковое
    const trimmed = rawValue.trim(); // Обрезаем пробелы для чистоты значения
    return trimmed; // Возвращаем подготовленную строку (или пустую)
  }

  function readBackendFromMeta() { // Пробуем прочитать адрес из meta-тега
    const metaTag = document.querySelector('meta[name="backend-base-url"]'); // Ищем meta с именем backend-base-url
    if (!metaTag) { // Если meta не найдена
      return ''; // Возвращаем пустую строку
    }
    const metaContent = (metaTag.getAttribute('content') || '').trim(); // Получаем значение content и обрезаем пробелы
    return metaContent; // Возвращаем прочитанное значение
  }

  function resolveBackendBaseUrl() { // Определяем итоговый базовый адрес бэкенда
    const fromWindow = readBackendFromWindow(); // Берём значение из window приоритетно
    if (fromWindow) { // Если значение найдено и непустое
      return fromWindow; // Используем его
    }

    const fromMeta = readBackendFromMeta(); // Иначе пробуем прочитать meta-тег
    if (fromMeta) { // Если meta содержит адрес
      return fromMeta; // Используем его
    }

    return DEFAULT_BACKEND_BASE_URL; // В противном случае возвращаем дефолтный HTTPS-туннель
  }

  const resolvedBackendBaseUrl = resolveBackendBaseUrl(); // Считаем итоговый адрес один раз

  window.AppConfig = window.AppConfig || {}; // Создаём пространство имён конфигурации, если его нет
  window.AppConfig.BACKEND_BASE_URL = resolvedBackendBaseUrl; // Экспортируем базовый адрес для остальных модулей
})(window, document); // Передаём window и document в IIFE
