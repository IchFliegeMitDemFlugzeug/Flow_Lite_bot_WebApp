(function (window) { // Оборачиваем код в IIFE, чтобы не засорять глобальную область имён
  const telegramApi = window.Telegram ? window.Telegram.WebApp : undefined; // Аккуратно берём объект Telegram WebApp, если он есть

  if (telegramApi) { // Если скрипт выполняется внутри Telegram Mini App
    try { // Пытаемся уведомить Telegram, что интерфейс готов
      telegramApi.ready(); // Сообщаем Telegram о готовности страницы
      telegramApi.expand(); // Просим раскрыть Mini App на всю доступную высоту
    } catch (error) { // Если готовность вызвать не удалось
      console.debug('TelegramBridge: ошибка готовности', error); // Выводим диагностическое сообщение в консоль
    }
  }

  function decodeTransferPayload(startParam) { // Аккуратно раскодируем transfer_id в объект
    if (!startParam) { // Если параметра нет
      return {}; // Возвращаем пустой объект
    }

    try { // Пытаемся раскодировать base64url → JSON
      const normalized = startParam.replace(/-/g, '+').replace(/_/g, '/'); // Возвращаем стандартные символы base64
      const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4); // Добавляем недостающие "=" для корректной декодировки
      const json = atob(padded); // Декодируем в строку JSON
      const parsed = JSON.parse(json); // Парсим строку в объект
      return parsed && typeof parsed === 'object' ? parsed : {}; // Возвращаем объект, если всё хорошо
    } catch (error) { // Если что-то пошло не так
      console.debug('TelegramBridge: не удалось раскодировать transfer_id', error); // Пишем диагностическое сообщение
      return {}; // Возвращаем пустой объект, чтобы приложение не падало
    }
  }

  function getTelegramContext() { // Функция собирает все данные окружения Telegram
    const initData = telegramApi ? telegramApi.initData || '' : ''; // Строка подписи initData из объекта Telegram
    const initDataUnsafe = telegramApi ? telegramApi.initDataUnsafe || {} : {}; // Безопасный объект initDataUnsafe с деталями
    const user = initDataUnsafe && initDataUnsafe.user ? initDataUnsafe.user : undefined; // Пользователь, если Telegram его передал
    const startParam = telegramApi && telegramApi.startParam ? telegramApi.startParam : initDataUnsafe.start_param; // Стартовый параметр или transfer_id
    const hasTelegramWebApp = Boolean(telegramApi); // Фиксируем наличие Telegram.WebApp в окружении
    const initDataLen = initData ? initData.length : 0; // Считаем длину initData, не сохраняя саму строку
    const initUnsafeKeys = Object.keys(initDataUnsafe || {}); // Берём список ключей initDataUnsafe для диагностики
    const href = window.location.href; // Сохраняем текущий URL страницы
    if (window.PFLogger && window.PFLogger.info) { // Проверяем, что логгер доступен
      window.PFLogger.info('telegram context', { // Отправляем безопасные данные контекста
        hasTelegramWebApp: hasTelegramWebApp, // Показываем, есть ли Telegram.WebApp
        startParam: startParam, // Логируем startParam без изменения
        initDataLen: initDataLen, // Логируем длину initData
        initUnsafeKeys: initUnsafeKeys, // Логируем ключи initDataUnsafe
        href: href // Логируем URL страницы
      }); // Завершаем логирование контекста
    } // Завершаем проверку наличия логгера
    const transferPayload = decodeTransferPayload(startParam); // Пытаемся извлечь полезную нагрузку из transfer_id
    const platform = telegramApi && telegramApi.platform ? telegramApi.platform : 'browser'; // Платформа, полученная из Telegram
    const version = telegramApi && telegramApi.version ? telegramApi.version : 'unknown'; // Версия Telegram WebApp
    const colorScheme = telegramApi && telegramApi.colorScheme ? telegramApi.colorScheme : 'light'; // Текущая цветовая схема Telegram
    const themeParams = telegramApi && telegramApi.themeParams ? telegramApi.themeParams : {}; // Объект с темой оформления

    return { // Возвращаем собранный объект контекста
      initData: initData, // Сырая строка initData
      initDataUnsafe: initDataUnsafe, // Объект initDataUnsafe с деталями
      user: user, // Пользовательские данные
      startParam: startParam, // Стартовый параметр/transfer_id
      transferPayload: transferPayload, // Полезная нагрузка, которая была упакована в start_param
      platform: platform, // Платформа, которую сообщает Telegram
      version: version, // Версия Telegram WebApp
      colorScheme: colorScheme, // Цветовая схема
      themeParams: themeParams // Параметры темы
    }; // Конец объекта контекста
  }

  function closeMiniApp() { // Функция аккуратно закрывает Mini App или возвращает пользователя назад
    if (telegramApi) { // Если работаем внутри Telegram
      telegramApi.close(); // Закрываем Mini App через API Telegram
      return; // Прерываем дальнейшее выполнение
    }
    window.history.back(); // В браузере без Telegram просто возвращаемся назад
  }

  function openExternalLink(url) { // Открываем ссылку во внешнем браузере или новой вкладке
    if (!url) { // Если URL не передан
      return; // Ничего не делаем
    }
    const targetUrl = url.toString ? url.toString() : String(url); // Аккуратно приводим значение к строке

    try { // Пробуем использовать API Telegram, если оно доступно
      if (telegramApi && typeof telegramApi.openLink === 'function') { // Проверяем наличие метода openLink
        telegramApi.openLink(targetUrl, { try_instant_view: false }); // Открываем ссылку без Instant View, чтобы выйти из WebView
        return; // Завершаем выполнение после успешного вызова Telegram API
      }
    } catch (error) { // Если вызов Telegram API завершился ошибкой
      console.debug('TelegramBridge: не удалось открыть ссылку через Telegram API', error); // Пишем диагностическое сообщение
    }

    try { // Пробуем открыть ссылку стандартными средствами браузера
      const newWindow = window.open(targetUrl, '_blank'); // Пытаемся открыть в новой вкладке
      if (!newWindow) { // Если браузер заблокировал pop-up
        window.location.href = targetUrl; // Навигируем в текущей вкладке как запасной вариант
      }
    } catch (error) { // Если даже window.open выбросил исключение
      console.debug('TelegramBridge: не удалось открыть ссылку в браузере, пробуем навигацию', error); // Логируем проблему
      window.location.href = targetUrl; // Переходим на ссылку в текущем окне как последний шанс
    }
  }

  window.TelegramBridge = { // Экспортируем функции в глобальный объект
    getTelegramContext: getTelegramContext, // Делаем доступной функцию получения контекста
    closeMiniApp: closeMiniApp, // Делаем доступной функцию закрытия Mini App
    openExternalLink: openExternalLink // Экспортируем функцию открытия внешней ссылки
  }; // Конец экспорта
})(window); // Передаём глобальный объект window внутрь IIFE
