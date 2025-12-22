(function (window, document) { // Изолируем основной код Mini App
  document.addEventListener('DOMContentLoaded', function () { // Запускаем логику после готовности DOM
    const bankListElement = document.querySelector('.bank-list'); // Находим контейнер для кнопок банков
    const backButton = document.querySelector('.back-btn'); // Находим кнопку "← Вернуться"
    const telegramContext = window.TelegramBridge.getTelegramContext(); // Собираем контекст Telegram (или браузера)
    const transferId = telegramContext.startParam || (telegramContext.initDataUnsafe ? telegramContext.initDataUnsafe.start_param : ''); // Забираем transfer_id для запросов
    const linkCache = new Map(); // Кэшируем загруженные ссылки, чтобы не повторять запросы
    let linksPromise = null; // Храним единственный промис загрузки ссылок, чтобы не дёргать backend много раз

    window.ApiClient.sendWebAppOpen(telegramContext); // Отправляем событие открытия Mini App

    backButton.addEventListener('click', function () { // Навешиваем обработчик на кнопку возврата
      window.ApiClient.sendRedirectEvent(telegramContext, '', 'back_click', 'miniapp'); // Логируем клик по кнопке назад
      window.TelegramBridge.closeMiniApp(); // Корректно закрываем Mini App или возвращаемся назад
    }); // Завершаем обработчик кнопки назад

    window.BankLoader.loadBanks() // Загружаем встроенный список банков без ожидания backend, чтобы WKWebView показал первый кадр мгновенно
      .then(function (banks) { // После получения массива
        renderBanks(banks, bankListElement, telegramContext, transferId, linkCache, function loadLinksOnce() { // Рисуем кнопки и прокидываем загрузчик ссылок
          if (linksPromise) { // Если загрузка уже идёт
            return linksPromise; // Возвращаем существующий промис
          } // Завершаем проверку
          linksPromise = window.ApiClient.fetchBankLinks(transferId) // Запрашиваем ссылки только по требованию
            .then(function (links) { // После успешного ответа
              (links || []).forEach(function (link) { // Перебираем каждую ссылку
                const bankId = link.bank_id || link.id || ''; // Аккуратно достаём id банка
                if (bankId) { // Если id найден
                  linkCache.set(bankId, link); // Кладём объект в кэш для быстрых повторных кликов
                } // Завершаем проверку id
              }); // Завершаем forEach
              return links || []; // Возвращаем массив ссылок для дальнейшей цепочки
            }) // Завершаем then с обработкой ссылок
            .catch(function (error) { // Если запрос не удался
              console.debug('App: не удалось получить ссылки банка', error); // Сообщаем в debug, но UI не блокируем
              throw error; // Пробрасываем ошибку, чтобы обработать её в клике
            }); // Завершаем обработку fetch
          return linksPromise; // Возвращаем сохранённый промис, чтобы совпадал с объявлением
        }); // Завершаем рендер списка
        attachStretchEffect(bankListElement, '.btn'); // Добавляем эффект "растяжки" при прокрутке
      }) // Завершаем успешную загрузку банков
      .catch(function (error) { // Если даже встроенный список не вернулся
        console.debug('App: не удалось подготовить список банков', error); // Сообщаем в debug для диагностики
      }); // Завершаем обработку ошибок

    lazyLoadBackground(); // Догружаем фоновую картинку сразу, чтобы она подхватилась как только загрузится
  }); // Завершаем обработчик DOMContentLoaded

  function renderBanks(banks, container, telegramContext, transferId, linkCache, requestLinksOnce) { // Создаём кнопки для каждого банка
    container.innerHTML = ''; // Очищаем контейнер перед вставкой
    const fragment = document.createDocumentFragment(); // Готовим фрагмент, чтобы вставить элементы одной операцией

    if (!banks || !banks.length) { // Если список пустой или невалидный
      const message = document.createElement('p'); // Создаём текстовый блок
      message.className = 'error-text'; // Добавляем класс для стилизации ошибки
      message.textContent = 'Не удалось загрузить список банков. Попробуйте обновить страницу.'; // Показываем простое сообщение
      container.appendChild(message); // Добавляем в контейнер одним действием
      return; // Завершаем рендер, чтобы не падать
    } // Завершаем проверку пустого списка

    banks.forEach(function (bank, index) { // Перебираем список банков
      const button = document.createElement('button'); // Создаём элемент кнопки
      button.className = 'btn'; // Назначаем класс стилизации
      button.setAttribute('type', 'button'); // Указываем тип кнопки
      button.dataset.bankId = bank.bank_id || bank.id || ''; // Сохраняем id банка в data-атрибуте

      const iconWrapper = document.createElement('div'); // Создаём обёртку под иконку с плейсхолдером
      iconWrapper.className = 'bank-icon'; // Назначаем базовый класс иконки

      const icon = document.createElement('img'); // Создаём картинку логотипа
      icon.className = 'bank-icon__img'; // Добавляем класс для плавного показа
      icon.src = bank.logo; // Устанавливаем путь к логотипу
      icon.alt = bank.title; // Добавляем альтернативный текст
      icon.loading = 'lazy'; // Разрешаем браузеру отложенную загрузку
      icon.decoding = 'async'; // Просим асинхронное декодирование для быстрого первого кадра
      icon.width = 32; // Уменьшаем ширину логотипа на 20%, чтобы он стал компактнее
      icon.height = 32; // Ставим ту же высоту для сохранения пропорций и компактности
      icon.addEventListener('load', function () { // Когда логотип загрузился
        iconWrapper.classList.add('bank-icon--ready'); // Помечаем, что можно показывать картинку
      }); // Завершаем обработчик загрузки
      icon.addEventListener('error', function () { // Если логотип не загрузился
        console.debug('App: не удалось загрузить логотип банка', bank.logo); // Сообщаем в debug, UI не блокируем
      }); // Завершаем обработчик ошибки

      const title = document.createElement('span'); // Создаём элемент для текста
      title.className = 'btn-text'; // Назначаем класс текста
      title.textContent = bank.title; // Записываем название банка

      const status = document.createElement('span'); // Создаём индикатор состояния
      status.className = 'btn-status'; // Назначаем класс для подсветки
      status.setAttribute('aria-live', 'polite'); // Просим скринридеры озвучивать статус

      button.addEventListener('click', function () { // Реагируем на клик по конкретному банку
        handleBankClick(bank, button, status, telegramContext, transferId, linkCache, requestLinksOnce); // Передаём всю контекстную информацию
      }); // Завершаем подписку на клик

      iconWrapper.appendChild(icon); // Вставляем логотип внутрь плейсхолдера
      button.appendChild(iconWrapper); // Вставляем иконку в кнопку
      button.appendChild(title); // Добавляем текст внутрь кнопки
      button.appendChild(status); // Добавляем статус внутрь кнопки

      const delay = index * 0.05; // Высчитываем задержку анимации для ступенчатого появления
      button.style.animation = 'slideUp 0.6s ease-out both ' + delay + 's'; // Назначаем CSS-анимацию кнопке

      fragment.appendChild(button); // Помещаем готовую кнопку в фрагмент
    }); // Завершаем перебор банков

    container.appendChild(fragment); // Вставляем все кнопки одной операцией для быстрого рендера
  }

  function handleBankClick(bank, button, statusElement, telegramContext, transferId, linkCache, requestLinksOnce) { // Обрабатываем клик по банку
    window.ApiClient.sendBankClick(telegramContext, bank.bank_id || bank.id, { link_id: bank.link_id, link_token: bank.link_token }); // Отправляем событие выбора банка

    if (bank.close_only) { // Если кнопка-заглушка
      showStatus(statusElement, 'Закрываем…'); // Сообщаем пользователю о действии
      setTimeout(function () { // Делаем короткую паузу перед закрытием
        window.TelegramBridge.closeMiniApp(); // Закрываем Mini App без перехода
      }, 200); // Даём телеметрии стартовать
      return; // Завершаем обработчик клика
    } // Завершаем проверку заглушки

    showStatus(statusElement, 'Получаем ссылку…'); // Показываем лёгкий индикатор загрузки
    button.disabled = true; // Блокируем повторные клики, чтобы не дублировать запросы

    requestLinkData(bank, transferId, linkCache, requestLinksOnce) // Загружаем или достаём из кэша данные для редиректа
      .then(function (resolvedBank) { // После успешной загрузки ссылки
        openRedirect(resolvedBank, telegramContext); // Перенаправляем пользователя на страницу редиректа
      }) // Завершаем успешный then
      .catch(function (error) { // Если не удалось получить ссылку
        console.debug('App: не удалось получить диплинк для банка', error); // Сообщаем в debug
        showStatus(statusElement, 'Не удалось получить ссылку'); // Показываем пользователю понятную ошибку
        setTimeout(function () { // Через короткую паузу
          hideStatus(statusElement); // Прячем статус, чтобы кнопка вернулась в норму
        }, 2500); // Достаточно времени, чтобы прочитать сообщение
      }) // Завершаем обработку ошибки
      .finally(function () { // Независимо от результата
        button.disabled = false; // Разблокируем кнопку для следующей попытки
      }); // Завершаем финальную стадию
  }

  function requestLinkData(bank, transferId, linkCache, requestLinksOnce) { // Возвращаем банк с заполненными ссылками из backend
    const bankId = bank.bank_id || bank.id || ''; // Безопасно получаем идентификатор банка
    if (!bankId) { // Если id пустой
      return Promise.reject(new Error('Неизвестный банк')); // Возвращаем отклонённый промис
    } // Завершаем проверку наличия id

    if (linkCache.has(bankId)) { // Если ссылка для банка уже есть
      const cached = linkCache.get(bankId); // Забираем объект из кэша
      return Promise.resolve(Object.assign({}, bank, cached)); // Возвращаем объединённые данные без сетевого запроса
    } // Завершаем проверку кэша

    return requestLinksOnce() // Запускаем единственный запрос за ссылками
      .then(function () { // После завершения загрузки
        const cachedLink = linkCache.get(bankId); // Пробуем достать ссылку из кэша
        if (cachedLink) { // Если ссылка нашлась
          return Object.assign({}, bank, cachedLink); // Возвращаем объединённый объект
        } // Завершаем успешную ветку
        throw new Error('Ссылка для выбранного банка не найдена'); // Сообщаем о проблеме, чтобы отобразить ошибку
      }); // Завершаем цепочку
  }

  function showStatus(statusElement, text) { // Показываем статус на кнопке
    statusElement.textContent = text; // Устанавливаем текст статуса
    statusElement.classList.add('is-visible'); // Делаем статус видимым
  }

  function hideStatus(statusElement) { // Прячем статус на кнопке
    statusElement.textContent = ''; // Сбрасываем текст
    statusElement.classList.remove('is-visible'); // Прячем элемент визуально
  }

  function openRedirect(bank, telegramContext) { // Формируем ссылку на страницу редиректа и открываем её
    const preparedUrl = buildRedirectUrl(bank, telegramContext); // Собираем безопасный URL для страницы редиректа

    window.ApiClient.sendRedirectEvent(telegramContext, bank.bank_id || bank.id, 'redirect_prepare', 'miniapp', { link_token: bank.link_token || '' }); // Логируем факт подготовки редиректа

    window.TelegramBridge.openExternalLink(preparedUrl); // Открываем ссылку во внешнем браузере или новой вкладке

    setTimeout(function () { // Делаем короткую задержку, чтобы sendBeacon успел стартовать
      window.TelegramBridge.closeMiniApp(); // Закрываем Mini App после запуска перехода
    }, 200); // Укладываемся в диапазон 150–300 мс
  }

  function buildRedirectUrl(bank, telegramContext) { // Строим итоговый URL страницы редиректа
    const redirectBase = buildRedirectBase(); // Определяем базовый адрес редиректа с учётом вложенности сайта
    const redirectUrl = new URL(redirectBase, window.location.href); // Создаём объект URL для удобной работы с параметрами
    const transferId = telegramContext.startParam || (telegramContext.initDataUnsafe ? telegramContext.initDataUnsafe.start_param : ''); // Достаём transfer_id для телеметрии редиректа
    const bankId = bank.bank_id || bank.id || ''; // Безопасно получаем идентификатор банка

    if (bankId) { // Если id банка известен
      redirectUrl.searchParams.set('bank_id', bankId); // Добавляем его как query-параметр
    } // Завершаем проверку id

    if (transferId) { // Если есть transfer_id
      redirectUrl.searchParams.set('transfer_id', transferId); // Добавляем его для трейсинга на странице редиректа
    } // Завершаем проверку transfer_id

    if (bank.link_token) { // Если backend выдал link_token
      redirectUrl.searchParams.set('token', bank.link_token); // Используем токен как основной способ получения ссылок
      return redirectUrl.toString(); // Возвращаем сформированную строку
    } // Завершаем ветку с токеном

    if (bank.deeplink) { // Если токена нет, но есть deeplink
      redirectUrl.searchParams.set('deeplink', bank.deeplink); // Пробрасываем deeplink как запасной вариант
    } // Завершаем ветку deeplink

    if (bank.fallback_url) { // Если есть fallback_url
      redirectUrl.searchParams.set('fallback_url', bank.fallback_url); // Добавляем fallback для редирект-страницы
    } // Завершаем ветку fallback

    return redirectUrl.toString(); // Возвращаем итоговый URL с доступными параметрами
  }

  function buildRedirectBase() { // Высчитываем корректный базовый путь для страницы редиректа
    const repoPrefix = '/Flow_Lite_bot_WebApp/'; // Жёстко указываем имя репозитория для корректной работы GitHub Pages
    const defaultBase = (window.location.origin || '') + repoPrefix + 'redirect/'; // Собираем дефолтный адрес вида https://host/Flow_Lite_bot_WebApp/redirect/
    return (window.AppConfig && window.AppConfig.REDIRECT_BASE_URL) || defaultBase; // Возвращаем адрес из конфига или рассчитанный дефолт
  }

  function lazyLoadBackground() { // Догружаем фоновую картинку сразу после старта, чтобы фон появлялся как только загрузится
    const version = (window.AppConfig && window.AppConfig.APP_ASSETS_VERSION) || (window.APP_ASSETS_VERSION || ''); // Берём версию ассетов для bust параметра сразу
    const bgUrl = './assets/bg/background.png' + (version ? '?v=' + version : ''); // Формируем URL фоновой картинки с версией без задержек
    const img = new Image(); // Создаём объект Image для предзагрузки
    img.onload = function () { // После успешной загрузки
      document.body.style.setProperty('--app-bg-image', 'url(' + bgUrl + ')'); // Сохраняем URL в CSS-переменную, чтобы слой сразу стал валидным
      document.body.classList.add('bg-ready'); // Включаем слой с картинкой, как только она декодировалась
    }; // Завершаем обработчик onload
    img.onerror = function () { // Если картинка не загрузилась
      console.debug('App: не удалось загрузить фоновую картинку', bgUrl); // Сообщаем в debug, чтобы проще найти причину
    }; // Завершаем обработчик ошибки
    img.src = bgUrl; // Стартуем загрузку без задержек, чтобы фон появился сразу после готовности
  }

  function attachStretchEffect(listElement, buttonSelector) { // Добавляем "растяжку" списка при упоре
    let startY = 0; // Точка начала касания
    let touching = false; // Флаг активного касания

    listElement.addEventListener('touchstart', function (event) { // Фиксируем начало касания
      touching = true; // Включаем режим отслеживания
      startY = event.touches[0].clientY; // Запоминаем исходную координату Y
    }); // Завершаем обработчик начала касания

    listElement.addEventListener('touchmove', function (event) { // Реагируем на движение пальца
      if (!touching) { // Если касание не активно
        return; // Выходим из обработчика
      } // Завершаем проверку активности
      const delta = event.touches[0].clientY - startY; // Вычисляем смещение относительно старта
      const scale = 1 + Math.min(Math.abs(delta) / 200, 0.1); // Считаем коэффициент растяжки
      const atTop = listElement.scrollTop === 0 && delta > 0; // Проверяем упор в начало списка
      const atBottom = listElement.scrollTop + listElement.clientHeight >= listElement.scrollHeight && delta < 0; // Проверяем упор в конец списка
      if (atTop || atBottom) { // Если действительно упёрлись
        document.querySelectorAll(buttonSelector).forEach(function (button) { // Применяем стиль ко всем кнопкам
          button.style.transform = 'scaleY(' + scale + ')'; // Тянем кнопку по оси Y
        }); // Завершаем перебор кнопок
      } // Завершаем проверку упора
    }); // Завершаем обработчик движения

    listElement.addEventListener('touchend', function () { // Когда палец оторвали от экрана
      touching = false; // Выключаем режим отслеживания
      document.querySelectorAll(buttonSelector).forEach(function (button) { // Возвращаем кнопки к норме
        button.style.transition = 'transform 0.3s'; // Добавляем плавность
        button.style.transform = 'scaleY(1)'; // Сбрасываем растяжку
        setTimeout(function () { // После завершения анимации
          button.style.transition = ''; // Убираем transition, чтобы не мешал в дальнейшем
        }, 300); // Время совпадает с длительностью transition
      }); // Завершаем перебор кнопок
    }); // Завершаем обработчик завершения касания
  }
})(window, document); // Передаём объекты window и document внутрь IIFE
