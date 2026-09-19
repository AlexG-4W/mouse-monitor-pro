"""Прототип измерителя через Raw Input. ВНЕ приложения, в mouse_info_app.py
ничего не интегрировано и не будет -- решение принято по итогам замеров ниже.
Файл оставлен как документация этого решения.

    python tests/rawinput_probe.py                  # перечисление + самопроверка
    python tests/rawinput_probe.py 25 --single      # замер против LL-хука
    python tests/rawinput_probe.py --single --phases # фазы: тачпад / мышь / обе

================================ ИТОГ ЗАМЕРОВ =================================

ЧТО МЕРИЛИ. Raw Input (usage page 0x01 / usage 0x02, RIDEV_INPUTSINK,
message-only окно) как ВТОРОЙ источник телеметрии рядом с действующим
WH_MOUSE_LL через pynput. Две цели: разделить устройства и получить настоящую
частоту HID-репортов вместо частоты событий курсора.

ЧТО ВЫШЛО.

1. РАЗДЕЛЯТЬ НЕЧЕГО. Из четырёх записей Win32_PointingDevice репорты даёт
   ровно одна -- HID\VID_046D&PID_C539 (мышь Logitech). Записи
   VID_062A&PID_38B3 и VID_046D&PID_C231 молчали во всех шести прогонах.
   Тачпад MSFT0001 как raw-устройство не отвечает вовсе (см. п. 3).
   Реальных источников ввода два, а не четыре.

2. ЧАСТОТА ПОЛУЧАЕТСЯ ХУЖЕ, ЧЕМ У ХУКА. На одном движении руки Raw Input
   отдаёт в 3-8 раз меньше пакетов, чем LL-хук, при СОВПАДАЮЩЕМ суммарном
   смещении: данные не теряются, пакеты склеиваются. Зернистость хука 4.6
   counts на событие соответствует мыши на ~1000 Гц, зернистость Raw Input
   23-24 counts -- нет. Склейка растёт со скоростью движения (6.8 counts на
   репорт при медленном, 23.9 при быстром) и не снимается ни тесным циклом
   без ожидания (340 тыс. опросов/с), ни снятием LL-хука (27/с против 22/с).
   Флаг MOUSE_MOVE_NOCOALESCE не выставлен ни разу.
   Для тачпада та же картина (17.3 counts на репорт), то есть склейка --
   свойство пути доставки, а не устройства.

3. ТАЧПАД ПРИХОДИТ БЕЗ ИСТОЧНИКА. Precision Touchpad не виден как raw-мышь:
   его ввод приходит с hDevice == NULL. Доказано по фазам -- поток без
   источника жив ровно в фазах с тачпадом (781 и 503 репорта) и РОВНО НОЛЬ
   в фазе "только мышь". Отличить его от SendInput нельзя: синтетика тоже
   даёт hDevice == NULL.

4. ЛОЖНАЯ ТРЕВОГА, ЗАФИКСИРОВАНА ЯВНО. Гипотеза "фильтр injected в
   приложении выбрасывает ввод тачпада" ОПРОВЕРГНУТА замером: LL-хук видит
   тачпад как обычный ввод, injected-событий 0 во всех трёх фазах. Тачпад
   в метрики приложения попадает. Дефекта нет, чинить нечего.

5. РАЗДЕЛЕНИЕ ИСТОЧНИКОВ ТЕХНИЧЕСКИ РАБОТАЕТ. В фазе "тачпад и мышь вместе"
   20 корзин по 0.2 с с двумя активными источниками одновременно, при
   идеальном разделении по фазам. Механизм рабочий -- ему просто нечего
   разделять на этой машине, а тачпад отделяется лишь как "без источника".

ПОЧЕМУ НЕ ПОШЛО В ПРИЛОЖЕНИЕ. Обе заявленные цели на этом железе не
достигаются: разделять нечего, а частота выходит хуже действующей. Интеграция
добавила бы второе число, которое тоже пришлось бы объяснять.

=============================== ГРАБЛИ =======================================

GetRawInputBuffer, вызванный ИЗ обработчика WM_INPUT, почти всегда возвращает
ноль: запись к этому моменту принадлежит сообщению и достаётся только через
GetRawInputData(lParam). Он же, перенесённый в цикл сообщений ДО PeekMessage,
ТЕРЯЕТ 47% данных на гонке с DefWindowProc (замерено: 52-56% доходит,
независимо от темпа 50..1000/с). Годен только режим "handler" -- одиночный
GetRawInputData на каждое WM_INPUT: проверен на 400 из 400 при 1000 пакетах/с.

Все вызовы ctypes с restype/argtypes: в этом проекте дважды ловили усечение
pointer-sized значений до 32 бит на x64.
"""
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
HRAWINPUT = wintypes.HANDLE

# --- константы Raw Input ----------------------------------------------------
RIDEV_INPUTSINK = 0x00000100     # события приходят и когда окно не в фокусе
RIDEV_DEVNOTIFY = 0x00002000     # + WM_INPUT_DEVICE_CHANGE о приходе/уходе
RIDEV_REMOVE = 0x00000001

RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIDI_DEVICEINFO = 0x2000000B

RIM_TYPEMOUSE = 0

WM_INPUT = 0x00FF
WM_INPUT_DEVICE_CHANGE = 0x00FE
WM_QUIT = 0x0012
GIDC_ARRIVAL = 1
GIDC_REMOVAL = 2

# RAWMOUSE.usFlags
MOUSE_MOVE_RELATIVE = 0x00
MOUSE_MOVE_ABSOLUTE = 0x01
MOUSE_VIRTUAL_DESKTOP = 0x02
MOUSE_ATTRIBUTES_CHANGED = 0x04
MOUSE_MOVE_NOCOALESCE = 0x08

