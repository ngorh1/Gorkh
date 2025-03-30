import os
import json
import re
import time
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import aiohttp
import logging
import asyncio
import requests
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настройка логирования для отладки
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Дополнительная настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,
    handlers=[
        logging.StreamHandler(),  # Выводит логи в консоль
        logging.FileHandler('bot_log.log', mode='a')  # Записывает логи в файл
    ]
)

# Токен бота из .env
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Токен OpenWeatherMap сохранён в коде (оставляем как есть)
WEATHER_API_KEY = '53133f8c78bc5bfe64e7ef63e7d4ec32'

# Bin ID и API Key из .env
BIN_ID = os.getenv("BIN_ID")
API_KEY = os.getenv("API_KEY")

# Путь к файлу с данными пользователей
USERS_FILE = 'users_data.json'

# Главное меню
main_menu = ReplyKeyboardMarkup(
    [
        [KeyboardButton('Поделиться местоположением', request_location=True)],
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# Приветственное меню
welcome_menu = ReplyKeyboardMarkup(
    [
        [KeyboardButton('Начать')]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Чтение данных пользователей из файла
def load_users():
    url = f'https://api.jsonbin.io/v3/b/{BIN_ID}/latest'
    headers = {'X-Master-Key': API_KEY}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get('record', {})
    else:
        print(f"Ошибка загрузки данных: {response.status_code}")
        return {}

# Функция для записи данных в локальный файл users_data.json
def save_to_local_file(users, filename="users_data.json"):
    try:
        with open(filename, 'w', encoding='utf-8') as file:
            json.dump(users, file, ensure_ascii=False, indent=4)
        print(f"Данные успешно сохранены локально в файл: {filename}")
    except Exception as e:
        print(f"Ошибка при сохранении данных в локальный файл: {e}")

# Обновленная функция для сохранения данных
def save_users(users):
    # Сохранение на JSONBin
    url = f'https://api.jsonbin.io/v3/b/{BIN_ID}'
    headers = {
        'X-Master-Key': API_KEY,
        'Content-Type': 'application/json'
    }
    response = requests.put(url, headers=headers, json=users)
    if response.status_code == 200:
        print("Данные успешно сохранены на JSONBin.")
    else:
        print(f"Ошибка сохранения данных на JSONBin: {response.status_code}")
    
    # Сохранение в локальный файл users_data.json
    save_to_local_file(users)


def escape_markdown_v2(text: str) -> str:
    """
    Экранирует запрещённые символы MarkdownV2 и заменяет 'nn' на символ новой строки '\n'.
    """
    # Запрещённые символы MarkdownV2, которые нужно экранировать
    escape_chars = r'[]()~`>#+-=|{}.!'

    # Заменяем 'nn' на '\n', чтобы создавались правильные новые строки
    text = text.replace('nn', '\n')

    # Экранируем все запрещённые символы, кроме новой строки
    def escape_except_newlines(match):
        content = match.group(0)
        # Если это ссылка, не экранируем
        if content.startswith("[") and "](" in content:
            return content
        # Экранируем только запрещённые символы
        return re.sub(f"([{re.escape(escape_chars)}])", r'\\\1', content)

    # Экранируем все символы, кроме новой строки
    return re.sub(r"\[.*?\]\(.*?\)|[^\n]", escape_except_newlines, text, flags=re.S)
# Задержка для команд /start
last_start_call = {}

# Команда /start

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    current_time = time.time()

    # Проверяем, запускал ли пользователь команду недавно
    if user_id in last_start_call and (current_time - last_start_call[user_id]) < 2:
        logging.info(f"Пользователь {user_id} повторно вызывает /start в течение 2 секунд. Игнорируем.")
        return  # Игнорируем повторный вызов

    last_start_call[user_id] = current_time  # Обновляем время последнего вызова

    # Загружаем список пользователей из jsonbin.io
    users = load_users()

    # Проверяем, зарегистрирован ли пользователь
    if user_id in users and users[user_id].get('started'):
        logging.info(f"Пользователь {user_id} уже запускал бота, игнорируем повторный /start")
        await update.message.reply_text(
            "Вы уже зарегистрированы! Добро пожаловать снова!",
            reply_markup=main_menu
        )
        return

    # Если пользователь не зарегистрирован, добавляем его данные
    username = update.message.from_user.username
    first_name = update.message.from_user.first_name
    last_name = update.message.from_user.last_name

    users[user_id] = {
        'username': username,
        'first_name': first_name,
        'last_name': last_name,
        'region': None,
        'location': None,
        'started': True  # Указываем, что пользователь зарегистрировался
    }

    # Сохраняем обновленные данные пользователей в jsonbin.io
    save_users(users)

    # Приветственное сообщение
    message = (
        "*Привет!* Я бот питомника GORKH — твой садовый помощник. Поделись геопозицией, и я начну присылать советы "
        "по уходу за розами и пионами, ориентируясь на твой регион и погоду. Полив, органическая подкормка, защита без химии — "
        "всё вовремя и натурально. Жми “Поделиться местоположением”, и начнем! Нажимая на кнопку _Поделиться местоположением_ "
        "вы соглашаетесь с [политикой обработки персональных данных](https://example.com)"
    )

    # Экранируем символы для MarkdownV2
    message = escape_markdown_v2(message)

    # Отправляем сообщение пользователю
    await update.message.reply_text(
        message,
        reply_markup=main_menu,
        parse_mode="MarkdownV2"
    )

# Получение данных о погоде из OpenWeatherMap
async def get_weather(lat, lon):
    url = f'http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=ru'
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.json()
            else:
                logging.error(f"Ошибка получения погоды: {response.status}")
                return {}

# Обработка местоположения
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    lat = update.message.location.latitude
    lon = update.message.location.longitude
    logging.info(f"Получено местоположение от пользователя {user_id}: {lat}, {lon}")

    # Получаем данные о погоде
    weather_info = await get_weather(lat, lon)
    if weather_info and 'main' in weather_info:
        region_type = classify_region_by_latitude(lat)

        # Загружаем пользователей из jsonbin.io
        users = load_users()

        # Проверяем, существует ли пользователь
        if user_id in users:
            user_data = users[user_id]
            # Обновляем данные, если местоположение изменилось
            if not user_data.get('location') or (
                user_data['location'].get('latitude') != lat or
                user_data['location'].get('longitude') != lon
            ):
                logging.info(f"Обновление данных местоположения пользователя {user_id}.")
                users[user_id]['location'] = {'latitude': lat, 'longitude': lon}
                users[user_id]['region'] = region_type
        else:
            # Если пользователь новый, добавляем его в базу
            logging.info(f"Добавление нового пользователя {user_id}.")
            users[user_id] = {
                'username': update.message.from_user.username,
                'first_name': update.message.from_user.first_name,
                'last_name': update.message.from_user.last_name,
                'region': region_type,
                'location': {'latitude': lat, 'longitude': lon}
            }

        # Сохраняем обновленные данные в jsonbin.io
        save_users(users)
        logging.info(f"Данные пользователя {user_id} сохранены: {users[user_id]}")

        # Генерация и отправка рекомендаций
        recommendation = generate_advice(weather_info)
        await update.message.reply_text(
            f"Ваш регион: {region_type}\n{recommendation}",
            reply_markup=main_menu,
            parse_mode="MarkdownV2"
        )
    else:
        # Сообщение об ошибке получения данных о погоде
        logging.error("Не удалось получить данные о погоде.")
        await update.message.reply_text(
            "Извините, не удалось получить данные о погоде.",
            reply_markup=main_menu
        )
# Классификация региона по широте
def classify_region_by_latitude(latitude):
    if latitude > 45 or latitude < -45:
        return 'холодный'
    else:
        return 'тёплый'

# Генерация рекомендаций по уходу
def generate_advice(weather_data):
    temp = weather_data.get('main', {}).get('temp', 0)

    if temp < 5:
        return escape_markdown_v2(
            f"*Температура ({temp}°C). Холодный период, ранняя весна/поздняя осень.* \n\n"
            "*Розы:*\n"
            " • Полив не требуется, если нет продолжительной засухи.\n"
            " • Важно избегать застоя воды у корней, особенно если кусты находятся под укрытием.\n"
            " • Если осенью долго стоит сухая погода, перед первыми морозами проводят обильный полив (20–30 литров на взрослый куст), чтобы розы ушли в зиму с хорошо увлажненной почвой.\n\n"
            "*Пионы:*\n"
            " • Полив полностью прекращают – осенью пионы уходят в состояние покоя, а ранней весной корни только просыпаются.\n"
            " • Если осенью было мало дождей, перед морозами проводят однократный полив (10 литров на взрослый куст)."
        )
    elif 5 <= temp <= 15:
        return escape_markdown_v2(
            f"*Температура ({temp}°C). Пробуждение весной / подготовка к зиме осенью.*\n\n"
            "*Розы:*\n"
            " • Весной начинают постепенный полив – раз в 10-15 дней, если нет дождей.\n"
            " • Если роза под укрытием, полив проводят только после его снятия, иначе может начаться выпревание.\n"
            " • Осенью полив сокращают, а в конце октября в холодных регионах его прекращают полностью.\n\n"
            "*Пионы:*\n"
            " • Весной, когда появляются первые ростки, важно поддерживать почву слегка влажной, но не сырой.\n"
            " • Полив раз в 20 дней, около 5–7 литров на куст.\n"
            " • Важно рыхлить почву после полива, чтобы улучшить доступ кислорода к корням."
        )
    elif 15 < temp <= 25:
        return escape_markdown_v2(
            f"*Температура ({temp}°C). Активный рост, бутонизация и цветение.* \n\n"
            "*Розы:*\n"
            " • Полив раз в 10 дней, расходуя 10–15 литров на куст.\n"
            " • Если стоит тёплая, но не засушливая погода, лучше реже, но глубже промачивать почву.\n"
            " • Во время цветения важно избегать попадания воды на листья и бутоны, чтобы не спровоцировать грибковые заболевания.\n"
            " • Мульчирование корой помогает удерживать влагу и предотвращает растрескивание почвы.\n\n"
            "*Пионы:*\n"
            " • Полив раз в 10 дней, около 7 литров на куст.\n"
            " • В период активного роста и бутонизации увлажнение особенно важно – недостаток влаги может привести к мелким или недоразвитым бутонам.\n"
            " • После полива обязательно рыхлить почву, чтобы корни получали кислород.\n"
            " • Слой мульчи (для южных регионов) поможет удержать влагу."
        )
    else:  # temp > 25
        return escape_markdown_v2(
            f"*Температура ({temp}°C). Жара, засушливый период.* \n\n"
            "*Розы:*\n"
            " • Полив раз в 3–4 дня, расходуя 20–30 литров на куст.\n"
            " • Лучшее время для полива – раннее утро или вечер. Днём вода быстро испарится, а на листьях могут появиться ожоги.\n"
            " • Под кустами почву обязательно мульчируют, иначе влага будет быстро испаряться.\n"
            " • Раз в 2 недели можно проводить подкормку гуматами, чтобы корни лучше усваивали воду и питательные вещества.\n\n"
            "*Пионы:*\n"
            " • Полив раз в 5 дней, около 10-15 литров на взрослый куст.\n"
            " • Жара особенно опасна для молодых пионов – если кусту меньше 3 лет, следите, чтобы почва не пересыхала.\n"
            " • Можно добавить капельный полив, особенно для сортов с крупными махровыми цветами – они быстрее теряют влагу.\n"
            " • *Важно:* Если пионы выглядят увядшими, не заливайте их сразу большим количеством воды! Легче провести опрыскивание почвы вокруг куста водой и через пару часов полить основательно."
        )

# Рассылка для тёплого региона
async def broadcast_warm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Загружаем пользователей из jsonbin.io
    users = load_users()
    message = ' '.join(context.args)

    if not message:
        await update.message.reply_text("Введите текст для рассылки: /broadcast_warm Текст сообщения")
        return

    escaped_message = escape_markdown_v2(message)  # Экранируем запрещённые символы

    try:
        for user_id, data in users.items():
            if data.get('region') == 'тёплый':  # Условие для тёплого региона
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"*Тёплый регион:*\n{escaped_message}",  # Заголовок жирным
                    parse_mode="MarkdownV2"
                )
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения {user_id}: {e}")

# Рассылка для холодного региона
async def broadcast_cold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Загружаем пользователей из jsonbin.io
    users = load_users()
    message = ' '.join(context.args)

    if not message:
        await update.message.reply_text("Введите текст для рассылки: /broadcast_cold Текст сообщения")
        return

    escaped_message = escape_markdown_v2(message)  # Экранируем запрещённые символы

    try:
        for user_id, data in users.items():
            if data.get('region') == 'холодный':  # Условие для холодного региона
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"*Холодный регион:*\n{escaped_message}",  # Заголовок жирным
                    parse_mode="MarkdownV2"
                )
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения {user_id}: {e}")

# Тестовая рассылка
# Тестовая рассылка
async def broadcast_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    message = ' '.join(context.args)

    if not message:
        await update.message.reply_text("Введите текст для тестовой рассылки: /broadcast3 Тестовое сообщение")
        return

    escaped_message = escape_markdown_v2(message)  # Экранируем запрещённые символы

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"*Тестовая рассылка:*\n{escaped_message}",  # Заголовок жирным
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения для теста: {e}")

# Основная функция запуска бота
# Основная функция запуска бота
if __name__ == '__main__':
    import sys
    import threading

    # Устанавливаем политику для событийного цикла Windows
    if sys.platform.startswith('win'):
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Инициализация Telegram-бота
    bot_app = ApplicationBuilder().token(TOKEN).build()

    # Добавление хендлеров
    bot_app.add_handler(CommandHandler('start', start))
    bot_app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    bot_app.add_handler(CommandHandler('broadcast1', broadcast_warm))
    bot_app.add_handler(CommandHandler('broadcast2', broadcast_cold))
    bot_app.add_handler(CommandHandler('broadcast3', broadcast_test))

    # Запуск Telegram-бота в отдельной функции
    def run_telegram_bot():
        bot_app.run_polling()  # Исправлено: убран asyncio.run()

    # Инициализация Flask
    from flask import Flask

    flask_app = Flask(__name__)

    # Обработчик для UptimeRobot
    @flask_app.route('/ping', methods=['GET'])
    def ping():
        return "Bot is alive!", 200

    # Запуск Flask в отдельном потоке
    def run_flask():
        flask_app.run(host="0.0.0.0", port=5000)

    # Запускаем Flask и Telegram-бота параллельно
    threading.Thread(target=run_flask).start()
    run_telegram_bot()
