(function (window) { // Изолируем загрузчик банков в IIFE
  const LOCAL_BANKS = [ // Встроенный список, который рендерится мгновенно без ожидания сети
    { // Первый банк в списке
      id: 'sber', // Идентификатор банка для логики
      title: 'Сбербанк', // Читаемое название банка
      logo: 'assets/img/banks/sber.png', // Путь до PNG-логотипа
      supported_identifiers: ['phone', 'card'], // Что умеет сборщик ссылок
      builder: 'sber_universal', // Имя билдера на бэкенде
      notes: 'Перевод по номеру телефона или карты через Сбербанк' // Пояснение для отладки
    },
    { // Второй банк
      id: 'tbank', // Идентификатор банка
      title: 'Т-Банк', // Название на кнопке
      logo: 'assets/img/banks/tbank.png', // PNG-логотип
      supported_identifiers: ['phone'], // Какие реквизиты поддерживаются
      builder: 'tinkoff_phone', // Имя билдера ссылок
      notes: 'Оплата по номеру телефона в Т-Банк' // Комментарий
    },
    { // Третий банк
      id: 'vtb', // Идентификатор банка
      title: 'ВТБ', // Название
      logo: 'assets/img/banks/vtb.png', // Путь до логотипа
      supported_identifiers: ['phone', 'card'], // Доступные реквизиты
      builder: 'vtb_universal', // Имя билдера
      notes: 'Универсальные ссылки для перевода в ВТБ' // Комментарий для отладки
    },
    { // Заглушка Альфа-Банк
      id: 'alfabank', // Идентификатор банка
      title: 'Альфа-Банк', // Название
      logo: 'assets/img/banks/alfabank.png', // Логотип PNG
      supported_identifiers: ['phone', 'card'], // Доступные реквизиты
      notes: 'Заглушка: просто закрываем мини-апп' // Комментарий
    },
    { // Заглушка РСХБ
      id: 'rshb', // Идентификатор банка
      title: 'Россельхозбанк', // Название
      logo: 'assets/img/banks/rshb.png', // Логотип
      supported_identifiers: ['phone', 'card'], // Доступные реквизиты
      notes: 'Заглушка: просто закрываем мини-апп' // Комментарий
    },
    { // Заглушка Газпромбанк
      id: 'gazprombank', // Идентификатор банка
      title: 'Газпромбанк', // Название
      logo: 'assets/img/banks/gazprombank.png', // Логотип
      supported_identifiers: ['phone', 'card'], // Доступные реквизиты
      notes: 'Заглушка: просто закрываем мини-апп' // Комментарий
    },
    { // Заглушка ПСБ
      id: 'psb', // Идентификатор банка
      title: 'ПСБ', // Название
      logo: 'assets/img/banks/psb.png', // Логотип
      supported_identifiers: ['phone', 'card'], // Доступные реквизиты
      notes: 'Заглушка: просто закрываем мини-апп' // Комментарий
    },
    { // Заглушка МКБ
      id: 'mkb', // Идентификатор банка
      title: 'МКБ', // Название
      logo: 'assets/img/banks/mkb.png', // Логотип
      supported_identifiers: ['phone', 'card'], // Доступные реквизиты
      notes: 'Заглушка: просто закрываем мини-апп' // Комментарий
    },
    { // Заглушка МТС
      id: 'mtsbank', // Идентификатор банка
      title: 'МТС Банк', // Название
      logo: 'assets/img/banks/mtsbank.png', // Логотип
      supported_identifiers: ['phone', 'card'], // Доступные реквизиты
      notes: 'Заглушка: просто закрываем мини-апп' // Комментарий
    },
    { // Заглушка Почта Банк
      id: 'pochtabank', // Идентификатор банка
      title: 'Почта Банк', // Название
      logo: 'assets/img/banks/pochtabank.png', // Логотип
      supported_identifiers: ['phone', 'card'], // Доступные реквизиты
      notes: 'Заглушка: просто закрываем мини-апп' // Комментарий
    },
    { // Заглушка Совкомбанк
      id: 'sovcombank', // Идентификатор банка
      title: 'Совкомбанк', // Название
      logo: 'assets/img/banks/sovcombank.png', // Логотип
      supported_identifiers: ['phone', 'card'], // Доступные реквизиты
      notes: 'Заглушка: просто закрываем мини-апп' // Комментарий
    }
  ]; // Завершаем встроенный массив

  const ASSETS_VERSION = (window.AppConfig && window.AppConfig.APP_ASSETS_VERSION) || (window.APP_ASSETS_VERSION || ''); // Версия ассетов для пробивки кэша
  let banksCache = null; // Последний удачный список банков для повторного использования

  function cloneBanks(list) { // Делает поверхностную копию массива банков
    return list.map(function (bank) { // Перебираем входной массив
      return Object.assign({}, bank); // Возвращаем новый объект, чтобы не портить исходные данные
    }); // Завершаем map
  }

  function buildConfigUrl() { // Собирает полный URL до banks.json с версией
    const basePath = window.location.pathname.includes('/redirect/') ? '../config/banks.json' : './config/banks.json'; // Подбираем относительный путь от страницы
    const versionSuffix = ASSETS_VERSION ? `?v=${ASSETS_VERSION}` : ''; // Добавляем версию для обновления кэша
    const requestUrl = new URL(basePath + versionSuffix, window.location.href); // Строим абсолютный адрес
    return requestUrl.toString(); // Возвращаем готовую строку
  }

  function refreshBanksInBackground() { // Обновляет banks.json в кэше, не блокируя первый кадр
    requestAnimationFrame(function () { // Ждём, пока браузер нарисует стартовый кадр
      setTimeout(function () { // Переносим сетевой запрос в конец очереди событий
        const requestUrl = buildConfigUrl(); // Получаем полный URL файла конфигурации
        fetch(requestUrl) // Читаем banks.json из кэша браузера
          .then(function (response) { // Обрабатываем ответ сервера
            if (!response.ok) { // Проверяем код ответа
              throw new Error('Не удалось обновить список банков из banks.json'); // Бросаем ошибку для блока catch
            } // Завершаем проверку статуса
            return response.json(); // Парсим тело как JSON
          }) // Завершаем then с json
          .then(function (freshBanks) { // Когда JSON успешно распарсен
            banksCache = cloneBanks(freshBanks || LOCAL_BANKS); // Обновляем кэш новым списком или оставляем встроенный
          }) // Завершаем успешное обновление кэша
          .catch(function (error) { // Любая ошибка при запросе или парсинге
            console.debug('BankLoader: не удалось обновить banks.json, работаем из встроенных данных', error); // Сообщаем в debug, но не блокируем UI
          }); // Завершаем цепочку запроса
      }, 0); // Мгновенная задача после первого кадра
    }); // Завершаем requestAnimationFrame
  }

  function loadBanks() { // Публичная функция загрузки списка банков
    if (!banksCache) { // Проверяем, не заполняли ли кэш ранее
      banksCache = cloneBanks(LOCAL_BANKS); // Кладём встроенный список, чтобы сразу отрисовать UI
      refreshBanksInBackground(); // Параллельно пробуем обновить данные с диска
    } // Завершаем блок первичной инициализации

    return Promise.resolve(cloneBanks(banksCache)); // Возвращаем копию кэша, чтобы вызывающий код не изменил оригинал
  }

  window.BankLoader = { // Экспортируем API загрузчика банков
    loadBanks: loadBanks // Отдаём наружу только функцию загрузки
  }; // Завершаем экспорт
})(window); // Передаём window внутрь IIFE