# RAWMOUSE.usButtonFlags -- нужны, чтобы отличить движение от кнопки/колеса
RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HWHEEL = 0x0800
RI_BUTTON_ANY = 0x03FF

HWND_MESSAGE = -3
PM_REMOVE = 0x0001
QS_ALLINPUT = 0x04FF
CS_OWNDC = 0x0020


# --- структуры --------------------------------------------------------------
class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT),
                ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD),
                ("hwndTarget", wintypes.HWND)]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE),
                ("dwType", wintypes.DWORD)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD),
                ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE),
                ("wParam", wintypes.WPARAM)]


class _RAWMOUSE_BUTTONS(ctypes.Structure):
    _fields_ = [("usButtonFlags", wintypes.USHORT),
                ("usButtonData", wintypes.USHORT)]


class _RAWMOUSE_UNION(ctypes.Union):
    _anonymous_ = ("s",)
    _fields_ = [("ulButtons", wintypes.ULONG),
                ("s", _RAWMOUSE_BUTTONS)]


class RAWMOUSE(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("usFlags", wintypes.USHORT),
                ("u", _RAWMOUSE_UNION),
                ("ulRawButtons", wintypes.ULONG),
                ("lLastX", wintypes.LONG),
                ("lLastY", wintypes.LONG),
                ("ulExtraInformation", wintypes.ULONG)]


class RAWINPUT(ctypes.Structure):
    """Только мышиный вариант: регистрируем usage 0x02 и ничего больше."""
    _fields_ = [("header", RAWINPUTHEADER),
                ("mouse", RAWMOUSE)]


class RID_DEVICE_INFO_MOUSE(ctypes.Structure):
    _fields_ = [("dwId", wintypes.DWORD),
                ("dwNumberOfButtons", wintypes.DWORD),
                ("dwSampleRate", wintypes.DWORD),
                ("fHasHorizontalWheel", wintypes.BOOL)]


class RID_DEVICE_INFO_KEYBOARD(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD),
                ("dwSubType", wintypes.DWORD),
                ("dwKeyboardMode", wintypes.DWORD),
                ("dwNumberOfFunctionKeys", wintypes.DWORD),
                ("dwNumberOfIndicators", wintypes.DWORD),
                ("dwNumberOfKeysTotal", wintypes.DWORD)]


class RID_DEVICE_INFO_HID(ctypes.Structure):
    _fields_ = [("dwVendorId", wintypes.DWORD),
                ("dwProductId", wintypes.DWORD),
                ("dwVersionNumber", wintypes.DWORD),
                ("usUsagePage", wintypes.USHORT),
                ("usUsage", wintypes.USHORT)]


class _RID_INFO_UNION(ctypes.Union):
    _fields_ = [("mouse", RID_DEVICE_INFO_MOUSE),
                ("keyboard", RID_DEVICE_INFO_KEYBOARD),
                ("hid", RID_DEVICE_INFO_HID)]


class RID_DEVICE_INFO(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("cbSize", wintypes.DWORD),
                ("dwType", wintypes.DWORD),
                ("u", _RID_INFO_UNION)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT),
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON)]


# --- прототипы. ВСЕ с restype/argtypes -------------------------------------
user32.RegisterClassExW.restype = wintypes.ATOM
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]

user32.UnregisterClassW.restype = wintypes.BOOL
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]

user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR,
                                   wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]

user32.DestroyWindow.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]

user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]

user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE),
                                           wintypes.UINT, wintypes.UINT]

user32.GetRawInputData.restype = wintypes.UINT
user32.GetRawInputData.argtypes = [HRAWINPUT, wintypes.UINT, wintypes.LPVOID,
                                   ctypes.POINTER(wintypes.UINT), wintypes.UINT]

user32.GetRawInputBuffer.restype = wintypes.UINT
user32.GetRawInputBuffer.argtypes = [ctypes.POINTER(RAWINPUT),
                                     ctypes.POINTER(wintypes.UINT),
                                     wintypes.UINT]

user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
user32.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                          wintypes.LPVOID,
                                          ctypes.POINTER(wintypes.UINT)]

user32.GetRawInputDeviceList.restype = wintypes.UINT
user32.GetRawInputDeviceList.argtypes = [ctypes.POINTER(RAWINPUTDEVICELIST),
                                         ctypes.POINTER(wintypes.UINT),
                                         wintypes.UINT]

user32.PeekMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT, wintypes.UINT]

user32.TranslateMessage.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]

user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]

user32.MsgWaitForMultipleObjects.restype = wintypes.DWORD
user32.MsgWaitForMultipleObjects.argtypes = [wintypes.DWORD,
                                             ctypes.POINTER(wintypes.HANDLE),
                                             wintypes.BOOL, wintypes.DWORD,
                                             wintypes.DWORD]

kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

INVALID = wintypes.UINT(-1).value

# Псевдоустройство для репортов без источника (hDevice == NULL).
INJECTED_ID = "(БЕЗ ИСТОЧНИКА, hDevice=NULL)"


def normalize_device_name(raw_name):
    r"""Имя из Raw Input -> формат DeviceID, который показывает панель.

    Raw Input отдаёт \\?\HID#VID_046D&PID_C539&MI_01#7&2e3a...#{378de44c-...},
    WMI в панели -- HID\VID_046D&PID_C539&MI_01\7&2E3A...
    Приводим к виду WMI: снимаем префикс \\?\, отбрасываем хвостовой GUID
    интерфейса, разделители # -> \.
    """
    if not raw_name:
        return ""
    name = raw_name
    for prefix in ("\\\\?\\", "\\??\\"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    parts = name.split("#")
    if parts and parts[-1].startswith("{"):
        parts = parts[:-1]
    return "\\".join(parts).upper()


def device_name(handle):
    """DeviceID по хэндлу. Пустая строка, если устройство уже отключено."""
    size = wintypes.UINT(0)
    if user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None,
                                     ctypes.byref(size)) == INVALID:
        return ""
    if not size.value:
        return ""
    buf = ctypes.create_unicode_buffer(size.value + 1)
    written = user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, buf,
                                            ctypes.byref(size))
    if written == INVALID:
        return ""
    return buf.value


