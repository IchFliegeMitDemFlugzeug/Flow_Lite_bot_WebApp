(function (window) { // Изолируем клиент API в IIFE
  const BACKEND_BASE_URL = (window.AppConfig && window.AppConfig.BACKEND_BASE_URL) || 'https://shadow-verification-acm-river.trycloudflare.com'; // Забираем адрес бэкенда из конфигурации или берём дефолтный HTTPS
  const TELEMETRY_URL = `${BACKEND_BASE_URL}/api/webapp`; // Полный путь приёма телеметрии на удалённом сервере
  const LINKS_BASE_URL = `${BACKEND_BASE_URL}/api/links`; // Полный путь для динамических ссылок на удалённом сервере

  function buildPayload(context, eventType, bankId, page, extra) { // Собираем единый объект полезной нагрузки
    const safeContext = context || {}; // Гарантируем наличие объекта контекста
    const transferPayload = safeContext.transferPayload || {}; // Достаём раскодированный пакет из transfer_id
    const inlinePayload = transferPayload.payload || {}; // Внутренние данные о переводе

    const basePayload = { // Структура, общая для всех событий
      transfer_id: safeContext.startParam || (safeContext.initDataUnsafe ? safeContext.initDataUnsafe.start_param : '') || '', // Идентификатор операции/передачи
      transfer_payload: transferPayload, // Полный пакет, который пришёл через start_param
      inline_creator_tg_user_id: inlinePayload.creator_tg_user_id || null, // Кто отправил инлайн-сообщение
      inline_generated_at: inlinePayload.generated_at || '', // Когда сообщение сформировано
      inline_parsed: inlinePayload.parsed || {}, // Распарсенные данные запроса (банк, сумма)
      inline_option: inlinePayload.option || {}, // Конкретный выбранный реквизит
      event_type: eventType, // Имя события, например webapp_open
      ts: new Date().toISOString(), // Метка времени в ISO-формате
      initData: safeContext.initData || '', // Полная строка initData из Telegram
      initDataUnsafe: safeContext.initDataUnsafe || {}, // Детализированные поля initDataUnsafe
      userAgent: navigator.userAgent || '', // User-Agent браузера для диагностики
      language: navigator.language || '', // Текущая локаль браузера
      platform: navigator.platform || '', // Платформа устройства от браузера
      page: page, // На какой странице было событие (miniapp или redirect)
      bank_id: bankId || '', // Идентификатор выбранного банка, если применимо
      link_id: (extra || {}).link_id || '', // Идентификатор собранной ссылки
      link_token: (extra || {}).link_token || '' // Токен ссылки для редиректа
    }; // Завершаем базовый объект
    return Object.assign({}, basePayload, extra || {}); // Объединяем базу с дополнительными полями
  }

  function safePost(jsonBody) { // Отправляем POST-запрос с защитой от ошибок
    if (!TELEMETRY_URL) { // Если URL-заглушка не задан
      console.debug('ApiClient: BASE_URL не указан, пропускаем отправку'); // Сообщаем в debug и выходим
      return; // Прекращаем выполнение
    }
    const payloadString = JSON.stringify(jsonBody || {}); // Безопасно сериализуем данные в строку
    try { // Ловим синхронные исключения
      if (navigator.sendBeacon) { // Если браузер поддерживает надёжную отправку фоновых событий
        const beaconBody = new Blob([payloadString], { type: 'text/plain;charset=UTF-8' }); // Заворачиваем строку в Blob без JSON-заголовка
        const queued = navigator.sendBeacon(TELEMETRY_URL, beaconBody); // Отправляем событие через sendBeacon
        if (queued) { // Если браузер принял задачу в очередь
          return; // Завершаем без дополнительного запроса
        }
      }

      fetch(TELEMETRY_URL, { // Делаем POST на базовый URL в качестве запасного варианта
        method: 'POST', // Используем метод POST
        body: payloadString, // Передаём сериализованную строку без заголовков
        keepalive: true // Разрешаем отправку даже при закрытии страницы
      })
        .then(function () { // Обрабатываем успешный ответ
          return null; // Ничего не делаем с ответом, UI не трогаем
        })
        .catch(function (error) { // Отлавливаем сетевые ошибки
          console.debug('ApiClient: отправка не удалась', error); // Пишем в debug, чтобы не мешать UX
        }); // Завершаем обработку промиса
    } catch (error) { // Ловим исключения при запуске fetch
      console.debug('ApiClient: исключение при отправке', error); // Сообщаем в debug и продолжаем работу
    }
  }

  function sendWebAppOpen(context) { // Публичная функция для события открытия Mini App
    const payload = buildPayload(context, 'webapp_open', '', 'miniapp'); // Собираем полезную нагрузку
    safePost(payload); // Отправляем событие на сервер с защитой
  }

  function sendBankClick(context, bankId, extraMeta) { // Публичная функция для события клика по банку
    const payload = buildPayload(context, 'bank_click', bankId, 'miniapp', extraMeta); // Собираем полезную нагрузку вместе с meta
    safePost(payload); // Отправляем событие
  }

  function sendRedirectEvent(context, bankId, eventType, pageOverride, extraMeta) { // Публичная функция для событий страницы редиректа
    const payload = buildPayload(context, eventType || 'redirect_open', bankId, pageOverride || 'redirect', extraMeta); // Собираем полезную нагрузку
    safePost(payload); // Отправляем событие
  }

  function fetchBankLinks(transferId) { // Получаем динамические ссылки для банков с backend
    const safeId = encodeURIComponent(transferId || ''); // Экранируем transfer_id для URL
    const requestUrl = `${LINKS_BASE_URL}?transfer_id=${safeId}`; // Собираем путь запроса

    return fetch(requestUrl, { method: 'GET', cache: 'no-cache' }) // Запрашиваем список ссылок
      .then(function (response) { // Ждём ответ
        if (!response.ok) { // Если пришла ошибка
          const responseError = new Error('Не удалось получить ссылки банка'); // Готовим ошибку для вызвавшего кода
          responseError.status = response.status; // Сохраняем статус ответа для диагностики
          responseError.statusText = response.statusText; // Сохраняем текст статуса
          responseError.requestUrl = requestUrl; // Сохраняем URL запроса
          throw responseError; // Бросаем исключение, чтобы его обработали выше
        }
        return response.json(); // Парсим тело как JSON
      })
      .then(function (data) { // После парсинга
        return data.links || []; // Возвращаем массив ссылок (или пустой массив)
      })
      .catch(function (error) { // Отлавливаем сетевые и логические ошибки
        const enrichedError = error || new Error('unknown error'); // Страхуемся от отсутствия объекта ошибки
        enrichedError.requestUrl = enrichedError.requestUrl || requestUrl; // Подставляем URL запроса, если его не было
        throw enrichedError; // Пробрасываем ошибку дальше
      });
  }

  function fetchLinkByToken(token) { // Получаем deeplink и fallback по токену
    const requestUrl = `${LINKS_BASE_URL}/${encodeURIComponent(token || '')}`; // Формируем путь запроса

    return fetch(requestUrl, { method: 'GET', cache: 'no-cache' }) // Запрашиваем данные по токену
      .then(function (response) { // Обрабатываем ответ
        if (!response.ok) { // Если код не 2xx
          throw new Error('Не удалось найти токен ссылки'); // Выбрасываем исключение
        }
        return response.json(); // Парсим JSON
      });
  }

  window.ApiClient = { // Экспортируем функции наружу
    sendWebAppOpen: sendWebAppOpen, // Экспорт события открытия Mini App
    sendBankClick: sendBankClick, // Экспорт события клика по банку
    sendRedirectEvent: sendRedirectEvent, // Экспорт событий на странице редиректа
    fetchBankLinks: fetchBankLinks, // Экспорт загрузки динамических ссылок
    fetchLinkByToken: fetchLinkByToken // Экспорт получения deeplink/fallback по токену
  }; // Конец экспорта
})(window); // Передаём window в IIFE
