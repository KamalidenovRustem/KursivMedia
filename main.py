import os
import time
import logging
import psycopg2
from io import BytesIO
from PIL import Image
from datetime import datetime
import telebot
from telebot import types
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackContext
from dotenv import  dotenv_values

# Загружаем переменные с .env файла
config = dotenv_values(".env")


# Свои настройки PostgreSQL
db_host = (config['DATABASE_HOST'])
db_port = (config['DATABASE_PORT'])
db_name = (config['DATABASE_NAME'])
db_user = (config['DATABASE_USER'])
db_password = (config['DATABASE_PASSWORD'])

# Вставить API token нашего бота
token = (config['TELEGRAM_BOT_CODE'])
bot = telebot.TeleBot(token)

# Соединение с базой данных
conn = psycopg2.connect(
    host=db_host,
    port = db_port,
    database=db_name,
    user=db_user,
    password=db_password
)
cursor = conn.cursor()

# Создание базы данных ниже
# Таблица для хранения заявок
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS requests (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        text TEXT,
        photo TEXT,
        video TEXT,
        status INTEGER,
        rejection_reason TEXT,
        time TIMESTAMP DEFAULT current_timestamp
    );
    """
)

# Таблица для хранения информации о пользователе
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        user_id BIGINT
    );
''')

# Создание таблицы модераторов, если она не существует
cursor.execute('''
    CREATE TABLE IF NOT EXISTS moderators (
        id SERIAL PRIMARY KEY,
        moder_id BIGINT
    );
''')

# Создание таблицы групп, если она не существует
cursor.execute('''
    CREATE TABLE IF NOT EXISTS groups (
        id SERIAL PRIMARY KEY,
        group_id BIGINT
    );
''')

# Создание таблицы кулдауна, если она не существует
cursor.execute('''
    CREATE TABLE IF NOT EXISTS cooldown (
        id SERIAL PRIMARY KEY,
        cooldown_value BIGINT
    );
''')

conn.commit()


#Одноразовый запуск
# Функция для вставки данных в таблицу
def insert_data(cursor, table_name, column_name, value):
    try:
        insert_query = f"INSERT INTO {table_name} ({column_name}) VALUES (%s) ON CONFLICT DO NOTHING;" #Если группа, модератор и кулдаун уже определены, база данных не будет изменена
        cursor.execute(insert_query, (value,))
        conn.commit()
        print(f"Данные успешно вставлены в таблицу {table_name}.")
    except Exception as e:
        conn.rollback()
        print(f"Ошибка: {e}")

# Вставка группы в таблицу "groups"
group_id = -1001965855664
insert_data(cursor, 'groups', 'group_id', group_id)

# Вставка значения cooldown в таблицу "cooldown"
cooldown_int = 60
insert_data(cursor, 'cooldown', 'cooldown_value', cooldown_int)

# Вставка модератора в таблицу "moderators"
first_moder_id = 1732450131
insert_data(cursor, 'moderators', 'moder_id', first_moder_id)



#Телеграм-бот 

# Извлечение идентификаторов модераторов из базы данных и заполнение списка moderator_ids
def retrieve_moderator_ids(cursor):
    # SQL-запрос для извлечения идентификаторов модераторов
    cursor.execute("SELECT moder_id FROM moderators")
    moderator_records = cursor.fetchall()

    # Извлечение идентификаторов модераторов из записей и сохранение их в списке moderator_ids
    moderator_ids = [record[0] for record in moderator_records]

    return moderator_ids


#Получение модераторов
moderator_ids = retrieve_moderator_ids(cursor)

# Получение данных
def retrieve_data(cursor, table, column, record_id):
    # SQL-запрос с параметрами
    query = f'SELECT {column} FROM "{table}" WHERE id = %s;'

    # Параметры для запроса
    params = (record_id,)

    # Выполнение запроса и получение результата
    cursor.execute(query, params)
    result = cursor.fetchone()

    # Получение значения из результата или None, если нет данных
    return result[0] if result else None

# идентификатор чата группы для отправки сообщения
# Вызов функции для безопасного получения other_group_chat_id
other_group_chat_id = [retrieve_data(cursor, 'groups', 'group_id', 1)] # Если у заказчика будет 1 группа    

# Функция получения кулдауна из базы данных
def get_cooldown_value_from_db():
    cursor.execute("SELECT cooldown_value FROM cooldown WHERE id = 1")
    result = cursor.fetchone()
    if result:
        return result[0]
    return None

#Логирование
logging.basicConfig(filename='bot.log', level=logging.INFO)

#Получение команды
@bot.message_handler(commands=['get'])
def send_chat_id(message):
    # Check if the user who sent the command is in the moderator_ids list
    if message.from_user.id in moderator_ids:
        # Check if the message is in a group or supergroup chat
        if message.chat.type in ["group", "supergroup"]:
            # Send the chat ID as a private message to the user
            bot.send_message(message.from_user.id, f"Chat ID этой группы: {message.chat.id}")
        else:
            bot.reply_to(message, "Эта команда должна быть выполнена в групповом чате.")
    else:
        bot.reply_to(message, "Вы не имеете доступа к этой команде.")

#Создание Клавиатуры
def create_keyboard(buttons):
    keyboard = types.ReplyKeyboardMarkup(row_width=len(buttons), resize_keyboard=True)
    for text in buttons:
        button = types.KeyboardButton(text)
        keyboard.add(button)
    return keyboard


# Клавиатура пользователя
user_buttons = ["Отправить материал", "О нас", "Контакты", "Посмотреть статус заявок"]
start_menu_keyboard = create_keyboard(user_buttons)

# Клавиатура модератора
moderator_buttons = ["Посмотреть заявки", "Рассылка", "Настройка бота", "Публикация на канале",]
moderator_keyboard = create_keyboard(moderator_buttons)

# Настройки бота у модератора
settings_buttons = ["Добавить модератора", "Изменить группу", "Изменить интервал отправки заявок", "Вернуться Назад"]
settings_keyboard = create_keyboard(settings_buttons)

# Обработчик команды "старт"
@bot.message_handler(commands=['start'])
def handle_start(message):
  if message.chat.type != 'private':
        bot.send_message(message.chat.id, "Этот бот работает только в приватных чатах.")
        return

  user_id = message.from_user.id

  if user_id in moderator_ids:  # Check if the user is a moderator
        bot.send_message(user_id, "Вы модератор.", reply_markup=moderator_keyboard)
  else:
        bot.send_message(user_id, "Вы пользователь.", reply_markup=start_menu_keyboard)

    # Check if the user is not already in the 'users' table
  cursor.execute("SELECT id FROM users WHERE user_id = %s", (user_id,))
  user_exists = cursor.fetchone()

  if not user_exists:
    # If the user is not in the database, insert them
      cursor.execute("INSERT INTO users (user_id) VALUES (%s)", (user_id,))
      conn.commit()
      bot.send_message(message.chat.id, 'Привет! \n С помощью этого бота вы можете отправить материал для Kursiv Playground.', 
                       reply_markup=start_menu_keyboard) # Инициация стартового меню для пользоватлей
      

#Основной функционал
# Function to handle the "Отправить материал" command
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'отправить материал')
def send_material_command(message):
    if message.text.lower() == 'отправить материал':
        #bot.delete_message(message.chat.id, message.message_id - 1)
        Keyboard = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        button = types.KeyboardButton(text='Оставить заявку')
        button2 = types.KeyboardButton(text='Выход в главное меню')
        Keyboard.add(button, button2)
        bot.send_message(message.chat.id, "Критерии материала: \n *Ограничения по символам \n *Фактчекинг \n *Оригинальность \n *Предупреждение о ненарушении законодательства РК \n *Какие материалы ожидаем (темы, формат) \n *Инфо о конкурсе ", 
                         reply_markup=Keyboard)
        

# Команда "Оставить заявку"
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'оставить заявку')
def repeat_all_messages(message):
    if message.text.lower() == 'оставить заявку':
        #Delete the button
        #markup = types.ReplyKeyboardRemove(selective=False)

        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        button = types.KeyboardButton(text='Выход в главное меню')
        markup.add(button)

        if message.text and message.text.lower() == 'выход в главное меню':
          bot.send_message(message.chat.id, "Выход в главное меню", reply_markup=start_menu_keyboard)
        else:
          bot.send_message(message.chat.id, 'Чтобы отправить материал, введите или вставьте ниже свой контент в чат одним сообщением. Вы также можете прикрепить фото и видео к вашей статье. \n Обязательно укажите заголовок для вашей статьи и выделите в тексте ссылки на источники. \n Если вы хотите, чтобы вас упомянули как автора материала, в конце текста укажите своё имя/никнейм.', 
                           reply_markup=markup)
          bot.register_next_step_handler(message, send_request)



# Команда "О нас"
@bot.message_handler(content_types=['text'], func=lambda message: message.chat.type == 'private' and message.text.lower() == 'о нас')
def repeat_all_messages(message):
    if message.text.lower() == 'о нас':
        Keyboard = types.InlineKeyboardMarkup()
        Url_button = types.InlineKeyboardButton(text='Ссылка на наш сайт', url="https://kz.kursiv.media/")
        Keyboard.add(Url_button)
        #bot.delete_message(message.chat.id, message.message_id - 1)
        bot.send_message(message.chat.id, "Немного о Playground \n (Общая вводная инфо, принципы издания)", reply_markup=Keyboard)



# Команда "Контакты"
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'контакты')
def repeat_all_messages(message):
    if message.text.lower() == 'контакты':
        Keyboard = types.InlineKeyboardMarkup()
        Url_button1 = types.InlineKeyboardButton(text='Telegram', url="https://www.youtube.com/watch?v=Zi_XLOBDo_Y")
        Url_button2 = types.InlineKeyboardButton(text='WhatsApp', url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        Keyboard.add(Url_button1, Url_button2)
        #bot.delete_message(message.chat.id, message.message_id - 1)
        bot.send_message(message.chat.id, "Контакты для обратной связи и по вопросам сотрудничества", reply_markup=Keyboard)



# Команда "Посмотреть статус заявок"
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'посмотреть статус заявок')
def check_request_status(message):
    user_id = message.from_user.id
    print(user_id)
    user_requests = get_user_requests(user_id)

    if not user_requests:
        bot.send_message(user_id, "У вас нет активных заявок.", reply_markup=start_menu_keyboard)
    else:
        bot.send_message(user_id, f"Помните, что бот отправляет лишь {request_limit} последних заявок. \n Ваши заявки:")

        for request in user_requests:
            request_id, status, timestamp = request
            formatted_timestamp = timestamp.strftime("%d/%m/%Y")  # Format timestamp to day/month/year
            if status == 1:
                bot.send_message(user_id, f"Заявка #{request_id}: Ожидает модерации\nДата: {formatted_timestamp}")
            elif status == 2:
                bot.send_message(user_id, f"Заявка #{request_id}: Одобрена\nДата: {formatted_timestamp}")
            elif status == 3:
              # Send a button to retrieve rejection reason from the database
                markup = types.InlineKeyboardMarkup()
                button = types.InlineKeyboardButton("Причина отклонения", callback_data=f"reason_{request_id}")
                markup.add(button)
                bot.send_message(user_id, f"Заявка #{request_id}: Отклонена. "
                                          f"\nДата: {formatted_timestamp}"
                                          f"\nНажмите на кнопку, чтобы узнать причину отклонения:", reply_markup=markup)

# Определение количества запросов для извлечения
request_limit = 10

def get_user_requests(user_id):
    user_requests = []
    # SQL-запрос, чтобы упорядочить результаты по времени и ограничить результаты
    cursor.execute("SELECT id, status, time FROM requests WHERE user_id = %s ORDER BY time DESC LIMIT %s", (user_id, request_limit))
    results = cursor.fetchall()

    for row in results:
        request_id, status, timestamp = row
        user_requests.append((request_id, status, timestamp))

    return user_requests

# Обработчик коллбэк-запросов для причины отказа
@bot.callback_query_handler(func=lambda call: call.data.startswith('reason_'))
def send_rejection_reason(call):
    request_id = int(call.data.split('_')[1])

    # Здесь вы можете получить причину отказа из базы данных
    rejection_reasons = get_rejection_reasons([request_id])

    if request_id in rejection_reasons:
        bot.send_message(call.message.chat.id,
                         f"Причина отказа для заявки #{request_id}:\n{rejection_reasons[request_id]}")
    else:
        bot.send_message(call.message.chat.id, f"Для заявки #{request_id} не указана причина отказа.")


def get_rejection_reasons(request_ids):
    # Подготавливаем список запросов вида (?, ?, ?)
    placeholders = ', '.join(['%s'] * len(request_ids))

    # Выполняем SQL-запрос для извлечения причин отказа
    query = f"SELECT id, rejection_reason FROM requests WHERE id IN ({placeholders})"
    cursor.execute(query, tuple(request_ids))

    rejection_reasons = {request_id: reason for request_id, reason in cursor.fetchall()}

    return rejection_reasons


# Функция для получения всех пользователей из базы данных
def get_all_users():
    users = []
    cursor.execute("SELECT user_id FROM users")
    result = cursor.fetchall()
    for row in result:
        users.append(row[0])
    return users

# При подписке нового пользователя добавляем его user_id в базу данных
def add_user(user_id):
    cursor.execute("INSERT INTO users (user_id) VALUES (%s)", (user_id,))
    conn.commit()

## ЧТО ЭТО  ##
def publish_text_to_group(message):
    user_id = message.from_user.id

    if user_id in moderator_ids:
        text_to_publish = message.text  # Получите текст, который ввел модератор

        # Отправьте текст в другую группу
        bot.send_message(other_group_chat_id, text_to_publish)
        bot.send_message(user_id, "Сообщение успешно опубликовано в другой группе.")
    else:
        bot.send_message(user_id, "У вас нет прав для выполнения этой команды.")


# Функция для проверки количества слов в тексте
def check_word_count(text, min_count, max_count):
    words = text.split()
    if len(words) < min_count:
        return f'Сообщение содержит менее {min_count} слов. Увеличьте количество слов.'
    if len(words) > max_count:
        return f'Сообщение содержит более {max_count} слов. Уменьшите количество слов.'
    return None


user_cooldown = {}
@bot.message_handler(content_types=['text', 'photo', 'video'], func=lambda message: message.chat.type == 'private' and message.from_user.id not in moderator_ids)
def send_request(message):
    user_id = message.from_user.id

    text = message.text if message.text else message.caption

    if text and text.lower() == 'выход в главное меню':
        bot.send_message(message.chat.id, "Выход в главное меню", reply_markup=start_menu_keyboard)
    else:
        # Проверяем, находится ли пользователь в режиме ожидания
        cooldown_value = get_cooldown_value_from_db()
        if user_id in user_cooldown and time.time() - user_cooldown[user_id] < cooldown_value:
            cooldown_remaining = int(cooldown_value - (time.time() - user_cooldown[user_id]))
            bot.send_message(message.chat.id, f'Подождите {cooldown_remaining} секунд, прежде чем отправить еще один файл или текст. \n Возвращение в меню', reply_markup=start_menu_keyboard)
            return

        # Инициализируем переменные для хранения содержания файла и текста
        user_message = None
        user_message_photo = None
        user_message_photo = None
        photo_id = None
        video_id = None

        # Проверяем тип сообщения (фото, видео или текст)
        if message.photo:
            photo_id = message.photo[-1].file_id
            caption = message.caption
            user_message_photo = caption
            if not caption:
                bot.send_message(message.chat.id, 'Вы не можете отправить пустую фотографию. Пожалуйста, добавьте подпись к фотографии.')
                return
            error_message = check_word_count(caption, 20, 400)
            user_message = caption
            if error_message:
                bot.send_message(message.chat.id, error_message)
                return
        elif message.video:
            video_id = message.video.file_id
            caption = message.caption
            user_message_video = caption
            if not caption:
                bot.send_message(message.chat.id, 'Вы не можете отправить пустое видео. Пожалуйста, добавьте подпись к видео.')
                return
            error_message = check_word_count(caption, 20, 400)
            if error_message:
                bot.send_message(message.chat.id, error_message)
                return

        # Получаем текст из сообщения
        if text:
            error_message = check_word_count(text, 20, 400)
            if error_message:
                bot.send_message(message.chat.id, error_message)
                return

            user_message = text

        else:
            bot.send_message(message.chat.id, 'Вы можете отправить только изображение (фотографию) в формате JPEG/JPG/PNG, видео в формате MP4 или текст.')

        try:
            if photo_id:
                cursor.execute("INSERT INTO requests (user_id, text, photo, status) VALUES (%s, %s ,%s, 1)", (user_id, user_message_photo, photo_id))
            elif video_id:
                cursor.execute("INSERT INTO requests (user_id, text, video, status) VALUES (%s, %s, %s, 1)", (user_id, user_message_video , video_id))
            elif user_message:
                cursor.execute("INSERT INTO requests (user_id, text, status) VALUES (%s, %s, 1)", (user_id, user_message))

            conn.commit()

            user_cooldown[user_id] = time.time()  # Обновляем время последней отправки для пользователя

            bot.send_message(message.chat.id, 'Спасибо за отправку! Ваш файл или текст будет отправлен модератору и, при одобрении, будет опубликован на канале Kursiv Playground.', reply_markup=start_menu_keyboard)

        except psycopg2.connector.Error as err:
            # Обрабатываем ошибки базы данных здесь
            print(f"Database Error: {err}")



#Раздел модератора
#Функия проверки integer для заполнения данных в базу данных
def is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False
    
#Настройка бота
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'настройка бота' )#and message.from_user.id in moderator_ids)
def settings_menu(message):
    user_id = message.from_user.id

    if user_id in moderator_ids:  # Проверка, что команду отправляет модератор
        # Создаем клавиатуру на основе списка кнопок
        settings_buttons = ["Добавить модератора", "Изменить группу", "Изменить интервал отправки заявок", "Вернуться Назад"]
        settings_keyboard = create_keyboard(settings_buttons)

        # Отправляем сообщение с этой клавиатурой
        bot.send_message(message.chat.id, "Выберите действие:", reply_markup=settings_keyboard)
    else:
        bot.send_message(message.chat.id, "У вас нет доступа к настройкам бота.")


# Обновить модераторский список
def update_moderator_ids():
    cursor.execute("SELECT moder_id FROM moderators")
    moderator_records = cursor.fetchall()
    moderator_ids = [record[0] for record in moderator_records]
    return moderator_ids


# Добавить модератора
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'добавить модератора')  # and message.from_user.id in moderator_ids)
def add_mod(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    button_exit = types.KeyboardButton(text='Вернуться Назад')
    markup.add(button_exit)

    if user_id in moderator_ids:  # Проверка, что команду отправляет модератор
        bot.send_message(user_id, "Введите Chat ID Модератора: \n Чтобы получить ID модератора, пройдите по ссылке \n @getmyid_bot \n Пример: 5746051320 \n или нажмите на кнопку '⬅️ Вернуться Назад'",reply_markup=markup)
        bot.register_next_step_handler(message, mod_add)
    else:
        bot.send_message(user_id, "У вас нет прав для выполнения этой команды.")

def mod_add(message):
    moder_int = message.text  # замена имени переменной здесь
    user_id = message.from_user.id

    if moder_int.lower() == 'вернуться Назад':
        bot.send_message(user_id, "Выход в меню модератора", reply_markup=moderator_keyboard)
        return

    # Проверка, является ли moder_int целым числом
    if not moder_int.isdigit():
        bot.send_message(user_id, "Пожалуйста, введите корректный ID модератора (целое число).")
        bot.register_next_step_handler(message, mod_add)
        return

    try:
        # Использование параметризованного запроса для вставки модератора
        cursor.execute("INSERT INTO moderators (moder_id) VALUES (%s)", (moder_int,))  # замена имени переменной здесь
        conn.commit()
        bot.send_message(user_id, "Модератор успешно добавлен", reply_markup=moderator_keyboard)
        bot.send_message(moder_int, "Вы теперь модератор!", reply_markup=moderator_keyboard)

        # Обновить переменную moderator_ids
        global moderator_ids
        moderator_ids = update_moderator_ids()
    except psycopg2.connector.Error as err:
        # Обработка ошибки базы данных, например, нарушение целостности и т. д.
        print("Database Error:", err)

# Функция для изменения группы
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'изменить группу')  # and message.from_user.id in moderator_ids)
def add_group(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    button_exit = types.KeyboardButton(text='Вернуться Назад')
    markup.add(button_exit)


    if user_id in moderator_ids:  # проверка, что команду отправляет модератор
        bot.send_message(user_id, "Введите Chat ID Канала для Публикаций: \n Чтобы узнать ID группы необходимо добавить данного Бота в канал, выдать разрешение на все функции и написать команду /get в группу.\n Пример: -1001965855662 \n или нажмите на кнопку 'Вернуться Назад'",reply_markup=markup)
        bot.register_next_step_handler(message, group_add)
    else:
        bot.send_message(user_id, "У вас нет прав для выполнения этой команды.")

# Функция для проверки, что текст можно преобразовать в int
def is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False

# Функция для обновления группы
def update_group_chat_id(new_chat_id):
    cursor.execute('''
        UPDATE "groups"
        SET group_id = %s
        WHERE id = 1;
    ''', (new_chat_id,))
    conn.commit()  # Сохранение изменений в базе данных

def group_add(message):
    text = message.text
    user_id = message.from_user.id

    if text.lower() == 'вернуться назад':
        bot.send_message(user_id, "Выход в меню модератора", reply_markup=moderator_keyboard)
        return

    if is_int(text):
        # Преобразование в целое число и обновление группы
        new_chat_id = int(text)
        update_group_chat_id(new_chat_id)

        # Обновление переменной other_group_chat_id
        global other_group_chat_id
        other_group_chat_id = new_chat_id

        # Уведомление модератора об изменении группы
        bot.send_message(user_id, "Группа изменена на чат с ID " + str(other_group_chat_id), reply_markup=moderator_keyboard)
    else:
        # Неверный ввод, уведомление модератора
        bot.send_message(user_id, "Введенный текст не является целым числом. Пожалуйста, введите правильный chatid.")
        bot.register_next_step_handler(message, group_add)


# Функция для изменения cooldown
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'Изменить интервал отправки заявок')  # and message.from_user.id in moderator_ids)
def add_cooldown(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    button_exit = types.KeyboardButton(text='Вернуться Назад')
    markup.add(button_exit)

    if user_id in moderator_ids:  # проверка, что команду отправляет модератор
        bot.send_message(user_id, "Введите новое значение интервала отправки новых заявок в секундах. \n или нажмите кнопку 'Вернуться Назад'",reply_markup=markup)
        bot.register_next_step_handler(message, set_cooldown)
    else:
        bot.send_message(user_id, "У вас нет прав для выполнения этой команды.")

# Функция для обновления cooldown
def update_cooldown(new_cooldown):
    cursor.execute('''
        UPDATE "cooldown"
        SET cooldown_value = %s
        WHERE id = 1;
    ''', (new_cooldown,))
    conn.commit()  # Сохранение изменений в базе данных

def set_cooldown(message):
    text = message.text
    user_id = message.from_user.id

    if text.lower() == 'Вернуться назад':
        bot.send_message(user_id, "Выход в меню модератора", reply_markup=moderator_keyboard)
        return

    if is_int(text):
        # Преобразование в целое число и обновление cooldown
        new_cooldown = int(text)
        update_cooldown(new_cooldown)

        # Уведомление модератора об изменении cooldown
        bot.send_message(user_id, "Cooldown изменен на " + str(new_cooldown) + " секунд.", reply_markup=moderator_keyboard)
    else:
        # Неверный ввод, уведомление модератора
        bot.send_message(user_id, "Введенный текст не является целым числом. Пожалуйста, введите правильное значение для cooldown.")
        bot.register_next_step_handler(message, set_cooldown)


#Выход в меню модератора
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'Вернуться назад' )#and message.from_user.id in moderator_ids)
def exit(message):
    user_id = message.from_user.id
    if user_id in moderator_ids:  # Проверка что команду выполняет модератор
        bot.send_message(user_id, "Вы вернулись в главное меню модератора.", reply_markup=moderator_keyboard)
    else:
        bot.send_message(user_id, "У вас нет прав для выполнения этой команды.")


#Публикация на канале
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'публикация на канале')
def request_text_for_publication(message):
    user_id = message.from_user.id

    if user_id not in moderator_ids:
        bot.send_message(user_id, "У вас нет прав для выполнения этой команды.")
        return

    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    button_exit = types.KeyboardButton(text='выход в меню модератора')
    markup.add(button_exit)
    bot.send_message(message.chat.id, "Введите текст для публикации или нажмите на кнопку для выхода в меню модератора", reply_markup=markup)

    # Регистрация следующего шага
    bot.register_next_step_handler(message, publish_text_to_group)

def publish_text_to_group(message):
    user_id = message.from_user.id
    text_to_publish = message.text or message.caption

    if text_to_publish and text_to_publish.lower() == 'Вернуться Назад':
            bot.send_message(message.chat.id, "Выход в меню модератор", reply_markup=moderator_keyboard)
            return

    if user_id in moderator_ids:
        try:
            if message.photo:
                photo_id = message.photo[-1].file_id
                bot.send_photo(other_group_chat_id, photo_id, caption=text_to_publish)
            elif message.video:
                video_id = message.video.file_id
                bot.send_video(other_group_chat_id, video_id, caption=text_to_publish)
            elif text_to_publish:
                bot.send_message(other_group_chat_id, text_to_publish)
        except Exception as e:
            print(f"Error sending message to {other_group_chat_id}: {e}")

        if message.photo:
            bot.send_message(message.chat.id, "Публикация выполнена. Отправлено фото.")
        elif message.video:
            bot.send_message(message.chat.id, "Публикация выполнена. Отправлено видео.")
        elif text_to_publish:
            bot.send_message(message.chat.id, f"Публикация выполнена. Отправлено сообщение:\n{text_to_publish}")
        else:
            bot.send_message(message.chat.id, "Неизвестный тип контента. Публикация не выполнена.")
            bot.register_next_step_handler(message, request_text_for_publication)
    else:
        bot.send_message(user_id, "У вас нет прав для выполнения этой команды.")



#Рассылка сообщений
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text and message.text.lower() == 'рассылка')
def send_all_message(message):
    user_id = message.from_user.id

    if user_id not in moderator_ids:
        bot.send_message(user_id, "У вас нет прав для выполнения этой команды.")
        return

    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    button_exit = types.KeyboardButton(text='выход в меню модератора')
    markup.add(button_exit)
    bot.send_message(message.chat.id, Введите текст и прикрепите медиа-файлы, чтобы осуществить рассылку всем пользователям Бота. \n или нажмите кнопку 'Вернуться Назад' ", reply_markup=markup)

    # После этого, регистрируем следующий шаг
    bot.register_next_step_handler(message, send_message_to_all)


def send_message_to_all(message):
    user_id = message.from_user.id
    text = message.text or message.caption

    if text and text.lower() == 'Вернуться Назад':
        bot.send_message(message.chat.id, "Выход в меню модератор", reply_markup=moderator_keyboard)
        return

    if user_id in moderator_ids:
        user_ids = get_all_users()

        for uid in user_ids:
            try:
                if message.photo:
                    photo_id = message.photo[-1].file_id
                    bot.send_photo(uid, photo_id, caption=text)

                elif message.video:
                    video_id = message.video.file_id
                    bot.send_video(uid, video_id, caption=text)

                elif text:
                    bot.send_message(uid, text)

            except Exception as e:
                print(f"Error sending message to {uid}: {e}")

        if message.photo:
            bot.send_message(message.chat.id, "Рассылка выполнена. Отправлено фото.")
        elif message.video:
            bot.send_message(message.chat.id, "Рассылка выполнена. Отправлено видео.")
        elif text:
            bot.send_message(message.chat.id, f"Рассылка выполнена. Отправлено сообщение:\n{text}")
        else:
            bot.send_message(message.chat.id, "Неизвестный тип контента. Рассылка не выполнена.")
            bot.register_next_step_handler(message, send_all_message)

    else:
        bot.send_message(user_id, "У вас нет прав для выполнения этой команды.")


# Рассмотрение заявок 
# создание инлайн-кнопок "Одобрить" и "Отклонить" под каждой заявкой
def create_request_buttons(request_id):
    markup = types.InlineKeyboardMarkup()
    true_button = types.InlineKeyboardButton("Одобрить", callback_data=f"true_{request_id}")
    false_button = types.InlineKeyboardButton("Отклонить", callback_data=f"false_{request_id}")
    markup.add(true_button, false_button)
    return markup

# Функция для получение имени пользовтеля
def get_user_name_by_id(user_id):
    user = bot.get_chat(user_id)
    user_name = user.first_name  # You can also use user.last_name for the last name
    return user_name

# добавление кнопки для каждой заявки
@bot.message_handler(func=lambda message: message.chat.type == 'private' and message.text.lower() == 'посмотреть заявки') #and message.from_user.id in moderator_ids)
def process_requests(message):
    moder_id = message.from_user.id

    if moder_id in moderator_ids and message.text.lower() == 'посмотреть заявки':
        cursor.execute("SELECT id, user_id, text, photo, video, time FROM requests WHERE status = 1")
        requests = cursor.fetchall()

        if not requests:
            bot.send_message(moder_id, "Нет новых заявок")
        else:
            for request in requests:
                request_id, user_id, text, photo_id, video_id, timestamp = request
                formatted_timestamp = timestamp.strftime("%d/%m/%Y %H:%M:%S")
                request_markup = create_request_buttons(request_id)
                user_name = get_user_name_by_id(user_id)

                # Check if there is a photo or video in the request and send it accordingly
                if photo_id:
                    bot.send_photo(moder_id, photo_id, caption=f"Заявка #{request_id}\nПользователь: {user_name}\nДата: {formatted_timestamp}\nСодержание: {text}", reply_markup=request_markup)
                elif video_id:
                    bot.send_video(moder_id, video_id, caption=f"Заявка #{request_id}\nПользователь: {user_name}\nДата: {formatted_timestamp}\nСодержание: {text}", reply_markup=request_markup)
                else:
                    # If there is no photo or video, just send the text
                    bot.send_message(moder_id, f"Заявка #{request_id}\nПользователь: {user_name}\nДата: {formatted_timestamp}\nСодержание: {text}", reply_markup=request_markup)
    else:
          bot.send_message(moder_id, "У вас нет прав для выполнения этой команды.")


# Обработка нажатия на кнопки "Одобрить" и "Отклонить"
@bot.callback_query_handler(func=lambda call: call.data.startswith(('true_', 'false_')))
def handle_request_action(call):
    action, request_id = call.data.split('_')
    request_id = int(request_id)

    if action == 'true':
        cursor.execute("SELECT text, photo, video, user_id FROM requests WHERE id = %s", (request_id,))
        request_data = cursor.fetchone()
        request_text, photo_id, video_id, user_id = request_data[0], request_data[1], request_data[2], request_data[3]

        # Отметьте заявку как одобренную
        cursor.execute("UPDATE requests SET status = 2 WHERE id = %s", (request_id,))
        conn.commit()

        # Отправьте медиа или текст заявки в другой группе после одобрения
        if photo_id:  # Если есть фото
            bot.send_photo(other_group_chat_id, photo_id, caption=f"Заявка #{request_id} одобрена. Текст заявки:\n{request_text}")
        elif video_id:  # Если есть видео
            bot.send_video(other_group_chat_id, video_id, caption=f"Заявка #{request_id} одобрена. Текст заявки:\n{request_text}")
        else:  # Если есть только текст
            bot.send_message(other_group_chat_id, f"Заявка #{request_id} одобрена. Текст заявки:\n{request_text}")

        # Уведомите пользователя о решении
        bot.send_message(user_id, f"Ваша заявка #{request_id} была одобрена.")
        bot.send_message(call.from_user.id, f"Заявка #{request_id} была одобрена.")
        # Удалите кнопки после обработки действия
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)

        # Отметьте заявку как одобренную
        cursor.execute("UPDATE requests SET status = 2 WHERE id = %s", (request_id,))
        conn.commit()

    elif action == 'false':
        cursor.execute("SELECT user_id FROM requests WHERE id = %s", (request_id,))
        user_id = cursor.fetchone()[0]

        # Запросите причину отказа у модератора
        bot.send_message(call.from_user.id, f"Заявка #{request_id} отклонена. Пожалуйста, укажите причину отказа в ответ на данное сообщение.")

        # Удалите кнопки после обработки действия
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)

        # обработчик сообщений для получения причины отклонения от модератора.
        bot.register_next_step_handler(call.message, save_rejection_reason, request_id, user_id)

# Define the save_rejection_reason function with an additional request_id and user_id parameter
def save_rejection_reason(message, request_id, user_id):
    rejection_reason = message.text
    try:
        # Добавьте информацию о статусе отказа и тексте причины в базу данных
        cursor.execute("UPDATE requests SET status = 3, rejection_reason = %s WHERE id = %s",
                       (rejection_reason, request_id))
        conn.commit()
        bot.send_message(message.chat.id, f"Причина отказа для заявки #{request_id} сохранена.")

        # Уведомите пользователя о решении
        bot.send_message(user_id, f"Ваша заявка #{request_id} была отклонена по следующей причине: {rejection_reason}")
    except Exception as e:
        bot.send_message(message.chat.id, f"Произошла ошибка при сохранении причины отказа: {str(e)}")



import cProfile

def my_function():
    total = 0
    for i in range(1000000):
        total += i
    return total

if __name__ == '__main__':
    bot.infinity_polling()
    logging.info('Бот успешно запущен')
    profiler = cProfile.Profile()
    profiler.enable()
    result = my_function()
    profiler.disable()
    profiler.print_stats(sort='cumulative')
