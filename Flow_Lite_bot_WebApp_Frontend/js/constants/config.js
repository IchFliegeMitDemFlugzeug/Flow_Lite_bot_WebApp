(function (window, document) { // Изолируем конфиг в IIFE, чтобы не засорять глобальную область
  const DEFAULT_BACKEND_BASE_URL = 'https://shadow-verification-acm-river.trycloudflare.com'; // Базовый HTTPS-адрес по умолчанию
  const repoPrefix = '/Flow_Lite_bot_WebApp/'; // Жёстко задаём имя репозитория, чтобы GitHub Pages всегда отдавал правильный путь
  const DEFAULT_REDIRECT_BASE_URL = (window.location && window.location.origin ? window.location.origin : '') + repoPrefix + 'redirect/'; // Базовый адрес страницы редиректа, учитывающий вложенность сайта

  function readBackendFromWindow() { // Пробуем взять адрес из window.__BACKEND_BASE_URL__
    const rawValue = (window.__BACKEND_BASE_URL__ || '').toString(); // Приводим значение к строке, даже если оно не строковое
    const trimmed = rawValue.trim(); // Обрезаем пробелы для чистоты значения
    return trimmed; // Возвращаем подготовленную строку (или пустую)
  }

  function readRedirectFromWindow() { // Пробуем взять адрес редиректа из window.__REDIRECT_BASE_URL__
    const rawValue = (window.__REDIRECT_BASE_URL__ || '').toString(); // Приводим значение к строке, чтобы избежать ошибок типов
    const trimmed = rawValue.trim(); // Обрезаем пробелы по краям
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

  function readRedirectFromMeta() { // Пробуем прочитать адрес страницы редиректа из meta-тега
    const metaTag = document.querySelector('meta[name="redirect-base-url"]'); // Ищем meta с именем redirect-base-url
    if (!metaTag) { // Если meta не нашлась
      return ''; // Возвращаем пустую строку
    }
    const metaContent = (metaTag.getAttribute('content') || '').trim(); // Извлекаем значение атрибута content
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

  function resolveRedirectBaseUrl() { // Определяем итоговый базовый адрес страницы редиректа
    const fromWindow = readRedirectFromWindow(); // Пробуем взять значение из window
    if (fromWindow) { // Если адрес найден и не пустой
      return fromWindow; // Используем его
    }

    const fromMeta = readRedirectFromMeta(); // Иначе читаем meta-тег
    if (fromMeta) { // Если meta содержит значение
      return fromMeta; // Возвращаем его
    }

    return DEFAULT_REDIRECT_BASE_URL; // В остальных случаях используем дефолт от origin + /redirect/
  }

  const resolvedBackendBaseUrl = resolveBackendBaseUrl(); // Считаем итоговый адрес один раз
  const resolvedRedirectBaseUrl = resolveRedirectBaseUrl(); // Считаем итоговый адрес редиректа один раз

  window.AppConfig = window.AppConfig || {}; // Создаём пространство имён конфигурации, если его нет
  window.AppConfig.BACKEND_BASE_URL = resolvedBackendBaseUrl; // Экспортируем базовый адрес для остальных модулей
  window.AppConfig.REDIRECT_BASE_URL = resolvedRedirectBaseUrl; // Экспортируем адрес страницы редиректа для Mini App
})(window, document); // Передаём window и document в IIFE