def device_info(handle):
    """RID_DEVICE_INFO_MOUSE либо None."""
    info = RID_DEVICE_INFO()
    info.cbSize = ctypes.sizeof(RID_DEVICE_INFO)
    size = wintypes.UINT(ctypes.sizeof(RID_DEVICE_INFO))
    if user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICEINFO,
                                     ctypes.byref(info),
                                     ctypes.byref(size)) == INVALID:
        return None
    if info.dwType != RIM_TYPEMOUSE:
        return None
    return info.mouse


def enumerate_mice():
    """Все указывающие устройства, которые видит система прямо сейчас."""
    count = wintypes.UINT(0)
    size = ctypes.sizeof(RAWINPUTDEVICELIST)
    if user32.GetRawInputDeviceList(None, ctypes.byref(count),
                                    size) == INVALID:
        raise ctypes.WinError(ctypes.get_last_error())
    if not count.value:
        return []
    devices = (RAWINPUTDEVICELIST * count.value)()
    got = user32.GetRawInputDeviceList(devices, ctypes.byref(count), size)
    if got == INVALID:
        raise ctypes.WinError(ctypes.get_last_error())
    result = []
    for i in range(got):
        if devices[i].dwType != RIM_TYPEMOUSE:
            continue
        handle = devices[i].hDevice
        result.append({
            "handle": handle,
            "raw_name": device_name(handle),
            "info": device_info(handle),
        })
    return result


class DeviceStats:
    """Счётчики по одному устройству. Ключ -- DeviceID, а не хэндл:
    хэндл меняется при переподключении, DeviceID -- нет."""

    def __init__(self, device_id, raw_name):
        self.device_id = device_id
        self.raw_name = raw_name
        self.reports = 0            # всего репортов
        self.moves = 0              # из них с ненулевым смещением
        self.buttons = 0            # из них с событием кнопки
        self.wheel = 0
        self.absolute = 0           # MOUSE_MOVE_ABSOLUTE -- иная семантика
        self.counts_x = 0           # сумма |lLastX| в сырых counts
        self.counts_y = 0
        self.first_ts = None
        self.last_ts = None
        self.handles = set()        # сколько разных хэндлов видели
        self.detached = False
        self.nocoalesce = 0         # репортов с MOUSE_MOVE_NOCOALESCE
        self.delta_hist = {}        # |dx|+|dy| -> сколько репортов
        self.buckets = {}           # номер корзины времени -> репортов
        self.abs_last = None        # предыдущая абсолютная позиция
        self.abs_steps = 0          # переходов между абсолютными позициями
        self.abs_delta_sum = 0      # сумма |dx|+|dy| в абсолютных единицах

    def add(self, mouse, ts, handle, t0, bucket_size):
        self.reports += 1
        idx = int((ts - t0) / bucket_size)
        self.buckets[idx] = self.buckets.get(idx, 0) + 1
        self.handles.add(handle)
        if self.first_ts is None:
            self.first_ts = ts
        self.last_ts = ts
        flags = mouse.usFlags
        if flags & MOUSE_MOVE_ABSOLUTE:
            # lLastX/lLastY здесь -- нормализованные абсолютные координаты
            # (0..65535), а не приращение. В сумму смещений их класть нельзя;
            # вместо этого считаем разности между соседними позициями, иначе
            # для абсолютного устройства не с чем сравнивать зернистость.
            self.absolute += 1
            point = (mouse.lLastX, mouse.lLastY)
            if self.abs_last is not None and point != self.abs_last:
                self.abs_steps += 1
                self.abs_delta_sum += (abs(point[0] - self.abs_last[0])
                                       + abs(point[1] - self.abs_last[1]))
            self.abs_last = point
        elif mouse.lLastX or mouse.lLastY:
            self.moves += 1
            self.counts_x += abs(mouse.lLastX)
            self.counts_y += abs(mouse.lLastY)
            step = abs(mouse.lLastX) + abs(mouse.lLastY)
            bucket = step if step <= 8 else (16 if step <= 16 else
                                             32 if step <= 32 else 99)
            self.delta_hist[bucket] = self.delta_hist.get(bucket, 0) + 1
        if flags & MOUSE_MOVE_NOCOALESCE:
            self.nocoalesce += 1
        btn = mouse.usButtonFlags
        if btn & RI_BUTTON_ANY:
            self.buttons += 1
        if btn & (RI_MOUSE_WHEEL | RI_MOUSE_HWHEEL):
            self.wheel += 1

    @property
    def span(self):
        if self.first_ts is None or self.last_ts is None:
            return 0.0
        return self.last_ts - self.first_ts

    def rate(self):
        """Частота репортов на интервале активности устройства.

        Считается по собственному окну активности, а не по всей длительности
        замера: устройство, которым не пользовались половину прогона, иначе
        показало бы вдвое заниженную частоту.
        """
        if self.span <= 0 or self.reports < 2:
            return 0.0
        return (self.reports - 1) / self.span


