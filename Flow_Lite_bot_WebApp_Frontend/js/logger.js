(function (window, document) { // Оборачиваем логгер в IIFE, чтобы не засорять глобальную область имён
  'use strict'; // Включаем строгий режим для предсказуемого поведения

  const MAX_RECORDS = 200; // Максимальное количество записей в буфере
  const SEND_INTERVAL_MS = 3000; // Интервал отправки логов на сервер (3 секунды)
  const MAX_ERROR_BODY_LENGTH = 1500; // Ограничиваем длину тела ошибки в логах
  const DEBUG_LOG_ENDPOINT = '/api/debug/log'; // Относительный путь для отправки логов

  const sessionId = (window.crypto && window.crypto.randomUUID) // Пытаемся использовать крипто-UUID, если доступно
    ? window.crypto.randomUUID() // Генерируем UUID через Web Crypto
    : 'sess-' + Math.random().toString(16).slice(2) + '-' + Date.now().toString(16); // Фолбэк на псевдо-UUID без криптографии

  const recordsBuffer = []; // Буфер логов в памяти
  let flushTimerId = null; // Идентификатор таймера отправки
  let isSending = false; // Флаг, чтобы не отправлять несколько пачек одновременно

  const originalFetch = window.fetch ? window.fetch.bind(window) : null; // Сохраняем оригинальный fetch до обёртки

  function nowIso() { // Получаем текущую дату в ISO-формате
    return new Date().toISOString(); // Возвращаем ISO-строку времени
  } // Завершаем функцию nowIso

  function clampString(value) { // Обрезаем строки до лимита
    if (typeof value !== 'string') { // Если значение не строка
      return value; // Возвращаем как есть
    } // Завершаем ветку проверки типа
    if (value.length <= MAX_ERROR_BODY_LENGTH) { // Если строка короче лимита
      return value; // Возвращаем её без изменений
    } // Завершаем ветку короткой строки
    return value.slice(0, MAX_ERROR_BODY_LENGTH); // Обрезаем строку до лимита
  } // Завершаем функцию clampString

  function pushRecord(level, message, data) { // Добавляем запись в буфер и пишем в консоль
    const record = { // Формируем объект записи
      ts: nowIso(), // Фиксируем время записи
      level: level, // Сохраняем уровень логирования
      message: message, // Сохраняем текст сообщения
      data: data || {} // Кладём дополнительные данные, если они есть
    }; // Завершаем формирование записи

    recordsBuffer.push(record); // Добавляем запись в буфер
    while (recordsBuffer.length > MAX_RECORDS) { // Пока буфер превышает лимит
      recordsBuffer.shift(); // Удаляем самые старые записи
    } // Завершаем контроль лимита буфера

    if (level === 'error' && console && console.error) { // Если это ошибка и есть console.error
      console.error('[PFLogger]', message, data || {}); // Пишем ошибку в консоль
    } else if (level === 'warn' && console && console.warn) { // Если это предупреждение и есть console.warn
      console.warn('[PFLogger]', message, data || {}); // Пишем предупреждение в консоль
    } else if (console && console.log) { // Для всех остальных случаев используем console.log
      console.log('[PFLogger]', message, data || {}); // Пишем сообщение в консоль
    } // Завершаем выбор уровня консоли
  } // Завершаем функцию pushRecord

  function shouldLogApiRequest(urlString) { // Проверяем, нужно ли логировать API-запрос
    if (!urlString) { // Если URL пустой
      return false; // Не логируем
    } // Завершаем ветку пустого URL
    try { // Пробуем привести URL к абсолютному виду
      const absoluteUrl = new URL(urlString, window.location.href); // Создаём абсолютный URL на основе текущего адреса
      if (absoluteUrl.origin !== window.location.origin) { // Если origin отличается от текущего сайта
        return false; // Не логируем внешние адреса
      } // Завершаем проверку origin
      if (!absoluteUrl.pathname.startsWith('/api/')) { // Если путь не начинается с /api/
        return false; // Не логируем нерелевантные запросы
      } // Завершаем проверку префикса /api/
      if (absoluteUrl.pathname === DEBUG_LOG_ENDPOINT) { // Если это собственный эндпоинт логирования
        return false; // Не логируем, чтобы избежать рекурсии
      } // Завершаем проверку debug-эндпоинта
      return true; // Всё хорошо, можно логировать
    } catch (error) { // Если URL разобрать не удалось
      return false; // В сомнительных случаях не логируем
    } // Завершаем обработку ошибок URL
  } // Завершаем функцию shouldLogApiRequest

  function getRequestInfo(resource, options) { // Достаём URL и метод из запроса
    const requestUrl = typeof resource === 'string' ? resource : (resource && resource.url) ? resource.url : ''; // Получаем URL из строки или объекта Request
    const requestMethod = (options && options.method) || (resource && resource.method) || 'GET'; // Вычисляем HTTP-метод с фолбэком на GET
    return { url: requestUrl, method: requestMethod }; // Возвращаем данные запроса
  } // Завершаем функцию getRequestInfo

  function sendLogs(isFinal) { // Отправляем накопленные логи на сервер
    if (isSending) { // Если отправка уже идёт
      return; // Не запускаем ещё одну
    } // Завершаем проверку повторной отправки
    if (!recordsBuffer.length) { // Если буфер пуст
      return; // Нечего отправлять
    } // Завершаем проверку пустого буфера

    const payload = { // Формируем payload для backend
      type: 'frontend_debug_log', // Указываем тип лога
      sessionId: sessionId, // Передаём идентификатор сессии
      page: window.location.pathname, // Сохраняем путь страницы
      records: recordsBuffer.splice(0, recordsBuffer.length) // Забираем все накопленные записи
    }; // Завершаем формирование payload

    const payloadString = JSON.stringify(payload); // Сериализуем payload в строку JSON
    const headers = { 'Content-Type': 'application/json' }; // Готовим заголовки для JSON

    if (isFinal && navigator.sendBeacon) { // Если страница закрывается и есть sendBeacon
      const beaconBody = new Blob([payloadString], { type: 'application/json' }); // Заворачиваем payload в Blob
      const queued = navigator.sendBeacon(DEBUG_LOG_ENDPOINT, beaconBody); // Отправляем через sendBeacon
      if (queued) { // Если браузер принял задачу
        return; // Выходим, чтобы не дублировать запрос
      } // Завершаем проверку отправки через sendBeacon
    } // Завершаем ветку sendBeacon

    if (!originalFetch) { // Если fetch недоступен
      return; // Ничего не отправляем
    } // Завершаем проверку доступности fetch

    isSending = true; // Поднимаем флаг отправки
    originalFetch(DEBUG_LOG_ENDPOINT, { // Отправляем логи на backend через originalFetch
      method: 'POST', // Используем POST
      headers: headers, // Передаём JSON-заголовок
      body: payloadString, // Передаём тело запроса
      keepalive: true // Разрешаем отправку при закрытии вкладки
    }) // Завершаем параметры originalFetch
      .catch(function (error) { // Ловим ошибки сети
        console.debug('PFLogger: не удалось отправить логи', error); // Пишем предупреждение в консоль
        recordsBuffer.unshift.apply(recordsBuffer, payload.records); // Возвращаем записи в буфер, чтобы не потерять
        while (recordsBuffer.length > MAX_RECORDS) { // Если буфер снова стал больше лимита
          recordsBuffer.pop(); // Удаляем самые старые записи с конца
        } // Завершаем подрезку буфера после ошибки отправки
      }) // Завершаем обработку ошибки отправки
      .finally(function () { // В любом случае завершаем отправку
        isSending = false; // Сбрасываем флаг отправки
      }); // Завершаем finally-ветку отправки
  } // Завершаем функцию sendLogs

  function scheduleFlush() { // Планируем периодическую отправку логов
    if (flushTimerId) { // Если таймер уже есть
      return; // Не создаём новый
    } // Завершаем проверку таймера
    flushTimerId = window.setInterval(function () { // Запускаем интервал
      sendLogs(false); // Отправляем логи в фоновом режиме
    }, SEND_INTERVAL_MS); // Указываем интервал 3 секунды
  } // Завершаем функцию scheduleFlush

  const PFLogger = { // Формируем публичный API логгера
    info: function (message, data) { // Публичный метод для информационных логов
      pushRecord('info', message, data); // Добавляем запись в буфер
    }, // Завершаем метод info
    warn: function (message, data) { // Публичный метод для предупреждений
      pushRecord('warn', message, data); // Добавляем запись в буфер
    }, // Завершаем метод warn
    error: function (message, data) { // Публичный метод для ошибок
      pushRecord('error', message, data); // Добавляем запись в буфер
    } // Завершаем метод error
  }; // Завершаем объявление PFLogger

  window.PFLogger = PFLogger; // Экспортируем логгер в глобальный объект

  if (originalFetch) { // Если fetch доступен
    window.fetch = function (resource, options) { // Оборачиваем fetch для логирования
      const requestInfo = getRequestInfo(resource, options); // Забираем URL и метод запроса
      const shouldLog = shouldLogApiRequest(requestInfo.url); // Проверяем, нужно ли логировать запрос

      if (shouldLog) { // Если запрос нужно логировать
        PFLogger.info('api request', { method: requestInfo.method, url: requestInfo.url }); // Логируем отправку запроса
      } // Завершаем ветку логирования запроса

      return originalFetch(resource, options) // Выполняем оригинальный fetch
        .then(function (response) { // Обрабатываем ответ
          if (shouldLog) { // Если запрос логируется
            PFLogger.info('api response', { // Логируем ответ
              method: requestInfo.method, // Пишем метод запроса
              url: requestInfo.url, // Пишем URL запроса
              status: response.status // Сохраняем статус ответа
            }); // Завершаем логирование ответа
            if (!response.ok) { // Если ответ не успешный
              response.clone().text() // Читаем тело ответа
                .then(function (text) { // Получаем текст ответа
                  PFLogger.warn('api response error body', { // Логируем тело ошибки
                    url: requestInfo.url, // Указываем URL запроса
                    status: response.status, // Указываем статус
                    body: clampString(text || '') // Обрезаем тело ошибки
                  }); // Завершаем логирование тела ошибки
                }) // Завершаем обработку чтения тела ошибки
                .catch(function (error) { // Если тело прочитать не удалось
                  PFLogger.warn('api response error body read failed', { // Логируем ошибку чтения тела
                    url: requestInfo.url, // Указываем URL запроса
                    status: response.status, // Указываем статус
                    error: error ? error.message : 'unknown error' // Указываем сообщение ошибки
                  }); // Завершаем логирование ошибки чтения тела
                }); // Завершаем catch чтения тела
            } // Завершаем ветку обработки неуспешного ответа
          } // Завершаем ветку логирования ответа
          return response; // Возвращаем исходный ответ
        }) // Завершаем then-обработчик fetch
        .catch(function (error) { // Обрабатываем сетевые ошибки
          if (shouldLog) { // Если запрос логируется
            PFLogger.error('api request failed', { // Логируем сетевую ошибку
              method: requestInfo.method, // Пишем метод запроса
              url: requestInfo.url, // Пишем URL запроса
              error: error ? error.message : 'unknown error' // Пишем текст ошибки
            }); // Завершаем логирование сетевой ошибки
          } // Завершаем ветку логирования сетевой ошибки
          throw error; // Пробрасываем ошибку дальше
        }); // Завершаем catch-ветку fetch
    }; // Завершаем обёртку fetch
  } // Завершаем ветку наличия fetch

  document.addEventListener('visibilitychange', function () { // Отправляем логи при смене видимости страницы
    if (document.visibilityState === 'hidden') { // Если страница скрывается
      sendLogs(true); // Пробуем отправить логи перед закрытием
    } // Завершаем проверку скрытия страницы
  }); // Завершаем обработчик visibilitychange

  window.addEventListener('beforeunload', function () { // Отправляем логи перед закрытием вкладки
    sendLogs(true); // Пробуем отправить логи перед закрытием
  }); // Завершаем обработчик beforeunload

  scheduleFlush(); // Запускаем периодическую отправку логов
})(window, document); // Передаём глобальные window и document в IIFE
