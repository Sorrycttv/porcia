# Android-приложение «Порция»

Клиент на Kotlin с XML-разметкой экранов. Проект открывается из этой папки в Android Studio. Требуемые версии SDK и Gradle указаны в файлах проекта; Gradle Wrapper включён.

## Адрес API
Перед сборкой задать `PORCIA_API_BASE_URL` в окружении Android Studio/Gradle либо `porciaApiBaseUrl` в пользовательском `~/.gradle/gradle.properties`, который находится за пределами репозитория. Пример формата: `https://api.example.invalid/`. Заменить его адресом своего сервера, сохранив завершающий `/`. После изменения окружения перезапустить IDE.

Gradle записывает URL в `BuildConfig.API_BASE_URL`. Личные параметры и `local.properties` не нужно добавлять в Git. Адрес нельзя считать секретом: он будет доступен в собранном APK. Постоянные API-ключи в клиент не встраиваются; пользователь получает токен после входа.

## Основные экраны
- `MainActivity`, `LoginActivity`, `RegisterActivity` — запуск, вход и регистрация.
- `HomeActivity`, `ProfileActivity` — главное меню и профиль.
- `PlanActivity` — меню на день или неделю, настройки, замена и закупка.
- `RecipeSearchActivity`, `FridgeActivity` — книга блюд и домашние продукты.
- `StorePricesActivity`, `StoreMapActivity` — поиск товаров и карта.
- `acriv_coach` — диалог с ИИ-помощником.

В `ApiService.kt` находятся модели запросов и интерфейс API. Чеклист закупки хранится локально; автоматического пополнения холодильника и синхронизации отметок с сервером нет.

## Сборка и тесты
Из этой папки:
```
gradlew.bat :app:assembleDebug
gradlew.bat :app:testDebugUnitTest
```
На Linux/macOS использовать `./gradlew`.

При проблеме с UTF-8 classpath Gradle в кириллическом пути Windows:
```
gradlew.bat :app:testDebugUnitTest --offline --no-configuration-cache -I tools/test-windows-paths.gradle
```

Проверки интерфейса на подготовленных данных находятся в `app/src/androidTest/`. Они не подтверждают работу домашнего сервера и не заменяют проверку на физическом телефоне.
