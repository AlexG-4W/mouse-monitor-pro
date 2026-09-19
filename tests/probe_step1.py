"""Шаг 1: три замера одним заходом. ВНЕ приложения, ничего не интегрирует.

    python tests/probe_step1.py

В run_all.py НЕ включается: 1a и 1c требуют живой мыши под рукой.

================================ ИТОГ ЗАМЕРОВ =================================

1b. ЧТЕНИЕ HID-КОЛЛЕКЦИЙ МЫШИ ЗАПРЕЩЕНО. Подтверждено, путь закрыт.
    Все 4 коллекции с usage 01/02 (мышь) вернули ERROR_ACCESS_DENIED на
    CreateFileW с GENERIC_READ. Клавиатурные -- тоже. При этом 19 прочих
    коллекций того же железа открылись, включая вендорские FF00 приёмника
    Logitech. Запрет по классу устройства, а не по занятости.
    Побочно: VID_062A&PID_38B3, которую WMI числит указывающим устройством и
    которая молчала во всех прогонах Raw Input, представляется системой как
    "USB 2.4G Keyboard" -- клавиатурный приёмник с мышиной коллекцией в
    дескрипторе. Конкретный механизм того, почему запись в
    Win32_PointingDevice не означает живого устройства.

1a. ХУК РАЗРЕШАЕТ ПЕРИОД ~1 мс. Оценка частоты репортов состоятельна.
    Замер при 741 px/с: 2646 событий за 10 с, 2625 интервалов короче 50 мс.
    Гистограмма с шагом 0.1 мс даёт не просто моду, а ГАРМОНИЧЕСКУЮ ЛЕСТНИЦУ:

        0.9-1.1 мс  59.3%   <- основной период
        1.9-2.1 мс  10.5%   <- 2x
        2.9-3.1 мс   3.9%   <- 3x
        3.9-4.1 мс   1.6%   <- 4x
        5.0-5.1 мс   0.5%   <- 5x

    Кратные пики -- подпись периодического источника, у которого часть
    репортов не сдвигает курсор на пиксель и потому не порождает события.
    Медиана 1.02 мс, 10-й процентиль 0.91 мс. Период ~1.0 мс => ~950-1000 Гц.

    ВАЖНО ПРО МЕТОДИКУ. Первый прогон при 17 событиях/с дал острую моду
    7.0-7.1 мс с удвоением на 90-м процентиле -- и это было бы принято за
    период устройства. На медленном движении гистограмма показывает
    зернистость пересечения границ пикселей, а не репорты. Поэтому здесь
    жёсткий отбор выборки: старт только при 150 событиях за 0.5 с (300/с),
    отбраковка окна при среднем темпе ниже 200/с, и печать скорости в px/с,
    чтобы условия замера стояли рядом с результатом.

1c. КОЛЕСО ОБЫЧНОЕ, pynput ничего не теряет -- но выборка тонкая.
    4 тика на медленной прокрутке: сырое usButtonData ровно 120 у всех,
    pynput отдал dy=1, обнулённых вызовов нет. Быстрая фаза не набрала ни
    одного тика. Колёс высокого разрешения на этой машине не обнаружено.
    Вывод верен для ЭТОГО железа. Для публичного инструмента риск остаётся:
    у другого пользователя колесо со свободным ходом даст сырые приращения
    меньше 120, а pynput делит на WHEEL_DELTA целочисленно (mouse/_win32.py:
    dd = SHORT(mouseData >> 16) // 120), то есть вернёт dy = 0 без ошибки.
    Детектор износа энкодера обязан это переживать независимо от результата
    здесь.

=============================== ЧТО ЭТО ЗНАЧИТ ================================

Идея "оценка периода репортов по гистограмме интервалов" -- подтверждена и
дешевле, чем казалась: данные уже в потоке, отдельный API не нужен.
Идея "детектор износа энкодера колеса на on_scroll" -- проходит по цене,
с оговоркой про dy == 0.
Идея "читать HID напрямую" -- закрыта окончательно.

Все вызовы ctypes с restype/argtypes: в этом проекте дважды ловили усечение
pointer-sized значений до 32 бит на x64.
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rawinput_probe as RI          # noqa: E402  (готовые структуры Raw Input)

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)


# ============================ 1b: HID-пути ==================================

class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD),
                ("Reserved", ctypes.POINTER(wintypes.ULONG))]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG),
                ("VendorID", wintypes.USHORT),
                ("ProductID", wintypes.USHORT),
                ("VersionNumber", wintypes.USHORT)]


# HIDP_CAPS длиннее, чем нам нужно; берём первые два поля и место под остальное.
class HIDP_CAPS_HEAD(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT),
                ("UsagePage", wintypes.USHORT),
                ("rest", ctypes.c_ubyte * 252)]


DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

ERRORS = {0: "OK", 2: "ERROR_FILE_NOT_FOUND", 5: "ERROR_ACCESS_DENIED",
          32: "ERROR_SHARING_VIOLATION", 87: "ERROR_INVALID_PARAMETER",
          123: "ERROR_INVALID_NAME", 1167: "ERROR_DEVICE_NOT_CONNECTED"}

setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                          wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

hid.HidD_GetAttributes.restype = ctypes.c_ubyte
hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetProductString.restype = ctypes.c_ubyte
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetPreparsedData.restype = ctypes.c_ubyte
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.restype = ctypes.c_ubyte
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.restype = ctypes.c_long
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS_HEAD)]

USAGE_NAMES = {(0x01, 0x02): "МЫШЬ",
               (0x01, 0x01): "указатель",
               (0x01, 0x06): "клавиатура",
               (0x01, 0x04): "джойстик",
               (0x01, 0x05): "геймпад",
               (0x0C, 0x01): "consumer control",
               (0x0D, 0x01): "дигитайзер",
               (0x0D, 0x04): "тачскрин",
               (0x0D, 0x05): "ТАЧПАД"}


def hid_paths():
    """Пути ко всем присутствующим HID-интерфейсам."""
    guid = GUID(0x4D1E55B2, 0xF16F, 0x11CF,
                (ctypes.c_ubyte * 8)(0x88, 0xCB, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30))
    handle = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    paths = []
    try:
        index = 0
        while True:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                    handle, None, ctypes.byref(guid), index, ctypes.byref(iface)):
                break
            index += 1
            need = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                handle, ctypes.byref(iface), None, 0, ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value)
            # ЛОВУШКА: cbSize здесь -- размер ЗАГОЛОВКА структуры, а не буфера.
            # На x64 это 8 (DWORD + WCHAR + выравнивание), на x86 -- 6.
            ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = (
                8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6)
            if setupapi.SetupDiGetDeviceInterfaceDetailW(
                    handle, ctypes.byref(iface), buf, need.value, None, None):
                paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(handle)
    return paths


def describe(path):
    """VID/PID, имя и usage через хэндл с НУЛЕВЫМ доступом.

    Открытие с access=0 -- запрос метаданных, а не чтение. Оно разрешено там,
    где чтение запрещено, и именно этим отделяется "устройства не видно" от
    "читать не дают".
    """
    info = {"vid": None, "pid": None, "name": "", "usage": None, "meta_err": 0}
    h = kernel32.CreateFileW(path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE,
                             None, OPEN_EXISTING, 0, None)
    if h == INVALID_HANDLE_VALUE:
        info["meta_err"] = ctypes.get_last_error()
        return info
    try:
        attrs = HIDD_ATTRIBUTES()
        attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
        if hid.HidD_GetAttributes(h, ctypes.byref(attrs)):
            info["vid"], info["pid"] = attrs.VendorID, attrs.ProductID
        name = ctypes.create_unicode_buffer(128)
        if hid.HidD_GetProductString(h, name, ctypes.sizeof(name)):
            info["name"] = name.value
        pre = ctypes.c_void_p()
        if hid.HidD_GetPreparsedData(h, ctypes.byref(pre)):
            try:
                caps = HIDP_CAPS_HEAD()
                if hid.HidP_GetCaps(pre, ctypes.byref(caps)) == 0x00110000:
                    info["usage"] = (caps.UsagePage, caps.Usage)
            finally:
                hid.HidD_FreePreparsedData(pre)
    finally:
        kernel32.CloseHandle(h)
    return info


def try_read(path):
    """Попытка открыть на ЧТЕНИЕ. Возвращает (успех, код ошибки)."""
    h = kernel32.CreateFileW(path, GENERIC_READ,
                             FILE_SHARE_READ | FILE_SHARE_WRITE,
                             None, OPEN_EXISTING, 0, None)
    if h == INVALID_HANDLE_VALUE:
        return False, ctypes.get_last_error()
    kernel32.CloseHandle(h)
    return True, 0


def measure_1b():
    print("=" * 78)
    print("1b. HID-пути: можно ли открыть коллекцию мыши на чтение")
    print("=" * 78)
    paths = hid_paths()
    print("HID-интерфейсов присутствует: %d\n" % len(paths))
    mice_ok = mice_denied = other_ok = other_denied = 0
    for path in paths:
        info = describe(path)
        ok, err = try_read(path)
        usage = info["usage"]
        label = USAGE_NAMES.get(usage, "usage %04X/%04X" % usage if usage else "?")
        is_mouse = usage == (0x01, 0x02)
        if is_mouse:
            mice_ok += ok
            mice_denied += (not ok)
        else:
            other_ok += ok
            other_denied += (not ok)
        vid = "VID_%04X&PID_%04X" % (info["vid"], info["pid"]) if info["vid"] else "?"
        print("  %-22s %-18s %s" % (label, vid, (info["name"] or "")[:32]))
        print("     GENERIC_READ: %-9s %s"
              % ("ОТКРЫЛСЯ" if ok else "ОТКАЗ", "" if ok else
                 "%d (%s)" % (err, ERRORS.get(err, "?"))))
        print("     %s" % path[:110])
    print()
    print("  МЫШИНЫЕ коллекции (usage 01/02): открылось %d, отказ %d"
          % (mice_ok, mice_denied))
    print("  прочие коллекции:                открылось %d, отказ %d"
          % (other_ok, other_denied))
    print()
    if mice_ok == 0 and mice_denied:
        print("  ВЫВОД: чтение мышиных коллекций запрещено -- подозрение из")
        print("         антисписка подтвердилось, путь закрыт.")
    elif mice_ok:
        print("  ВЫВОД: мышиную коллекцию УДАЛОСЬ открыть на чтение -- подозрение")
        print("         не подтвердилось, направление требует отдельной проверки.")


def wait_sustained(box, need, window, timeout, what):
    """Ждёт УСТОЙЧИВОЙ активности, а не одиночного события.

    Старт по первому же событию оказался ошибкой: случайный сдвиг курсора
    открывал окно замера в пустоту, и десять секунд уходили впустую. Здесь
    окно открывается только если за `window` секунд пришло не меньше `need`
    событий, то есть человек действительно занят делом.
    """
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        del box[:]
        time.sleep(window)
        if len(box) >= need:
            return True
    print("!!! %s не дождались за %d с" % (what, timeout))
    return False


# ==================== 1a: гистограмма интервалов ============================

def measure_1a(seconds=10):
    from pynput import mouse
    print()
    print("=" * 78)
    print("1a. Гистограмма межсобытийных интервалов LL-хука")
    print("=" * 78)
    stamps = []
    track = []

    def on_move(x, y, injected=False):
        if not injected:
            stamps.append(time.perf_counter())
            track.append((x, y))

    listener = mouse.Listener(on_move=on_move)
    listener.start()
    print(">>> ДВИГАЙ МЫШЬ БЫСТРО И НЕПРЕРЫВНО. Замер стартует, когда движение")
    print(">>> станет устойчивым, и длится %d с. Ожидание (до 5 мин)..." % seconds)
    sys.stdout.flush()
    # Порог намеренно жёсткий: 150 событий за 0.5 с -- это 300/с, то есть
    # движение, при котором почти каждый репорт сдвигает курсор. На медленном
    # движении гистограмма показывает зернистость пересечения границ пикселей,
    # а не период репортов устройства, и замер бессмыслен.
    MIN_RATE = 200.0
    got, got_track = [], []
    for attempt in range(1, 6):
        if not wait_sustained(stamps, 150, 0.5, 300, "быстрого движения"):
            listener.stop()
            return
        print(">>> ПОЕХАЛИ (попытка %d)" % attempt)
        sys.stdout.flush()
        del stamps[:]
        del track[:]
        time.sleep(seconds)
        got, got_track = list(stamps), list(track)
        rate = len(got) / seconds
        if len(got) >= 500 and rate >= MIN_RATE:
            break
        print(">>> выборка негодная: %d событий, %.0f/с (нужно >= %.0f/с) -- ждём снова"
              % (len(got), rate, MIN_RATE))
        sys.stdout.flush()
    listener.stop()
    stamps = got
    if len(stamps) >= 2 and len(got_track) == len(stamps):
        import math as _m
        path = sum(_m.dist(got_track[i], got_track[i + 1])
                   for i in range(len(got_track) - 1))
        span = stamps[-1] - stamps[0]
        print("  скорость движения при замере: %.0f px/с (путь %.0f px за %.1f с)"
              % (path / span if span else 0, path, span))

    if len(stamps) < 100:
        print("!!! событий слишком мало (%d), выводы делать не на чем" % len(stamps))
        return
    gaps = [(stamps[i + 1] - stamps[i]) * 1000.0 for i in range(len(stamps) - 1)]
    moving = [g for g in gaps if g < 50.0]      # паузы в распределение не входят
    print("  событий: %d за %.1f с -> %.0f/с"
          % (len(stamps), stamps[-1] - stamps[0],
             (len(stamps) - 1) / (stamps[-1] - stamps[0])))
    print("  интервалов всего %d, из них < 50 мс (движение) %d, пауз %d"
          % (len(gaps), len(moving), len(gaps) - len(moving)))

    bins = {}
    for g in moving:
        if g < 10.0:
            bins[int(g * 10)] = bins.get(int(g * 10), 0) + 1
    over = sum(1 for g in moving if g >= 10.0)
    if not bins:
        print("  все интервалы >= 10 мс, моды нет")
        return
    peak = max(bins.values())
    mode_bin = max(bins, key=lambda k: bins[k])
    print()
    print("  шаг 0.1 мс, показаны корзины с долей > 0.5%%:")
    for key in sorted(bins):
        share = bins[key] / len(moving) * 100.0
        if share < 0.5:
            continue
        bar = "#" * max(1, int(bins[key] / peak * 46))
        print("   %5.1f-%4.1f мс | %-46s %5d  %4.1f%%"
              % (key / 10.0, (key + 1) / 10.0, bar, bins[key], share))
    if over:
        print("   %5s>=10 мс | %-46s %5d  %4.1f%%"
              % ("", "", over, over / len(moving) * 100.0))

    ordered = sorted(moving)
    median = ordered[len(ordered) // 2]
    mode_ms = mode_bin / 10.0
    mode_share = bins[mode_bin] / len(moving) * 100.0
    print()
    print("  мода: %.1f-%.1f мс, доля %.1f%%  ->  %.0f Гц, если это период репортов"
          % (mode_ms, mode_ms + 0.1, mode_share,
             1000.0 / (mode_ms + 0.05) if mode_ms else 0))
    print("  медиана: %.2f мс   |   10%%: %.2f мс   90%%: %.2f мс"
          % (median, ordered[len(ordered) // 10], ordered[len(ordered) * 9 // 10]))
    print()
    if mode_share >= 15.0:
        print("  ВЫВОД: мода выражена -- оценка периода репортов осмысленна.")
    else:
        print("  ВЫВОД: выраженной моды нет (доля %.1f%%), распределение размазано."
              % mode_share)
        print("         Оценивать период репортов по этим данным нельзя.")


# ============================ 1c: колесо ====================================

RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HWHEEL = 0x0800


class WheelProbe(RI.RawInputProbe):
    """Тот же зонд, но запоминает СЫРОЕ смещение колеса из RAWMOUSE."""

    def __init__(self):
        super().__init__()
        self.wheel_raw = []

    def _consume(self, raw_input, ts):
        mouse = raw_input.mouse
        if mouse.usButtonFlags & (RI_MOUSE_WHEEL | RI_MOUSE_HWHEEL):
            # usButtonData -- USHORT, а смещение знаковое.
            self.wheel_raw.append(ctypes.c_short(mouse.usButtonData).value)
        return super()._consume(raw_input, ts)


def measure_1c(slow=8, fast=8):
    from pynput import mouse
    print()
    print("=" * 78)
    print("1c. Колесо: сырое смещение против того, что отдаёт pynput")
    print("=" * 78)
    print("  WHEEL_DELTA = 120. pynput делит на него ЦЕЛОЧИСЛЕННО, поэтому")
    print("  сырое смещение меньше 120 превращается в 0.")
    pyn = []

    def on_scroll(x, y, dx, dy, injected=False):
        pyn.append((dx, dy, injected))

    probe = WheelProbe()
    probe.mode = "handler"
    probe.use_buffer = False
    probe.start()
    listener = mouse.Listener(on_scroll=on_scroll)
    listener.start()
    print()
    print(">>> КРУТИ КОЛЕСО. Замер стартует от первого тика.")
    print(">>>   %d с МЕДЛЕННО, по одному щелчку" % slow)
    print(">>>   %d с БЫСТРО, размашисто" % fast)
    print(">>> Ожидание...")
    sys.stdout.flush()

    # Прокрутка редкая по природе: три тика за две секунды -- уже "крутят".
    deadline = time.perf_counter() + 300
    started = False
    while time.perf_counter() < deadline:
        del pyn[:]
        del probe.wheel_raw[:]
        probe.pump(2.0)
        if len(pyn) >= 3 or len(probe.wheel_raw) >= 3:
            started = True
            break
    if not started:
        print("!!! колесо не крутили за 5 мин")
        listener.stop()
        probe.stop()
        return
    print(">>> ПОЕХАЛИ: МЕДЛЕННО")
    sys.stdout.flush()
    del pyn[:]
    del probe.wheel_raw[:]
    probe.pump(slow)
    slow_pyn, slow_raw = list(pyn), list(probe.wheel_raw)
    del pyn[:]
    del probe.wheel_raw[:]
    print(">>> ТЕПЕРЬ БЫСТРО")
    sys.stdout.flush()
    probe.pump(fast)
    fast_pyn, fast_raw = list(pyn), list(probe.wheel_raw)
    listener.stop()
    probe.stop()

    for label, p, r in (("МЕДЛЕННО", slow_pyn, slow_raw),
                        ("БЫСТРО", fast_pyn, fast_raw)):
        print()
        print("  --- %s ---" % label)
        print("  pynput on_scroll вызван %d раз | Raw Input тиков колеса %d"
              % (len(p), len(r)))
        if p:
            zeros = sum(1 for dx, dy, _ in p if dx == 0 and dy == 0)
            vals = sorted({dy for _, dy, _ in p})
            print("     dy у pynput: %s" % (vals[:12] or "-"))
            print("     вызовов с dx==0 и dy==0: %d из %d  (%.0f%%)"
                  % (zeros, len(p), 100.0 * zeros / len(p)))
        if r:
            uniq = sorted(set(r))
            sub = sum(1 for v in r if abs(v) < 120)
            print("     сырое usButtonData: %s" % uniq[:12])
            print("     тиков с |смещением| < 120: %d из %d  (%.0f%%)"
                  % (sub, len(r), 100.0 * sub / len(r)))

    all_raw = slow_raw + fast_raw
    all_pyn = slow_pyn + fast_pyn
    print()
    if not all_raw and not all_pyn:
        print("  ВЫВОД: данных нет.")
        return
    hires = sum(1 for v in all_raw if abs(v) < 120)
    zeros = sum(1 for dx, dy, _ in all_pyn if dx == 0 and dy == 0)
    if hires or zeros:
        print("  ВЫВОД: колесо высокого разрешения. Сырых тиков меньше 120: %d,"
              % hires)
        print("         обнулённых вызовов pynput: %d. Считать тики через pynput"
              % zeros)
        print("         НЕЛЬЗЯ -- нужен свой хук либо Raw Input для колеса.")
    else:
        print("  ВЫВОД: обычное колесо, все тики кратны 120, pynput ничего не теряет.")
        print("         Детектор износа энкодера можно строить на on_scroll.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    measure_1b()
    measure_1a()
    measure_1c()
    print()
    print("замеры завершены, хуки и окно сняты")
    return 0


if __name__ == "__main__":
    sys.exit(main())