class RawInputProbe:
    CLASS_NAME = "MouseMonitorProRawInputProbe"

    def __init__(self):
        self.hwnd = None
        self.atom = 0
        self.hinstance = kernel32.GetModuleHandleW(None)
        self.stats = {}                 # DeviceID -> DeviceStats
        self.by_handle = {}             # хэндл -> DeviceStats (кэш)
        self.unknown_reports = 0        # hDevice, который не удалось назвать
        self.injected_reports = 0       # hDevice == NULL -- синтетика
        self.batch_sizes = {}           # сколько записей забрал один drain
        self.arrivals = []
        self.removals = []
        self.buffer_calls = 0
        self.fallback_calls = 0
        self.wm_input_messages = 0
        self.t0 = None
        self.bucket_size = 0.2      # корзина линии активности, с
        # Пакетное чтение можно отключить: нужно, чтобы отделить
        # поведение GetRawInputBuffer от поведения самого Raw Input.
        self.use_buffer = True
        # "handler" -- GetRawInputData внутри обработчика WM_INPUT.
        #     ЗАМЕРЕНО: ровно 1:1 с сообщениями, на контролируемом потоке
        #     ловит 100% поданного при 100, 500 и 1000 пакетах/с.
        #     Это единственный режим, пригодный для интеграции.
        # "loopbuf" -- GetRawInputBuffer в цикле сообщений, до PeekMessage.
        #     ТЕРЯЕТ ДАННЫЕ, НЕ ИСПОЛЬЗОВАТЬ. Замерено: на контролируемом
        #     потоке доходит 52-56% независимо от темпа (50..1000/с).
        #     Причина -- гонка: если запись не успел забрать drain_pending,
        #     её забирает DefWindowProc(WM_INPUT) при диспетчеризации, и она
        #     пропадает молча. Оставлен только как демонстрация этого эффекта.
        self.mode = "handler"
        # Тесный цикл без ожидания: съедает ядро, зато исключает
        # собственную задержку потребителя из результата замера.
        self.busy = False
        self._wndproc = WNDPROC(self._on_message)
        # Буфер под пакетное чтение: один RAWINPUT ~40 байт на x64,
        # 512 записей с запасом перекрывают секунду при 1000 Гц.
        self._buf_len = 512
        self._buf = (RAWINPUT * self._buf_len)()
        self._single = RAWINPUT()

    # --- окно и регистрация -------------------------------------------------
    def start(self):
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = CS_OWNDC
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self.hinstance
        wc.lpszClassName = self.CLASS_NAME
        self.atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not self.atom:
            raise ctypes.WinError(ctypes.get_last_error())
        # HWND_MESSAGE: окно без экрана, без обработки ввода, только сообщения.
        self.hwnd = user32.CreateWindowExW(
            0, self.CLASS_NAME, None, 0, 0, 0, 0, 0,
            wintypes.HWND(HWND_MESSAGE), None, self.hinstance, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

        rid = RAWINPUTDEVICE()
        rid.usUsagePage = 0x01          # Generic Desktop Controls
        rid.usUsage = 0x02              # Mouse
        # INPUTSINK -- события идут и когда окно не в фокусе (у message-only
        # окна фокуса не бывает вовсе, без флага не пришло бы ничего).
        # DEVNOTIFY -- WM_INPUT_DEVICE_CHANGE о приходе и уходе устройств:
        # именно так ловится переподключение, при котором меняется hDevice.
        rid.dwFlags = RIDEV_INPUTSINK | RIDEV_DEVNOTIFY
        rid.hwndTarget = self.hwnd
        if not user32.RegisterRawInputDevices(ctypes.byref(rid), 1,
                                              ctypes.sizeof(RAWINPUTDEVICE)):
            raise ctypes.WinError(ctypes.get_last_error())
        return self

    def stop(self):
        # Снятие регистрации: hwndTarget обязан быть NULL при RIDEV_REMOVE.
        if self.hwnd:
            rid = RAWINPUTDEVICE()
            rid.usUsagePage = 0x01
            rid.usUsage = 0x02
            rid.dwFlags = RIDEV_REMOVE
            rid.hwndTarget = None
            user32.RegisterRawInputDevices(ctypes.byref(rid), 1,
                                           ctypes.sizeof(RAWINPUTDEVICE))
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.atom:
            user32.UnregisterClassW(self.CLASS_NAME, self.hinstance)
            self.atom = 0

    # --- разбор -------------------------------------------------------------
    def _stats_for(self, handle):
        """Статистика по хэндлу, с кэшем и переоткрытием при переподключении."""
        cached = self.by_handle.get(handle)
        if cached is not None:
            return cached
        raw = device_name(handle)
        if not raw:
            # Устройство уже отключено либо это синтетика (hDevice == NULL).
            return None
        device_id = normalize_device_name(raw)
        stats = self.stats.get(device_id)
        if stats is None:
            stats = DeviceStats(device_id, raw)
            self.stats[device_id] = stats
        else:
            stats.detached = False
        self.by_handle[handle] = stats
        return stats

    def _consume(self, raw_input, ts):
        header = raw_input.header
        if header.dwType != RIM_TYPEMOUSE:
            return
        handle = header.hDevice
        if not handle:
            # Источника нет. Это либо SendInput/mouse_event, либо ввод,
            # синтезированный драйвером устройства (Precision Touchpad
            # именно так и работает). Ведём как отдельное псевдоустройство,
            # чтобы у него была та же статистика и та же линия активности.
            self.injected_reports += 1
            stats = self.stats.get(INJECTED_ID)
            if stats is None:
                stats = DeviceStats(INJECTED_ID, INJECTED_ID)
                self.stats[INJECTED_ID] = stats
            if self.t0 is None:
                self.t0 = ts
            stats.add(raw_input.mouse, ts, 0, self.t0, self.bucket_size)
            return
        stats = self._stats_for(handle)
        if stats is None:
            self.unknown_reports += 1
            return
        if self.t0 is None:
            self.t0 = ts
        stats.add(raw_input.mouse, ts, handle, self.t0, self.bucket_size)

    def _drain(self, hrawinput):
        """Забирает всё, что накопилось, одним вызовом.

        GetRawInputBuffer вместо GetRawInputData на каждое сообщение: при
        1000 Гц на четырёх устройствах очередь сообщений -- узкое место, а
        пакетное чтение снимает по несколько десятков репортов за системный
        вызов. Размер пакета пишем в гистограмму: по ней видно, доходило ли
        дело до переполнения.
        """
        ts = time.perf_counter()
        total = 0
        while self.use_buffer:
            size = wintypes.UINT(ctypes.sizeof(self._buf))
            count = user32.GetRawInputBuffer(self._buf, ctypes.byref(size),
                                             ctypes.sizeof(RAWINPUTHEADER))
            self.buffer_calls += 1
            if count == INVALID or count == 0:
                break
            total += count
            # Записи переменной длины: следующая начинается через dwSize,
            # выровненный вверх до размера указателя (NEXTRAWINPUTBLOCK).
            addr = ctypes.addressof(self._buf)
            align = ctypes.sizeof(ctypes.c_void_p)
            for _ in range(count):
                item = RAWINPUT.from_address(addr)
                self._consume(item, ts)
                step = item.header.dwSize
                addr += (step + align - 1) & ~(align - 1)
            if count < self._buf_len:
                break
        if total == 0 and hrawinput:
            # Буфер пуст -- значит сообщение уже разобрано предыдущим drain'ом
            # либо GetRawInputBuffer недоступен. Достаём одиночную запись.
            size = wintypes.UINT(ctypes.sizeof(self._single))
            got = user32.GetRawInputData(hrawinput, RID_INPUT,
                                         ctypes.byref(self._single),
                                         ctypes.byref(size),
                                         ctypes.sizeof(RAWINPUTHEADER))
            self.fallback_calls += 1
            if got != INVALID and got > 0:
                self._consume(self._single, ts)
                total = 1
        if total:
            self.batch_sizes[total] = self.batch_sizes.get(total, 0) + 1

    def _on_message(self, hwnd, msg, wparam, lparam):
        if msg == WM_INPUT:
            self.wm_input_messages += 1
            if self.mode == "loopbuf":
                # Данные уже сняты сливом в цикле; здесь только учёт.
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
            self._drain(wintypes.HANDLE(lparam))
            # Система обязана освободить свои структуры: WM_INPUT всегда
            # передаётся дальше в DefWindowProc.
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        if msg == WM_INPUT_DEVICE_CHANGE:
            handle = wintypes.HANDLE(lparam)
            if wparam == GIDC_ARRIVAL:
                raw = device_name(handle)
                self.arrivals.append(normalize_device_name(raw) or "?")
                # Новый хэндл: кэш по нему пуст, статистика подхватится сама
                # при первом же репорте -- ключ у неё DeviceID, не хэндл.
            elif wparam == GIDC_REMOVAL:
                stats = self.by_handle.pop(handle.value if handle else None,
                                           None)
                if stats is None:
                    # Уже отключено -- имя не получить, ищем по кэшу хэндлов.
                    for key, value in list(self.by_handle.items()):
                        if key == handle:
                            stats = value
                            del self.by_handle[key]
                            break
                if stats is not None:
                    stats.detached = True
                    self.removals.append(stats.device_id)
                else:
                    self.removals.append("(неизвестное устройство)")
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def reset(self):
        """Обнуляет счётчики, сохраняя окно и регистрацию."""
        self.stats.clear()
        self.by_handle.clear()
        self.unknown_reports = 0
        self.injected_reports = 0
        self.batch_sizes.clear()
        self.buffer_calls = 0
        self.fallback_calls = 0
        self.wm_input_messages = 0
        self.t0 = None
        del self.arrivals[:]
        del self.removals[:]

    def real_reports(self):
        return sum(s.reports for s in self.stats.values())

    def wait_for_real_input(self, timeout):
        """Ждёт первого репорта от НАСТОЯЩЕГО устройства.

        Замер запускается от движения руки, а не от секундомера: иначе окно
        измерения начинается на пустом месте и частота выходит заниженной
        просто потому, что человек не успел взяться за мышь.
        """
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.pump(0.1)
            if self.real_reports():
                return True
        return False

    def drain_pending(self):
        """Снимает всё, что накопилось в буфере Raw Input, пачками.

        Зовётся из цикла сообщений ДО PeekMessage: пока записи не разобраны
        в сообщения, GetRawInputBuffer отдаёт их десятками за один системный
        вызов. Вызов того же GetRawInputBuffer ИЗ обработчика WM_INPUT почти
        всегда возвращает ноль -- запись к этому моменту уже принадлежит
        сообщению и достаётся только через GetRawInputData(lParam).
        """
        ts = time.perf_counter()
        align = ctypes.sizeof(ctypes.c_void_p)
        while True:
            size = wintypes.UINT(ctypes.sizeof(self._buf))
            count = user32.GetRawInputBuffer(self._buf, ctypes.byref(size),
                                             ctypes.sizeof(RAWINPUTHEADER))
            self.buffer_calls += 1
            if count == INVALID or count == 0:
                return
            self.batch_sizes[count] = self.batch_sizes.get(count, 0) + 1
            addr = ctypes.addressof(self._buf)
            for _ in range(count):
                item = RAWINPUT.from_address(addr)
                self._consume(item, ts)
                addr += (item.header.dwSize + align - 1) & ~(align - 1)
            if count < self._buf_len:
                return

    def pump(self, seconds):
        """Крутит очередь сообщений заданное время."""
        msg = wintypes.MSG()
        deadline = time.perf_counter() + seconds
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            if self.mode == "loopbuf":
                self.drain_pending()
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_QUIT:
                    return
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if self.busy:
                continue        # ни миллисекунды сна: меряем устройство, не себя
            # Спим до следующего сообщения, а не крутим процессор вхолостую.
            user32.MsgWaitForMultipleObjects(
                0, None, False, min(10, int(remaining * 1000) + 1), QS_ALLINPUT)


# --- отчёт ------------------------------------------------------------------
MOUSEEVENTF_MOVE = 0x0001
WAIT_TIMEOUT = 240        # сколько ждать, пока человек возьмётся за мышь
user32.mouse_event.restype = None
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, ctypes.c_void_p]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]


