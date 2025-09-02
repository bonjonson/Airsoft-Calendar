import json
import logging
import html
import re
import signal
import sys
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    ConversationHandler, ContextTypes, filters
)

# Загрузка переменных окружения
from dotenv import load_dotenv
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальная переменная для управления остановкой
application_instance = None

# Состояния для ConversationHandler
EVENT_NAME, EVENT_DATE, EVENT_ORGANIZER, EVENT_PRICE, EVENT_PLACE, EVENT_LINK = range(6)
DELETE_EVENT, CONFIRM_DELETE = range(6, 8)

# Файл для хранения данных
JSON_FILE = 'calendar.json'
USERS_FILE = 'users.json'  # Файл для хранения пользователей и их ролей

# Роли пользователей
ROLE_USER = 'user'
ROLE_COMMANDER = 'commander'
ROLE_ADMIN = 'admin'

# Клавиатуры
main_keyboard = [['События']]
events_keyboard_user = [['Показать события'], ['Назад']]
events_keyboard_commander = [['Сообщить о событии', 'Показать события'], ['Назад']]
events_keyboard_admin = [['Сообщить о событии', 'Показать события'], ['Удалить событие'], ['Назад']]
delete_keyboard = [['Отменить удаление']]
confirm_delete_keyboard = [['Да, удалить', 'Нет, отменить']]

def load_events():
    """Загрузка событий из файла"""
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"events": []}

def save_events(data):
    """Сохранение событий в файл"""
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_users():
    """Загрузка пользователей из файла"""
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Создаем файл с администратором по умолчанию
        default_users = {
            "users": {
                "1234567": {"role": ROLE_ADMIN, "username": "admin"}  # Замените на ваш ID
            }
        }
        save_users(default_users)
        return default_users

def save_users(data):
    """Сохранение пользователей в файл"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_role(user_id):
    """Получение роли пользователя"""
    users_data = load_users()
    user_id_str = str(user_id)
    
    if user_id_str in users_data.get("users", {}):
        return users_data["users"][user_id_str]["role"]
    
    # Если пользователь не найден, регистрируем его как обычного пользователя
    return register_new_user(user_id)

def register_new_user(user_id):
    """Регистрация нового пользователя с ролью 'user'"""
    users_data = load_users()
    user_id_str = str(user_id)
    
    if user_id_str not in users_data.get("users", {}):
        users_data.setdefault("users", {})[user_id_str] = {
            "role": ROLE_USER,
            "username": f"user_{user_id}"
        }
        save_users(users_data)
    
    return ROLE_USER

def has_permission(user_id, required_role):
    """Проверка прав пользователя"""
    user_role = get_user_role(user_id)
    
    # Определяем иерархию ролей
    role_hierarchy = {ROLE_USER: 1, ROLE_COMMANDER: 2, ROLE_ADMIN: 3}
    
    user_level = role_hierarchy.get(user_role, 0)
    required_level = role_hierarchy.get(required_role, 0)
    
    return user_level >= required_level

async def check_permission(update: Update, context: ContextTypes.DEFAULT_TYPE, required_role):
    """Проверка прав и отправка сообщения об ошибке если нет доступа"""
    user_id = update.effective_user.id
    
    if not has_permission(user_id, required_role):
        await update.message.reply_text(
            "❌ У вас недостаточно прав для выполнения этой операции.",
            reply_markup=get_events_keyboard(user_id)
        )
        return False
    return True

def get_events_keyboard(user_id):
    """Получение клавиатуры в зависимости от роли пользователя"""
    user_role = get_user_role(user_id)
    
    if user_role == ROLE_ADMIN:
        return ReplyKeyboardMarkup(events_keyboard_admin, resize_keyboard=True)
    elif user_role == ROLE_COMMANDER:
        return ReplyKeyboardMarkup(events_keyboard_commander, resize_keyboard=True)
    else:
        return ReplyKeyboardMarkup(events_keyboard_user, resize_keyboard=True)

def validate_date(date_str):
    """Проверка формата даты ДД.ММ.ГГГГ"""
    try:
        datetime.strptime(date_str, '%d.%m.%Y')
        return True
    except ValueError:
        return False

def validate_price(price_str):
    """Проверка формата цены"""
    price_str = price_str.replace(' ', '')
    
    if price_str.isdigit():
        return True
    
    if '-' in price_str:
        parts = price_str.split('-')
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return True
    
    return False

def format_price(price_str):
    """Форматирование цены с добавлением 'рублей'"""
    price_str = price_str.replace(' ', '')
    
    if '-' in price_str:
        min_price, max_price = price_str.split('-')
        return f"{min_price}-{max_price} рублей"
    else:
        return f"{price_str} рублей"

def find_event_by_name(event_name):
    """Поиск события по названию"""
    data = load_events()
    events = data.get('events', [])
    
    for event in events:
        if event['name'].lower() == event_name.lower():
            return event
    return None

def delete_event_by_name(event_name):
    """Удаление события по названию"""
    data = load_events()
    events = data.get('events', [])
    
    initial_count = len(events)
    data['events'] = [event for event in events if event['name'].lower() != event_name.lower()]
    
    if len(data['events']) < initial_count:
        save_events(data)
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    user_role = get_user_role(user_id)
    
    reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
    await update.message.reply_text(
        f"Добро пожаловать! Ваша роль: {user_role}\nВыберите действие:",
        reply_markup=reply_markup
    )

async def stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Остановка бота (только для администраторов)"""
    user_id = update.effective_user.id
    
    if not await check_permission(update, context, ROLE_ADMIN):
        return
    
    logger.info(f"Администратор {user_id} запросил остановку бота")
    
    await update.message.reply_text(
        "Останавливаю бота...",
        reply_markup=ReplyKeyboardRemove()
    )
    
    global application_instance
    if application_instance:
        await application_instance.stop()
        await application_instance.shutdown()
    
    sys.exit(0)

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик главного меню"""
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == 'События':
        reply_markup = get_events_keyboard(user_id)
        await update.message.reply_text(
            "Управление событиями:",
            reply_markup=reply_markup
        )

async def handle_events_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик меню событий"""
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == 'Сообщить о событии':
        if not await check_permission(update, context, ROLE_COMMANDER):
            return ConversationHandler.END
            
        await update.message.reply_text(
            "Введите название события:",
            reply_markup=ReplyKeyboardRemove()
        )
        return EVENT_NAME
        
    elif text == 'Показать события':
        await show_events(update, context)
        return ConversationHandler.END
        
    elif text == 'Удалить событие':
        if not await check_permission(update, context, ROLE_ADMIN):
            return ConversationHandler.END
            
        await update.message.reply_text(
            "Введите название события для удаления:",
            reply_markup=ReplyKeyboardMarkup(delete_keyboard, resize_keyboard=True)
        )
        return DELETE_EVENT
        
    elif text == 'Назад':
        reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

async def delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление события по названию"""
    user_id = update.effective_user.id
    
    if not await check_permission(update, context, ROLE_ADMIN):
        return ConversationHandler.END
        
    text = update.message.text
    
    if text == 'Отменить удаление':
        reply_markup = get_events_keyboard(user_id)
        await update.message.reply_text(
            "Удаление отменено.",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    
    event_name = text.strip()
    
    if not event_name:
        await update.message.reply_text("Название события не может быть пустым. Введите название события для удаления:")
        return DELETE_EVENT
    
    event = find_event_by_name(event_name)
    
    if event:
        message = (
            f"🗑️ <b>Удаление события:</b>\n\n"
            f"🎉 <b>{html.escape(event['name'])}</b>\n"
            f"📅 <b>Дата:</b> {html.escape(event['date'])}\n"
            f"👥 <b>Организатор:</b> {html.escape(event['organisators'])}\n\n"
            f"Вы уверены, что хотите удалить это событие?"
        )
        
        context.user_data['event_to_delete'] = event_name
        await update.message.reply_text(
            message,
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup(confirm_delete_keyboard, resize_keyboard=True)
        )
        return CONFIRM_DELETE
    
    else:
        await update.message.reply_text(
            f"Событие с названием '{event_name}' не найдено.\n"
            f"Введите название события для удаления:",
            reply_markup=ReplyKeyboardMarkup(delete_keyboard, resize_keyboard=True)
        )
        return DELETE_EVENT

async def confirm_delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления события"""
    user_id = update.effective_user.id
    
    if not await check_permission(update, context, ROLE_ADMIN):
        return ConversationHandler.END
        
    text = update.message.text
    event_name_to_delete = context.user_data.get('event_to_delete')
    
    if text == 'Да, удалить':
        if delete_event_by_name(event_name_to_delete):
            reply_markup = get_events_keyboard(user_id)
            await update.message.reply_text(
                f"✅ Событие '{event_name_to_delete}' успешно удалено!",
                reply_markup=reply_markup
            )
        else:
            reply_markup = get_events_keyboard(user_id)
            await update.message.reply_text(
                f"❌ Ошибка при удалении события '{event_name_to_delete}'.",
                reply_markup=reply_markup
            )
    elif text == 'Нет, отменить':
        reply_markup = get_events_keyboard(user_id)
        await update.message.reply_text(
            "Удаление отменено.",
            reply_markup=reply_markup
        )
    else:
        reply_markup = get_events_keyboard(user_id)
        await update.message.reply_text(
            "Неизвестная команда. Удаление отменено.",
            reply_markup=reply_markup
        )
    
    if 'event_to_delete' in context.user_data:
        del context.user_data['event_to_delete']
    
    return ConversationHandler.END

async def event_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение названия события"""
    user_id = update.effective_user.id
    
    if not await check_permission(update, context, ROLE_COMMANDER):
        return ConversationHandler.END
        
    name = update.message.text.strip()
    
    if not name:
        await update.message.reply_text("Название события не может быть пустым. Попробуйте еще раз:")
        return EVENT_NAME
    
    context.user_data['event'] = {'name': name}
    await update.message.reply_text("Введите дату события (в формате ДД.ММ.ГГГГ):")
    return EVENT_DATE

async def event_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение даты события"""
    date = update.message.text.strip()
    
    if not validate_date(date):
        await update.message.reply_text("Неверный формат даты. Используйте ДД.ММ.ГГГГ (например, 25.12.2024):")
        return EVENT_DATE
    
    context.user_data['event']['date'] = date
    await update.message.reply_text("Введите название организатора:")
    return EVENT_ORGANIZER