def check_layout():
    """Раскладка структур на x64. Ошибка здесь -- это молча неверные числа."""
    expect = {"RAWINPUTHEADER": (RAWINPUTHEADER, 24),
              "RAWMOUSE": (RAWMOUSE, 24),
              "RAWINPUTDEVICELIST": (RAWINPUTDEVICELIST, 16),
              "RAWINPUTDEVICE": (RAWINPUTDEVICE, 16)}
    print("разрядность: %d бит | размеры структур:" % (ctypes.sizeof(ctypes.c_void_p) * 8))
    okay = True
    for name, (cls, size) in expect.items():
        actual = ctypes.sizeof(cls)
        mark = "ok" if actual == size else "РАСХОЖДЕНИЕ, ждали %d" % size
        okay = okay and actual == size
        print("   %-20s %3d байт  %s" % (name, actual, mark))
    off = RAWINPUTHEADER.hDevice.offset
    print("   %-20s смещение hDevice = %d (ждали 8)" % ("", off))
    return okay and off == 8


def show_devices():
    mice = enumerate_mice()
    print("указывающих устройств в системе: %d" % len(mice))
    for entry in mice:
        info = entry["info"]
        rate = "%d Гц" % info.dwSampleRate if info and info.dwSampleRate else "не сообщает"
        buttons = info.dwNumberOfButtons if info else "?"
        print("   %s" % normalize_device_name(entry["raw_name"]))
        print("       hDevice=0x%X | кнопок: %s | заявленная частота опроса: %s"
              % (entry["handle"] or 0, buttons, rate))
    return mice


def self_test(probe):
    """Проверка проводки СИНТЕТИКОЙ. Реальной частоты она не даёт и для
    измерения непригодна -- только подтверждает, что WM_INPUT доходит,
    структуры разбираются и флаги декодируются."""
    pos = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pos))
    before = probe.injected_reports + sum(s.reports for s in probe.stats.values())
    for _ in range(8):
        user32.mouse_event(MOUSEEVENTF_MOVE, 3, 2, 0, None)
        time.sleep(0.01)
    probe.pump(0.4)
    user32.SetCursorPos(pos.x, pos.y)
    after = probe.injected_reports + sum(s.reports for s in probe.stats.values())
    print("подано 8 синтетических смещений -> репортов получено: %d" % (after - before))
    print("   из них с hDevice == NULL (синтетика): %d" % probe.injected_reports)
    return after - before


def measure(probe, seconds):
    """Замер настоящей мышью: хук и Raw Input на одном движении руки."""
    from pynput import mouse

    hook = {"moves": 0, "first": None, "last": None, "injected": 0}

    def on_move(x, y, injected=False):
        if injected:
            hook["injected"] += 1
            return
        now = time.perf_counter()
        if hook["first"] is None:
            hook["first"] = now
        hook["last"] = now
        hook["moves"] += 1

    print()
    print(">>> ДВИГАЙ НАСТОЯЩУЮ МЫШЬ. Замер стартует от первого живого репорта")
    print(">>> и длится %d с. По возможности задействуй и тачпад." % seconds)
    print(">>> Ожидание (до %d с)..." % WAIT_TIMEOUT)
    sys.stdout.flush()
    probe.reset()
    if not probe.wait_for_real_input(WAIT_TIMEOUT):
        print("!!! за %d с не пришло ни одного репорта от реального устройства"
              % WAIT_TIMEOUT)
        return None
    print(">>> движение поймано, идёт замер %d с..." % seconds)
    sys.stdout.flush()
    # Счётчики обнуляем ещё раз: ожидание уже набрало несколько репортов,
    # и окно измерения должно начинаться чистым, одновременно с хуком.
    probe.reset()
    half = seconds / 2.0
    # Первая половина -- БЕЗ низкоуровневого хука. Если хук сам вызывает
    # склейку Raw Input (он серализует весь ввод через процесс), частота
    # репортов в двух половинах разойдётся. Это единственный способ
    # проверить, совместимы ли два источника в одном процессе.
    t0 = time.perf_counter()
    probe.pump(half)
    phase1 = {"reports": probe.real_reports(), "injected": probe.injected_reports,
              "elapsed": time.perf_counter() - t0}
    listener = mouse.Listener(on_move=on_move)
    listener.start()
    t1 = time.perf_counter()
    probe.pump(seconds - half)
    phase2 = {"reports": probe.real_reports() - phase1["reports"],
              "injected": probe.injected_reports - phase1["injected"],
              "elapsed": time.perf_counter() - t1}
    elapsed = time.perf_counter() - t0
    listener.stop()
    print()
    print("ФАЗЫ: влияет ли сам LL-хук на доставку Raw Input")
    print("  без хука : %5d репортов за %.1f с -> %.0f/с (инъекции %d)"
          % (phase1["reports"], phase1["elapsed"],
             phase1["reports"] / max(0.001, phase1["elapsed"]), phase1["injected"]))
    print("  с хуком  : %5d репортов за %.1f с -> %.0f/с (инъекции %d)"
          % (phase2["reports"], phase2["elapsed"],
             phase2["reports"] / max(0.001, phase2["elapsed"]), phase2["injected"]))

    hook_span = ((hook["last"] - hook["first"])
                 if hook["first"] is not None and hook["last"] is not None else 0.0)
    hook_rate = (hook["moves"] - 1) / hook_span if hook_span > 0 and hook["moves"] > 1 else 0.0
    return elapsed, hook, hook_span, hook_rate