async def event_organizer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение организатора"""
    organizer = update.message.text.strip()
    
    if not organizer:
        await update.message.reply_text("Название организатора не может быть пустым. Попробуйте еще раз:")
        return EVENT_ORGANIZER
    
    context.user_data['event']['organisators'] = organizer
    await update.message.reply_text("Введите цену за участие (число или диапазон, например: 500 или 300-1000, если событие бесплатное - укажите 0):")
    return EVENT_PRICE

async def event_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение цены"""
    price = update.message.text.strip()
    
    if not validate_price(price):
        await update.message.reply_text("Неверный формат цены. Используйте число (500) или диапазон (300-1000):")
        return EVENT_PRICE
    
    context.user_data['event']['price_raw'] = price
    context.user_data['event']['price'] = format_price(price)
    
    await update.message.reply_text("Введите место проведения:")
    return EVENT_PLACE

async def event_place(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение места проведения"""
    place = update.message.text.strip()
    
    if not place:
        await update.message.reply_text("Место проведения не может быть пустым. Попробуйте еще раз:")
        return EVENT_PLACE
    
    context.user_data['event']['place'] = place
    await update.message.reply_text("Введите ссылку на событие:")
    return EVENT_LINK

async def event_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение ссылки и сохранение события"""
    link = update.message.text.strip()
    
    if not link:
        await update.message.reply_text("Ссылка не может быть пустой. Попробуйте еще раз:")
        return EVENT_LINK
    
    context.user_data['event']['link'] = link
    
    data = load_events()
    data['events'].append(context.user_data['event'])
    save_events(data)
    
    user_id = update.effective_user.id
    reply_markup = get_events_keyboard(user_id)
    await update.message.reply_text(
        "Событие успешно добавлено! ✅",
        reply_markup=reply_markup
    )
    
    context.user_data.clear()
    return ConversationHandler.END

async def show_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все события"""
    data = load_events()
    events = data.get('events', [])
    
    if not events:
        await update.message.reply_text("Событий пока нет.")
        return
    
    for event in events:
        message = (
            f"🎉 <b>{html.escape(event['name'])}</b>\n\n"
            f"📅 <b>Дата:</b> {html.escape(event['date'])}\n"
            f"👥 <b>Организатор:</b> {html.escape(event['organisators'])}\n"
            f"💰 <b>Цена:</b> {html.escape(event['price'])}\n"
            f"📍 <b>Место:</b> {html.escape(event['place'])}\n"
            f"🔗 <b>Ссылка:</b> {html.escape(event['link'])}"
        )
        
        await update.message.reply_text(
            message,
            parse_mode='HTML',
            disable_web_page_preview=True
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена операции"""
    user_id = update.effective_user.id
    reply_markup = get_events_keyboard(user_id)
    await update.message.reply_text(
        "Операция отменена.",
        reply_markup=reply_markup
    )
    context.user_data.clear()
    return ConversationHandler.END

def signal_handler(signum, frame):
    """Обработчик сигналов для корректного завершения"""
    logger.info(f"Получен сигнал {signum}, останавливаю бота...")
    global application_instance
    if application_instance:
        # Используем create_task для асинхронного завершения
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application_instance.stop())
        loop.run_until_complete(application_instance.shutdown())
        loop.close()
    sys.exit(0)

def main():
    """Основная функция"""
    global application_instance
    
    # Получаем токен из переменных окружения
    BOT_TOKEN = os.getenv('API_TOKEN')
    if not BOT_TOKEN:
        print("Ошибка: Не найден API_TOKEN в переменных окружения")
        sys.exit(1)
    
    # Создаем Application с токеном
    application = Application.builder().token(BOT_TOKEN).build()
    application_instance = application
    
    # Инициализируем файл пользователей
    load_users()
    
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # ConversationHandler для добавления событий
    add_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Сообщить о событии$'), handle_events_menu)],
        states={
            EVENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_name)],
            EVENT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_date)],
            EVENT_ORGANIZER: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_organizer)],
            EVENT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_price)],
            EVENT_PLACE: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_place)],
            EVENT_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, event_link)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # ConversationHandler для удаления событий
    delete_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Удалить событие$'), handle_events_menu)],
        states={
            DELETE_EVENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_event)],
            CONFIRM_DELETE: [MessageHandler(filters.Regex('^(Да, удалить|Нет, отменить)$'), confirm_delete_event)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_bot))
    application.add_handler(add_conv_handler)
    application.add_handler(delete_conv_handler)
    application.add_handler(MessageHandler(filters.Regex('^События$'), handle_main_menu))
    application.add_handler(MessageHandler(filters.Regex('^(Показать события|Назад)$'), handle_events_menu))
    
    print("Бот запущен...")
    print("Для остановки бота используйте команду /stop в Telegram или Ctrl+C в терминале")
    
    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()