def timeline(probe):
    """Линия активности и одновременность.

    Вопрос "разделяются ли два активных устройства" решается не заявлением,
    а пересечением: сколько корзин времени, в которых репорты давали ДВА и
    более устройства сразу. Корзина 0.2 с -- человек не успевает за это время
    переложить руку с тачпада на мышь.
    """
    active = [s for s in probe.stats.values() if s.reports]
    if not active:
        return
    span = max(max(s.buckets) for s in active) + 1
    print()
    print("ЛИНИЯ АКТИВНОСТИ (корзина %.1f с, '#' = были репорты)" % probe.bucket_size)
    width = min(span, 120)
    for s in sorted(active, key=lambda v: -v.reports):
        line = "".join("#" if i in s.buckets else "." for i in range(width))
        tag = s.device_id.split("\\")[1][:22] if "\\" in s.device_id else s.device_id[:22]
        print("  %-24s %s" % (tag, line))
    overlap = 0
    for i in range(span):
        if sum(1 for s in active if i in s.buckets) >= 2:
            overlap += 1
    print("  корзин с ДВУМЯ и более активными устройствами: %d из %d" % (overlap, span))
    if overlap:
        print("  -> одновременная работа разных устройств РАЗДЕЛЯЕТСЯ по DeviceID")
    else:
        print("  -> одновременной работы двух устройств в этом замере не было")


PHASE_PLAN = [(8.0, "только ТАЧПАД"),
              (6.0, "только МЫШЬ"),
              (6.0, "ТАЧПАД и МЫШЬ вместе")]


def measure_phased(probe, plan):
    """Замер по фазам: кто даёт события и совпадают ли два NULL-потока.

    Хук стоит всю дорогу и считает injected-события ОТДЕЛЬНО от обычных.
    Если в фазе "только тачпад" хук видит события и все они помечены
    injected, а Raw Input в тот же момент отдаёт столько же репортов без
    источника -- это один поток, и это тачпад.

    Синтетику в окне замера не подаём вовсе: иначе NULL-поток нельзя было бы
    приписать тачпаду однозначно.
    """
    from pynput import mouse

    hook = {"real": 0, "injected": 0}

    def on_move(x, y, injected=False):
        hook["injected" if injected else "real"] += 1

    def snap():
        return {"hook_real": hook["real"], "hook_inj": hook["injected"],
                "null": probe.injected_reports,
                "dev": sum(st.reports for did, st in probe.stats.items()
                           if did != INJECTED_ID)}

    listener = mouse.Listener(on_move=on_move)
    listener.start()
    print()
    total = sum(d for d, _ in plan)
    print(">>> СЦЕНАРИЙ, %d с, отсчёт от первого движения:" % int(total))
    mark = 0.0
    for dur, label in plan:
        print(">>>   %4.0f-%-4.0f с : %s" % (mark, mark + dur, label))
        mark += dur
    print(">>> Ожидание первого движения (до %d с)..." % WAIT_TIMEOUT)
    sys.stdout.flush()
    probe.reset()
    if not probe.wait_for_real_input(WAIT_TIMEOUT):
        print("!!! движения не было")
        listener.stop()
        return None
    probe.reset()
    hook["real"] = hook["injected"] = 0
    print(">>> ПОЕХАЛИ")
    sys.stdout.flush()

    rows = []
    t_start = time.perf_counter()
    for dur, label in plan:
        before = snap()
        probe.pump(dur)
        after = snap()
        rows.append((label, dur,
                     after["hook_real"] - before["hook_real"],
                     after["hook_inj"] - before["hook_inj"],
                     after["dev"] - before["dev"],
                     after["null"] - before["null"]))
    elapsed = time.perf_counter() - t_start
    listener.stop()

    print()
    print("=" * 78)
    print("ПО ФАЗАМ (замер %.1f с)" % elapsed)
    print("=" * 78)
    print("  %-22s %8s %10s %10s %10s" % ("фаза", "хук", "хук inj", "RI устр.", "RI NULL"))
    for label, dur, hr, hi, dev, null in rows:
        print("  %-22s %8d %10d %10d %10d" % (label, hr, hi, dev, null))
    print()
    for label, dur, hr, hi, dev, null in rows:
        print("  %-22s хук inj %.0f/с против RI NULL %.0f/с  -- %s"
              % (label, hi / dur, null / dur,
                 "темп совпал" if hi and abs(hi - null) <= max(3, 0.15 * max(hi, null))
                 else "не совпал" if (hi or null) else "потока нет"))
    return rows


def report(probe, elapsed, hook, hook_span, hook_rate, enumerated=None):
    print()
    print("=" * 78)
    print("ПОКАЗАНИЯ ПО УСТРОЙСТВАМ (Raw Input), замер %.1f с" % elapsed)
    print("=" * 78)
    active = [s for s in probe.stats.values() if s.reports]
    if not active:
        print("  ни одного репорта: мышь не двигалась")
    if enumerated:
        print("  какие из перечисленных записей дали данные:")
        for entry in enumerated:
            did = normalize_device_name(entry["raw_name"])
            hit = probe.stats.get(did)
            print("     %-8s %s"
                  % ("ДАЛА" if hit and hit.reports else "молчит", did))
        print()
    for s in sorted(active, key=lambda v: -v.reports):
        print("  %s" % s.device_id)
        print("     репортов: %-6d  из них смещений: %-6d  кнопки: %-4d  колесо: %d"
              % (s.reports, s.moves, s.buttons, s.wheel))
        print("     активность: %.2f с  ->  частота репортов: %.0f/с"
              % (s.span, s.rate()))
        print("     сырых counts: X=%d Y=%d  |  абсолютных репортов: %d  |  хэндлов: %d"
              % (s.counts_x, s.counts_y, s.absolute, len(s.handles)))
        if s.absolute and s.abs_steps:
            print("     АБСОЛЮТНОЕ устройство: шагов позиции %d, средний шаг %.1f"
                  " ед. из 65535 (counts на репорт для него не определены)"
                  % (s.abs_steps, s.abs_delta_sum / s.abs_steps))
        if s.moves:
            print("     counts на репорт (среднее): %.1f  |  с флагом NOCOALESCE: %d"
                  % ((s.counts_x + s.counts_y) / s.moves, s.nocoalesce))
            hist = sorted(s.delta_hist.items())
            names = {16: "9-16", 32: "17-32", 99: ">32"}
            print("     |dx|+|dy|: %s"
                  % ", ".join("%s:%d" % (names.get(k, k), v) for k, v in hist))
        if s.detached:
            print("     УСТРОЙСТВО ОТКЛЮЧЕНО в ходе замера")
    total_reports = sum(s.reports for s in active)
    total_moves = sum(s.moves for s in active)

    print()
    print("=" * 78)
    print("СРАВНЕНИЕ С ТЕКУЩИМ МЕТОДОМ (WH_MOUSE_LL через pynput)")
    print("=" * 78)
    print("  хук       : %-6d событий движения  за %.2f с  ->  %.0f/с"
          % (hook["moves"], hook_span, hook_rate))
    print("  хук       : %-6d событий, помеченных LLMHF_INJECTED (приложение их "
          "отбрасывает)" % hook["injected"])
    print("  Raw Input : %-6d репортов со смещением (сумма по устройствам)"
          % total_moves)
    print("  Raw Input : %-6d репортов всего" % total_reports)
    if hook["moves"]:
        print("  отношение : Raw Input / хук = %.2fx по смещениям, %.2fx по репортам"
              % (total_moves / hook["moves"], total_reports / hook["moves"]))
        diff = abs(total_moves - hook["moves"]) / hook["moves"] * 100.0
        print("  расхождение по числу событий: %.1f%%" % diff)
    print("  устройств, давших данные: %d (хук не различает их вовсе)" % len(active))

    print()
    print("СЛУЖЕБНОЕ")
    print("  сообщений WM_INPUT получено: %d" % probe.wm_input_messages)
    print("  пакетное чтение: %s | вызовов GetRawInputBuffer: %d | одиночным чтением: %d"
          % ("включено" if probe.use_buffer else "ВЫКЛЮЧЕНО",
             probe.buffer_calls, probe.fallback_calls))
    if probe.batch_sizes:
        top = sorted(probe.batch_sizes.items())
        print("  размер пакета (записей за раз): %s"
              % ", ".join("%d:%d" % kv for kv in top[:10]))
        print("  максимальный пакет: %d из %d возможных"
              % (max(probe.batch_sizes), probe._buf_len))
    print("  синтетических репортов (hDevice=NULL): %d" % probe.injected_reports)
    print("  репортов от неопознанного хэндла: %d" % probe.unknown_reports)
    print("  приходов устройств за замер: %s" % (probe.arrivals or "нет"))
    print("  уходов устройств за замер:   %s" % (probe.removals or "нет"))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    seconds = 0
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        seconds = int(args[0])
    use_buffer = "--single" not in sys.argv
    mode = "loopbuf" if "--loopbuf" in sys.argv else "handler"
    busy = "--busy" in sys.argv

    print("=" * 78)
    print("1. РАСКЛАДКА СТРУКТУР")
    print("=" * 78)
    if not check_layout():
        print("раскладка не совпала -- дальше идти нельзя")
        return 1

    print()
    print("=" * 78)
    print("2. ПЕРЕЧИСЛЕНИЕ УСТРОЙСТВ")
    print("=" * 78)
    devices = show_devices()

    probe = RawInputProbe()
    probe.use_buffer = use_buffer
    probe.mode = mode
    probe.busy = busy
    print()
    print("пакетное чтение GetRawInputBuffer: %s"
          % ("включено" if use_buffer else "ВЫКЛЮЧЕНО (--single)"))
    print("режим слива: %s | тесный цикл: %s"
          % (mode, "да (--busy)" if busy else "нет"))
    probe.start()
    try:
        print()
        print("=" * 78)
        print("3. САМОПРОВЕРКА ПРОВОДКИ (синтетика, НЕ измерение)")
        print("=" * 78)
        if "--phases" in sys.argv:
            print("пропущена: синтетику в фазовом режиме не подаём")
        else:
            self_test(probe)

        if "--phases" in sys.argv:
            rows = measure_phased(probe, PHASE_PLAN)
            if rows is None:
                return 2
            print()
            print("=" * 78)
            print("ИТОГО ПО УСТРОЙСТВАМ")
            print("=" * 78)
            print("  какие из перечисленных записей дали данные:")
            for entry in devices:
                did = normalize_device_name(entry["raw_name"])
                hit = probe.stats.get(did)
                print("     %-8s %s" % ("ДАЛА" if hit and hit.reports else "молчит", did))
            for st in sorted(probe.stats.values(), key=lambda v: -v.reports):
                if not st.reports:
                    continue
                print("  %s" % st.device_id)
                print("     репортов %d | смещений %d | кнопки %d | колесо %d | абс. %d"
                      % (st.reports, st.moves, st.buttons, st.wheel, st.absolute))
                if st.moves:
                    print("     counts на репорт: %.1f"
                          % ((st.counts_x + st.counts_y) / st.moves))
                if st.abs_steps:
                    print("     абсолютное: шагов %d, средний шаг %.1f из 65535"
                          % (st.abs_steps, st.abs_delta_sum / st.abs_steps))
            timeline(probe)
            return 0
        if seconds:
            got = measure(probe, seconds)
            if got is None:
                return 2
            report(probe, *got, enumerated=devices)
            timeline(probe)
        else:
            print()
            print("замер не запрошен: передай число секунд аргументом")
    finally:
        probe.stop()
        print()
        print("окно снято, регистрация Raw Input снята")
    return 0


if __name__ == "__main__":
    sys.exit(main())
