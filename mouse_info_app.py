import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont
import ctypes
from ctypes import wintypes
import logging
import re
import sys
import time
import math
import threading
import queue
import wmi
import pystray
import csv
import os
import win32gui
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from pynput import mouse
import win32api
import win32con
import pywintypes

# --- Диагностический лог -----------------------------------------------------
# Сборка идёт с console=False, поэтому stdout и traceback уходят в никуда.
# Всё, что нужно увидеть постфактум, пишется в файл рядом с приложением.

def app_dir():
    """Каталог рядом с исполняемым файлом (для onefile-сборки -- рядом с .exe)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DATA_DIR = None


def data_dir():
    """Каталог для логов, теплокарт и диагностического лога.

    Относительные пути ("logs", "heatmaps") разрешались от текущего рабочего
    каталога. У EXE, запущенного из ярлыка или автозагрузки, это может быть
    C:\\Windows\\System32, где создать каталог нельзя: os.makedirs бросал
    PermissionError прямо в обработчике кнопки, а при console=False traceback
    уходил в никуда и кнопка просто переставала работать.

    Пишем рядом с приложением; если туда нельзя -- в %LOCALAPPDATA%.
    """
    global DATA_DIR
    if DATA_DIR:
        return DATA_DIR

    candidates = [app_dir()]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "MouseMonitorPro"))

    for directory in candidates:
        try:
            os.makedirs(directory, exist_ok=True)
            probe = os.path.join(directory, ".write_test")
            with open(probe, "w"):
                pass
            os.remove(probe)
            DATA_DIR = directory
            return DATA_DIR
        except OSError:
            continue

    DATA_DIR = os.path.abspath(".")
    return DATA_DIR


# Значения по умолчанию в Windows -- нужны, чтобы отличить "пользователь не
# трогал настройку" от "пользователь её изменил". Пометка "(default)" ставится
# по факту сравнения, а не по привычке: на машине разработки порог двойного
# клика оказался 480 мс, а не 500.
WIN_DEFAULT_POINTER_SPEED = 10      # шкала ползунка 1..20
WIN_DEFAULT_DOUBLECLICK_MS = 500

_user32 = ctypes.windll.user32
_user32.GetDoubleClickTime.restype = wintypes.UINT
_user32.GetDoubleClickTime.argtypes = []


def double_click_limits():
    """Системные правила двойного клика: (порог в мс, ширина, высота в px).

    Порог -- GetDoubleClickTime. Прямоугольник -- SM_CXDOUBLECLK/SM_CYDOUBLECLK:
    второй клик обязан попасть в него вокруг первого, иначе Windows двойным
    его не считает, сколь угодно быстрым он бы ни был.
    """
    try:
        gap = int(_user32.GetDoubleClickTime())
    except OSError:
        logging.exception("не удалось прочитать GetDoubleClickTime")
        gap = WIN_DEFAULT_DOUBLECLICK_MS
    try:
        width = win32api.GetSystemMetrics(win32con.SM_CXDOUBLECLK)
        height = win32api.GetSystemMetrics(win32con.SM_CYDOUBLECLK)
    except pywintypes.error:
        logging.exception("не удалось прочитать метрики двойного клика")
        width = height = 4
    return gap, width, height


def _stick_label_west(layout):
    """Рекурсивно ставит sticky='w' элементу *.label в раскладке ttk."""
    out = []
    for name, options in layout:
        options = dict(options)
        if name.endswith(".label"):
            options["sticky"] = "w"
        if "children" in options:
            options["children"] = _stick_label_west(options["children"])
        out.append((name, options))
    return out


def left_menubutton_style(name="Left.TMenubutton"):
    """Стиль выпадающего списка с подписью по левому краю.

    Одной опции anchor мало: в теме vista раскладка TMenubutton содержит
    ('Menubutton.label', {'sticky': ''}), то есть подпись центрируется самой
    раскладкой и до неё опция не доходит. Поэтому раскладка берётся у
    ФАКТИЧЕСКОЙ темы и правится в одном месте -- жёстко прописанная копия
    сломалась бы на другой теме.

    Возвращает имя стиля; при отказе -- пустую строку, и вызывающий получит
    список с оформлением по умолчанию, а не исключение.
    """
    try:
        style = ttk.Style()
        style.layout(name, _stick_label_west(style.layout("TMenubutton")))
        style.configure(name, anchor="w")
        return name
    except tk.TclError:
        logging.exception("не удалось построить стиль выпадающего списка")
        return ""


def unique_path(directory, stem, extension, limit=100):
    """Свободное имя вида stem.ext, stem_2.ext, stem_3.ext...

    Имена артефактов сессии имеют секундную точность, и две сессии внутри
    одной секунды давали ОДНО имя: предыдущий файл молча перезаписывался,
    а для CSV это потеря данных. Воспроизводится тривиально -- СТАРТ мышью,
    СТОП пробелом с той же кнопки.

    Суффикс добавляется ТОЛЬКО при совпадении, поэтому обычные имена не
    меняются и остаются читаемыми и сортируемыми: session_20260905_121238.csv
    и session_20260905_121238_2.csv стоят рядом.
    """
    candidate = os.path.join(directory, stem + extension)
    if not os.path.exists(candidate):
        return candidate
    for index in range(2, limit + 1):
        candidate = os.path.join(directory, "%s_%d%s" % (stem, index, extension))
        if not os.path.exists(candidate):
            return candidate
    # Сто занятых имён в одну секунду -- уже не наш сценарий. Отдаём имя с
    # микросекундами, лишь бы не затереть чужой файл.
    return os.path.join(directory, "%s_%s%s"
                        % (stem, datetime.now().strftime("%f"), extension))


def setup_logging():
    """Ставит файловый лог. Никогда не роняет старт: если писать некуда,
    приложение обязано работать дальше -- просто без лога."""
    try:
        logging.basicConfig(
            filename=os.path.join(data_dir(), "mouse_monitor.log"),
            filemode="a",
            level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(threadName)-10s %(message)s",
            encoding="utf-8",
        )
        return data_dir()
    except OSError:
        return None


# Очередь событий ограничена. Продюсер -- поток низкоуровневого хука, до
# 1000 событий/с; при затыке главного потока неограниченная очередь растёт
# молча, а события старше секунды для оверлея всё равно бесполезны.
# 2000 -- примерно две секунды запаса при 1000 Гц.
EVENT_QUEUE_MAXSIZE = 2000


# --- DPI awareness и масштабирование интерфейса ------------------------------
# Уровень awareness обязан быть выставлен ДО создания окон и до любого чтения
# метрик экрана: неосведомлённому процессу Windows отдаёт логические значения
# (при масштабе 150% -- 1707x960 вместо физических 2560x1440), из-за чего
# теплокарта строится уменьшенной, а окна растягиваются битмапом.

DPI_AWARENESS = "UNKNOWN"   # фактический уровень, заполняет enable_dpi_awareness()
UI_SCALE = 1.0              # множитель размеров, заполняет apply_ui_scaling()

_DPI_LEVELS = {0: "UNAWARE", 1: "SYSTEM_AWARE", 2: "PER_MONITOR_AWARE"}


def current_dpi_awareness():
    """Фактический уровень awareness процесса, а не тот, который запрашивали."""
    try:
        value = ctypes.c_int(-1)
        if ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(value)) == 0:
            return _DPI_LEVELS.get(value.value, str(value.value))
    except (AttributeError, OSError):
        pass
    return "UNKNOWN"


def enable_dpi_awareness():
    """Объявляет процесс DPI-осведомлённым. Вызывать до tk.Tk().

    Проверяется ВОЗВРАЩАЕМОЕ значение, а не только исключения: при неудаче
    SetProcessDpiAwarenessContext молча возвращает 0, ничего не бросая.
    Отдельно важен argtypes: параметр -- pointer-sized HANDLE, и без явного
    c_void_p значение -4 на x64 обрезается до 32 бит, из-за чего вызов
    проваливается всегда.

    Возвращает (фактический_уровень, каким_вызовом_получен).
    """
    global DPI_AWARENESS

    # Манифест мог выставить уровень ещё до старта Python -- так и происходит
    # в собранном EXE. Проверяем это ПЕРВЫМ делом, потому что иначе каскад
    # припишет заслугу себе: SetProcessDPIAware() возвращает TRUE и на уже
    # осведомлённом процессе, и лог сообщал бы "через SetProcessDPIAware()"
    # (то есть SYSTEM_AWARE), хотя фактический уровень -- PER_MONITOR_AWARE
    # от манифеста.
    already = current_dpi_awareness()
    if already in ("PER_MONITOR_AWARE", "SYSTEM_AWARE"):
        DPI_AWARENESS = already
        return DPI_AWARENESS, "манифест приложения"

    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_int
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        for context, name in ((-4, "SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)"),
                              (-3, "SetProcessDpiAwarenessContext(PER_MONITOR_AWARE)")):
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(context)):
                DPI_AWARENESS = current_dpi_awareness()
                return DPI_AWARENESS, name
    except (AttributeError, OSError):
        pass    # Windows старше 10 1703

    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:  # S_OK
            DPI_AWARENESS = current_dpi_awareness()
            return DPI_AWARENESS, "SetProcessDpiAwareness(2)"
    except (AttributeError, OSError):
        pass    # Windows старше 8.1

    try:
        if user32.SetProcessDPIAware():
            DPI_AWARENESS = current_dpi_awareness()
            return DPI_AWARENESS, "SetProcessDPIAware()"
    except (AttributeError, OSError):
        pass

    # Сюда попадаем, только если процесс НЕ был осведомлён на входе и ни один
    # вызов не сработал -- то есть это настоящий отказ.
    DPI_AWARENESS = current_dpi_awareness()
    return DPI_AWARENESS, "все вызовы отклонены"


def monitor_dpi(hwnd=None):
    """Фактический DPI. Осмысленно только ПОСЛЕ enable_dpi_awareness():
    неосведомлённому процессу Windows всегда отвечает 96.

    Типы проставлены явно по той же причине, что и в enable_dpi_awareness():
    HWND, HMONITOR и HDC -- pointer-sized, а ctypes без argtypes/restype
    считает их c_int и на x64 режет до 32 бит. Нижние ветки недостижимы на
    Windows 10 1607+ (GetDpiForWindow отрабатывает первым), но полагаться на
    это как на причину не ставить типы -- значит помнить об этом вечно.
    """
    user32 = ctypes.windll.user32
    if hwnd:
        try:
            user32.GetDpiForWindow.restype = ctypes.c_uint
            user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
            dpi = user32.GetDpiForWindow(ctypes.c_void_p(hwnd))
            if dpi:
                return dpi
        except (AttributeError, OSError):
            pass    # Windows старше 10 1607
    try:
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        monitor = user32.MonitorFromPoint(wintypes.POINT(0, 0), 1)
        shcore = ctypes.windll.shcore
        shcore.GetDpiForMonitor.restype = ctypes.c_long
        shcore.GetDpiForMonitor.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                            ctypes.POINTER(ctypes.c_uint),
                                            ctypes.POINTER(ctypes.c_uint)]
        dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
        if shcore.GetDpiForMonitor(monitor, 0,
                                   ctypes.byref(dpi_x),
                                   ctypes.byref(dpi_y)) == 0:
            return dpi_x.value
    except (AttributeError, OSError):
        pass
    try:
        user32.GetDC.restype = ctypes.c_void_p
        user32.GetDC.argtypes = [ctypes.c_void_p]
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32 = ctypes.windll.gdi32
        gdi32.GetDeviceCaps.restype = ctypes.c_int
        gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
        hdc = user32.GetDC(None)
        try:
            return gdi32.GetDeviceCaps(hdc, 88)    # LOGPIXELSX
        finally:
            user32.ReleaseDC(None, hdc)
    except (AttributeError, OSError):
        pass
    return 96


def apply_ui_scaling(root):
    """Приводит интерфейс к фактическому DPI.

    Само по себе включение awareness убирает растяжение битмапом, но геометрию
    не пересчитывает: 380x780 логических стали бы 380x780 физическими, то есть
    при масштабе 150% окно ужалось бы в полтора раза. Шрифты заданы в пунктах
    и чинятся через tk scaling; явные размеры в пикселях -- через px().

    При масштабе 100% (dpi=96) множитель равен 1.0 и px() возвращает исходные
    значения, то есть поведение не отличается от прежнего.
    """
    global UI_SCALE
    dpi = monitor_dpi(root.winfo_id())
    UI_SCALE = dpi / 96.0
    root.tk.call("tk", "scaling", dpi / 72.0)
    return dpi, UI_SCALE


def px(value):
    """Логический размер в пикселях -> физический, с учётом масштаба дисплея."""
    return int(round(value * UI_SCALE))


def window_title(lang):
    """Заголовок окна: имя программы и версия.

    Версия НЕ дублируется строкой в панели. Заголовок виден всегда и при
    любом размере окна, версия есть ещё и в шапке сводки, а третья копия в
    колонке живых показаний была бы статической строкой среди меняющихся --
    то есть шумом, и стоила бы высоты минимальному окну.
    """
    return TRANSLATIONS.get(lang, TRANSLATIONS["English"])["win_title"].format(
        APP_VERSION)


def tray_tip(lang):
    """Имя с версией для подсказки области уведомлений."""
    return TRANSLATIONS.get(lang, TRANSLATIONS["English"])["tray_tip"].format(
        APP_VERSION)


# Режимы положения оверлея. Ключи внутренние и от языка не зависят;
# подписи берутся из словаря локализации по "pos_" + ключ.
POSITION_MODES = ("cursor", "top_left", "top_center", "top_right")

# Пороги детекции дребезга. ЭТО ЭВРИСТИКА, НЕ КАЛИБРОВКА: мыши с реальным
# дребезгом для снятия данных не было, значения выведены из механики, а не
# измерены на железе.
#
# 8 мс -- зона, где человека физически нет: даже drag-click (30-40 кликов/с)
# оставляет между отпусканием и нажатием не меньше 12-15 мс. Механический
# дребезг контакта живёт именно здесь, в единицах миллисекунд. Прежние 25 мс
# начинали давать ложные срабатывания с 20 кликов/с, то есть ровно на той
# технике, ради которой утилиту и ставят.
#
# Основной детектор -- не пауза, а ДЛИТЕЛЬНОСТЬ нажатия: дребезговое
# "нажатие" длится единицы миллисекунд, осознанное -- десятки, и по этому
# признаку человек и неисправность расходятся куда надёжнее.
DC_FAULT_GAP = 0.008        # отпускание -> нажатие быстрее этого = неисправность
DC_SUSPECT_GAP = 0.025      # ... и до этого = подозрительно, но не приговор
DC_SHORT_PRESS = 0.015      # само нажатие короче этого = неисправность (основной)

# --- Износ энкодера колеса ---------------------------------------------------
# Изношенный энкодер даёт фантомный тик в сторону, обратную прокрутке: крутишь
# вниз, страница дёргается вверх. По природе это тот же дребезг контакта, но на
# другом органе, и признак тот же -- обратный тик СЛИШКОМ БЫСТРО после прямого.
#
# 50 мс -- инженерная оценка, НЕ калибровка: колеса с изношенным энкодером для
# снятия данных не было, ровно как и мыши с дребезгом кнопки. Осознанная смена
# направления занимает у руки заметно больше, глитч энкодера укладывается в
# единицы миллисекунд.
WHEEL_REVERSAL_GAP = 0.050

# Колесо высокого разрешения (свободный ход) шлёт приращения МЕНЬШЕ WHEEL_DELTA,
# а pynput делит на него ЦЕЛОЧИСЛЕННО (mouse/_win32.py: dd = SHORT(...) // 120)
# и возвращает 0 без ошибки. Направления у такого тика нет, детектировать по
# нему нечего. Если доля таких тиков велика -- счёт объявляется недоступным.
#
# ЗАМЕРЕНО на машине разработки (tests/probe_step1.py): 4 тика, все ровно 120,
# нулей нет. Выборка тонкая, у читателя с GitHub колесо может быть другим,
# поэтому конструкция не полагается на этот результат.
WHEEL_ZERO_SHARE = 0.20      # доля нулевых тиков, выше которой считать нельзя
WHEEL_MIN_TICKS = 5          # меньше тиков -- судить не о чем

WHEEL_OK = "ok"              # счёт достоверен
WHEEL_NONE = "none"          # прокрутки не было вовсе
WHEEL_FEW = "few"            # тики есть, но их мало для суждения
WHEEL_UNUSABLE = "unusable"  # колесо высокого разрешения: pynput отдаёт нули


def wheel_health(ticks, zeros, reversals):
    """ЕДИНСТВЕННОЕ место, где решается, можно ли доверять счёту по колесу.

    Те же правила, что у оценки периода репортов: показать "недоступно"
    правильнее, чем показать число, полученное из данных, в которых половина
    тиков потеряла направление.

    ticks -- всего событий колеса, zeros -- из них без направления
    (dx == 0 и dy == 0), reversals -- обнаруженных обратных тиков.
    """
    out = {"state": WHEEL_NONE, "ticks": ticks, "zeros": zeros,
           "reversals": reversals, "zero_share": 0.0}
    if ticks <= 0:
        return out
    out["zero_share"] = zeros / ticks
    if out["zero_share"] > WHEEL_ZERO_SHARE:
        # Систематические нули -- это не тишина, о них надо СКАЗАТЬ.
        out["state"] = WHEEL_UNUSABLE
        return out
    if ticks < WHEEL_MIN_TICKS:
        # Отдельное состояние, а не WHEEL_NONE: тики БЫЛИ, и говорить
        # "прокрутки не было" -- прямая неправда. Пользователь крутит колесо,
        # видит "прокрутки не было" и справедливо считает это багом.
        out["state"] = WHEEL_FEW
        return out
    out["state"] = WHEEL_OK
    return out


# Разделитель признаков в колонке Flag, когда на одном эпизоде сработали оба.
# Счётчик при этом растёт на ЕДИНИЦУ: короткая пауза перед нажатием и короткое
# само нажатие -- это один отскок контакта, увиденный с двух сторон, а не два
# разных дефекта. Прежде эпизод давал +2, и число на экране было вдвое больше
# числа физических отскоков.
DC_FLAG_SEP = "|"

# Постоянная времени сглаживания индикатора изменения скорости.
# Прежние фиксированные веса 0.85/0.15 задавали окно, зависящее от частоты
# событий: -dt/ln(0.85) даёт 6.2 мс при 1000 событий/с и 103 мс при 60.
# Показание менялось от того, как быстро идут события, а не от движения руки.
# 60 мс выбраны по читаемости: значение устаканивается за 3*tau = 180 мс,
# то есть около пяти различимых показаний в секунду -- примерно столько
# человек и способен прочитать с бегущего счётчика.
ACCEL_TAU = 0.06

# Делитель показания dV. Величина остаётся индексом, а не измерением, поэтому
# сам делитель условен -- важно, что он ОДИН на обоих потребителей. Прежде на
# оверлей шло accel/100, а в CSV -- accel, и одно и то же движение выглядело в
# файле в сто раз крупнее, чем на экране.
DV_SCALE = 100


def dv_index(accel):
    """Показание dV: одно число и для оверлея, и для колонки SpeedChange."""
    return int(accel / DV_SCALE)


# --- Оценка периода репортов устройства -------------------------------------
# Межсобытийные интервалы хука несут период репортов мыши, но ТОЛЬКО пока
# движение достаточно быстрое. На медленном движении не каждый репорт сдвигает
# курсор на пиксель, и гистограмма показывает зернистость пересечения границ
# пикселей, а не устройство.
#
# Пороги ниже -- не настройка вкуса, а условие осмысленности, и они ПРОВЕРЕНЫ
# замером (tests/probe_step1.py):
#   при 741 px/с и 265 событиях/с -- мода 1.0-1.1 мс и гармоническая лестница
#   2x/3x/4x/5x с убывающими долями, то есть период ~1 мс;
#   при 17 событиях/с та же методика дала уверенную моду 7.0-7.1 мс с
#   удвоением на 90-м процентиле -- число, которое выглядит настоящим и неверно.
#
# Поэтому оценка обязана МОЛЧАТЬ, когда условия не выполнены: показать
# "недостаточно данных" правильнее, чем показать правдоподобную ошибку.
RATE_WINDOW = 2.0            # скользящее окно оценки, с
RATE_MIN_RATE = 200.0        # событий/с в окне; ниже -- движение слишком медленное
RATE_MAX_GAP = 0.050         # интервал длиннее -- пауза, в распределение не идёт
RATE_BIN = 0.0001            # корзина гистограммы, с (0.1 мс -- как в замере)
RATE_MIN_SAMPLES = 200       # интервалов в распределении
RATE_MIN_MODE_SHARE = 0.15   # доля моды; ниже -- распределение размазано
RATE_HARMONICS = 5           # сколько кратных пиков считать в лестнице
RATE_REFRESH = 0.5           # как часто пересчитывать, с

# --- Привязка измеренного периода к отраслевой шкале -------------------------
# Ступени частоты опроса, которые знает любой, кто выбирал мышь.
POLLING_STEPS = (125, 250, 500, 1000, 2000, 4000, 8000)

# Допуск выведен из разрешения САМОГО метода, а не подобран на глаз.
# Корзина гистограммы RATE_BIN = 0.1 мс. На ступени 1000 Гц (период 1.0 мс)
# это 10% периода, так что 12% -- одна корзина плюс небольшой запас.
# Ступени отстоят вдвое, то есть на 100% относительной разницы: середина
# промежутка между 1000 и 2000 Гц -- 0.75 мс, это 25% ниже верхней ступени и
# 50% выше нижней, и в допуск 12% не попадает НИ ОДНА. Так и задумано:
# попадание в середину означает плохой замер, а не мышь на 1333 Гц.
RATE_STEP_TOLERANCE = 0.12

STEP_OK = "step"             # период уверенно лёг на ступень
STEP_BETWEEN = "between"     # ни одна ступень не попала в допуск
STEP_TOO_FINE = "fine"       # ступени ближе, чем разрешение метода


def polling_step(period_ms):
    """Ближайшая отраслевая ступень -- либо честный отказ её назвать.

    Возвращает (частота ступени или None, состояние).

    Разрешение метода ограничено шириной корзины: полукорзина -- 0.05 мс.
    Если допуск вокруг ступени уже этого, соседние ступени неразличимы, и
    называть их нечестно. При корзине 0.1 мс это всё, что быстрее ~2400 Гц:
    4000 и 8000 Гц эта методика не различает и не должна делать вид, что да.
    """
    if not period_ms or period_ms <= 0:
        return None, STEP_TOO_FINE
    if period_ms * RATE_STEP_TOLERANCE < RATE_BIN * 1000.0 / 2.0:
        return None, STEP_TOO_FINE
    for step in POLLING_STEPS:
        ideal = 1000.0 / step
        if abs(period_ms - ideal) <= ideal * RATE_STEP_TOLERANCE:
            return step, STEP_OK
    return None, STEP_BETWEEN


# Потолки выборок за сессию. Прореживание вдвое, а не "первые N": покрытие
# всей сессии сохраняется, тогда как обрезание по началу описывало бы только
# первые секунды и молча врало бы про длинную сессию.
DV_SAMPLE_CAP = 20000
DBLCLK_PAIR_CAP = 5000


def percentile(values, fraction):
    """Порядковая статистика без numpy. values должен быть отсортирован."""
    if not values:
        return 0
    index = int(round(fraction * (len(values) - 1)))
    return values[max(0, min(index, len(values) - 1))]


RATE_OK = "ok"               # оценка получена
RATE_SLOW = "slow"           # движение слишком медленное
RATE_UNSURE = "unsure"       # данных мало либо распределение размазано


def report_rate_estimate(intervals, window=RATE_WINDOW):
    """ЕДИНСТВЕННОЕ место, где решается, годна ли выборка, и считается оценка.

    Условия собраны здесь целиком и намеренно НЕ размазаны по вызывающим:
    любое из них, ослабленное в одном месте, превращает показание в
    правдоподобную ошибку, а её потом не отличить от измерения.

    intervals -- межсобытийные интервалы в секундах за последнее окно.
    Возвращает словарь; state -- одно из RATE_OK / RATE_SLOW / RATE_UNSURE.
    """
    out = {"state": RATE_UNSURE, "period_ms": None, "hz": None,
           "mode_share": 0.0, "samples": 0, "rate": 0.0, "ladder": []}
    if not intervals or window <= 0:
        return out

    # Условие 1: темп. Считается по ОКНУ, а не по времени, покрытому
    # событиями: иначе короткий рывок внутри простоя набрал бы "быстрые"
    # интервалы и прошёл порог.
    out["rate"] = len(intervals) / window
    if out["rate"] < RATE_MIN_RATE:
        out["state"] = RATE_SLOW
        return out

    # Условие 2: паузы выбрасываются -- они про руку, а не про устройство.
    moving = [value for value in intervals if value < RATE_MAX_GAP]
    out["samples"] = len(moving)
    if len(moving) < RATE_MIN_SAMPLES:
        return out

    # Условие 3: мода должна быть выражена. Размазанное распределение значит,
    # что периодического источника сквозь доставку не видно.
    bins = {}
    for value in moving:
        # Эпсилон не косметика: int(0.001 / 0.0001) даёт 9, а не 10 --
        # ровно кратные интервалы иначе уезжают в соседнюю корзину.
        key = int(value / RATE_BIN + 1e-9)
        bins[key] = bins.get(key, 0) + 1
    mode_key = max(bins, key=lambda k: bins[k])
    out["mode_share"] = bins[mode_key] / len(moving)
    if out["mode_share"] < RATE_MIN_MODE_SHARE:
        return out

    # Период -- СРЕДНЕЕ внутри корзины моды, а не её центр. Центр даёт
    # систематическую ошибку до половины корзины (при 0.1 мс и периоде 1 мс
    # это 5%), и на ровном периоде показание уезжало на 1053 Гц вместо 1000.
    in_mode = [value for value in moving
               if int(value / RATE_BIN + 1e-9) == mode_key]
    period = sum(in_mode) / len(in_mode)
    if period <= 0:
        return out

    # Гармоническая лестница: доли интервалов около k-кратного периода.
    # Именно она отличает измерение от догадки -- у случайного распределения
    # кратных пиков нет, а у периодического источника, часть репортов которого
    # не сдвинула курсор, они обязаны быть, с убыванием.
    # Считается по НОМЕРАМ корзин, а не по границам в секундах: сравнение
    # вещественных границ промахивается мимо ровно кратных интервалов на
    # ошибке округления (проверено -- на синтетике с точным периодом доля
    # второй ступени выходила нулевой). Допуск растёт с кратностью: джиттер
    # k-го пика накапливается k раз.
    for k in range(1, RATE_HARMONICS + 1):
        target = mode_key * k
        hits = sum(count for key, count in bins.items()
                   if abs(key - target) <= k)
        out["ladder"].append((k, hits / len(moving)))

    out["state"] = RATE_OK
    out["period_ms"] = period * 1000.0
    out["hz"] = 1.0 / period
    return out


# Версия формата CSV. Фаза 4: добавлена колонка Flag, пишутся и нажатия, и
# отпускания, колонка Accel переименована в SpeedChange и больше не берётся по
# модулю. Фаза 6: SpeedChange приведён к масштабу экранного dV, в Flag может
# стоять пара признаков через DC_FLAG_SEP. Фаза 9: появились события колеса --
# Scroll_Up/Scroll_Down/Scroll_Left/Scroll_Right/Scroll_Zero -- и признак
# WHEEL_REVERSAL в колонке Flag. Набор колонок не менялся.
CSV_FORMAT_VERSION = 4

# Версия приложения. Поднимается РУКАМИ, в ОДНОМ месте: отсюда её берут и
# шапка сводки, и заголовок окна, и подсказка трея. Набранная руками строка
# "v3.1" где-нибудь ещё однажды отстала бы от этой -- поэтому её нет нигде.
#
# Смысл versionирования: сводка уходит в баг-репорты, и читающий должен
# понимать, от какой сборки она, не спрашивая автора. Раньше версия жила
# ТОЛЬКО в сводке, то есть в файле после остановки: пользователь не мог
# назвать свою сборку, не проведя сессию. Теперь она в заголовке окна,
# который виден всегда.
#
# Форматы CSV и сводки версионируются отдельно и точнее -- их читают
# программы, а версию приложения читает человек.
APP_VERSION = "3.1"

# Версия формата сводки. Поднимается, когда меняется состав или порядок
# разделов, чтобы чужой разборщик не гадал, что перед ним.
SUMMARY_FORMAT_VERSION = 1

# Горизонтальный отступ закреплённого оверлея от края рабочей области.
# По вертикали оверлей ставится вплотную, без зазора.
PINNED_MARGIN = 8

# Имя в подсказке трея. Туда же дописывается состояние колеса.
# Версия подставляется из APP_VERSION -- см. tray_title_text().
TRAY_TITLE = "Mouse Monitor"

# Предел длины подсказки области уведомлений: Shell_NotifyIcon обрезает szTip
# по 128 символов вместе с завершающим нулём. Длина проверяется стендом на
# всех состояниях колеса и обоих языках, а не предполагается.
TRAY_TIP_LIMIT = 127

# --- Вёрстка -----------------------------------------------------------------
# Ширина колонки контента в логических пикселях. Всё содержимое живёт ВНУТРИ
# неё; окно может быть какой угодно ширины, колонка остаётся этой и стоит у
# ЛЕВОГО края. Раньше контейнер занимал всё окно, и в нём соседствовали четыре
# разных горизонтальных поведения (anchor="w", центр по умолчанию, fill="x" и
# фиксированный wraplength) -- на растянутом окне они расходились в четыре
# стороны.
#
# 420 вместо прежних 380: потолок высоты снят, и в панель вернулась строка
# состояния колеса, а самая длинная строка показания по-русски занимает
# 511 физ. при внутренней ширине 525 -- запас был на пределе.
PANEL_WIDTH = 420
PANEL_PAD = 15               # поле внутри колонки
PANEL_MARGIN = 12            # минимальное поле между колонкой и краем окна


def work_area_at(x, y):
    """Рабочая область монитора, которому принадлежит точка (x, y).

    Именно рабочая область, а не весь экран: панель задач может стоять
    сверху, и прижатый к границе экрана оверлей уехал бы под неё.

    Берётся из GetMonitorInfo, а не из SPI_GETWORKAREA: во-первых, pywin32
    не реализует это действие (NotImplementedError: Action 48), во-вторых,
    SPI_GETWORKAREA относится только к основному монитору, а закрепляться
    нужно на том, где сейчас курсор.

    Координаты физические и уже в системе виртуального экрана: на
    мультимониторе левый или верхний край может быть отрицательным, и
    отдельно вычитать SM_XVIRTUALSCREEN не требуется.
    """
    try:
        monitor = win32api.MonitorFromPoint((int(x), int(y)),
                                            win32con.MONITOR_DEFAULTTONEAREST)
        return win32api.GetMonitorInfo(monitor)["Work"]
    except (pywintypes.error, KeyError, TypeError):
        logging.exception("не удалось определить рабочую область монитора")
        left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        return (left, top,
                left + win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN),
                top + win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN))


_TRAY_FONT = None


def tray_font():
    """Шрифт для иконки в трее.

    Кэшируется: ImageFont.truetype читает файл с диска, а иконка
    перерисовывается дважды в секунду всё время работы приложения.
    """
    global _TRAY_FONT
    if _TRAY_FONT is not None:
        return _TRAY_FONT
    for path in ("arial.ttf", "C:/Windows/Fonts/arial.ttf", "calibri.ttf"):
        try:
            _TRAY_FONT = ImageFont.truetype(path, 28)
            return _TRAY_FONT
        except OSError:
            continue        # шрифта нет по этому пути -- пробуем следующий
    _TRAY_FONT = ImageFont.load_default()
    return _TRAY_FONT


def device_discriminator(device_id):
    """VID/PID из DeviceID, чтобы различать устройства в списке.

    Windows отдаёт всем указывающим устройствам одинаковые Manufacturer и
    Name (общее имя HID-драйвера), поэтому четыре РАЗНЫХ устройства
    выглядели в панели как одно, повторённое четырежды.
    """
    if not device_id:
        return ""
    match = re.search(r"VID_[0-9A-F]{4}&PID_[0-9A-F]{4}", device_id, re.I)
    if match:
        return " [%s]" % match.group(0).upper()
    parts = device_id.split("\\")
    if len(parts) > 1 and parts[1]:
        return " [%s]" % parts[1].split("&")[0].upper()
    return ""


SKINS = {
    "Dark (Default)": {
        "bg": "#1e1e1e", 
        "pos_fg": "#ecf0f1", 
        "accel_fg": "#2ecc71", 
        "hz_fg": "#e74c3c", 
        "cps_fg": "#f39c12", 
        "alpha": 0.8
    },
    "Cyberpunk": {
        "bg": "#000000", 
        "pos_fg": "#f1c40f", 
        "accel_fg": "#ff00ff", 
        "hz_fg": "#00ffff", 
        "cps_fg": "#00ff00", 
        "alpha": 0.85
    },
    "Matrix": {
        "bg": "#000000", 
        "pos_fg": "#00ff00", 
        "accel_fg": "#008f11", 
        "hz_fg": "#00ff00", 
        "cps_fg": "#008f11", 
        "alpha": 0.7
    }
}

TRANSLATIONS = {
    "English": {
        "hw_info_title": "HARDWARE INFORMATION",
        "device": "Device",
        "win_speed": "Win Speed",
        "pointer_precision": "Pointer precision",
        "state_on": "on",
        "state_off": "off",
        "unknown": "unknown",
        "display_settings": "DISPLAY SETTINGS",
        "show_pos": "Show coordinates (XY)",
        "show_accel": "Show cursor speed change (dV, relative index)",
        "show_hz": "Show cursor event rate",
        "show_cps": "Show click frequency (CPS)",
        "show_faults": "Show button faults (DC)",
        "enable_logging": "Enable logging (.csv)",
        "enable_heatmap": "Generate heatmap (.png)",
        "overlay_style": "OVERLAY STYLING",
        "click_through": "Click-through mode",
        "transparency": "Transparency:",
        "skin_choice": "SELECT SKIN:",
        "pos_choice": "OVERLAY POSITION:",
        "pos_cursor": "Follow cursor",
        "pos_top_left": "Top left",
        "pos_top_center": "Top center",
        "pos_top_right": "Top right",
        "btn_start": "START MONITORING",
        "btn_stop": "STOP MONITORING",
        "hz_label": "Cursor events: {}/s (all devices)",
        "faults_label": "Faults (DC): L:{} | R:{}",
        "suspect_label": "Suspicious: L:{} | R:{}",
        "dc_note": "DC thresholds are a heuristic, not a calibration: "
                   "fault < {} ms or press < {} ms, suspicious < {} ms",
        "dropped_label": "Dropped events: {}",
        "rate_ok_step": "Report period: {} ms (~{} Hz, standard {} Hz step)",
        "rate_ok_between": "Report period: {} ms (~{} Hz, between steps)",
        "rate_ok_fine": "Report period: {} ms (~{} Hz, too fast to place)",
        "rate_slow": "Report period: move faster to measure",
        "rate_unsure": "Report period: not enough data",
        "wheel_ok": "Wheel: {} ticks, {} reversals",
        "wheel_none": "Wheel: no scrolling yet",
        "wheel_few": "Wheel: {} ticks, too few to judge",
        "wheel_unusable": "Wheel: high-resolution, cannot count",
        "log_active": "Log: {}",
        "log_failed": "Log: FAILED (see mouse_monitor.log)",
        "map_active": "Map active",
        "log_saved": "Log saved",
        "map_saved": "Map saved",
        "lang_choice": "LANGUAGE:",
        # Имя программы -- имя собственное, на русский не переводится;
        # ключи заведены ради единообразия наборов и чтобы строку можно
        # было поправить не трогая код. {} -- APP_VERSION.
        "win_title": "Mouse Monitor Pro v{}",
        "tray_tip": "Mouse Monitor v{}",
        # Подписи графиков. У dV в заголовке ПРЯМО сказано, что величина
        # относительная и без единиц: иначе шкала читается как измерение.
        "graph_hz_title": "Cursor events, per second",
        "graph_dv_title": "dV, relative index (no units)",
        "graph_no_data": "no data",
        "graph_sec": "s",
        "graph_hint_off": "Graphs: hidden, stretch the window to the right",
        "graph_hint_on": "Graphs: cursor event rate and dV, on the right",
        "tray_expand": "Expand",
        "tray_exit": "Exit",
        # Подписи на оверлее. Формат внутри строки: оверлей узкий (px(115)),
        # и подпись подобрана под ширину -- см. проверку ширины в Фазе 6.
        # L/R не переводятся намеренно, как и в faults_label.
        "ov_pos": "XY: {}, {}",
        "ov_accel": "dV: {:>+5}",
        "ov_hz": "Ev/s: {}",
        "ov_cps": "CPS: {}",
        "ov_faults": "DC: L:{} R:{}"
    },
    "Русский": {
        "hw_info_title": "ИНФОРМАЦИЯ О ЖЕЛЕЗЕ",
        "device": "Устройство",
        "win_speed": "Скорость Win",
        "pointer_precision": "Точность указателя",
        "state_on": "вкл",
        "state_off": "выкл",
        "unknown": "неизвестно",
        "display_settings": "НАСТРОЙКИ ОТОБРАЖЕНИЯ",
        "show_pos": "Показывать координаты (XY)",
        "show_accel": "Скорость курсора (dV, относительный индекс)",
        "show_hz": "Частота событий курсора",
        "show_cps": "Показывать клики (CPS)",
        "show_faults": "Ошибки кнопок (даблклик)",
        "enable_logging": "Включить запись лога (.csv)",
        "enable_heatmap": "Генерировать тепловую карту (.png)",
        "overlay_style": "СТИЛИЗАЦИЯ OVERLAY",
        "click_through": "Click-through (сквозь окно)",
        "transparency": "Прозрачность:",
        "skin_choice": "ВЫБОР СКИНА:",
        "pos_choice": "ПОЛОЖЕНИЕ OVERLAY:",
        "pos_cursor": "За курсором",
        "pos_top_left": "Сверху слева",
        "pos_top_center": "Сверху по центру",
        "pos_top_right": "Сверху справа",
        "btn_start": "ЗАПУСТИТЬ МОНИТОРИНГ",
        "btn_stop": "ОСТАНОВИТЬ",
        "hz_label": "События курсора: {}/с (все устройства)",
        "faults_label": "Ошибки (DC): L:{} | R:{}",
        "suspect_label": "Подозрительные: L:{} | R:{}",
        "dc_note": "Пороги DC -- эвристика, а не калибровка: "
                   "ошибка < {} мс или нажатие < {} мс, подозрение < {} мс",
        "dropped_label": "Потеряно событий: {}",
        "rate_ok_step": "Период репортов: {} мс (~{} Гц, ступень {} Гц)",
        "rate_ok_between": "Период репортов: {} мс (~{} Гц, между ступенями)",
        "rate_ok_fine": "Период репортов: {} мс (~{} Гц, быстрее шкалы)",
        "rate_slow": "Период репортов: нужно движение быстрее",
        "rate_unsure": "Период репортов: недостаточно данных",
        "wheel_ok": "Колесо: тиков {}, обратных {}",
        "wheel_none": "Колесо: прокрутки не было",
        "wheel_few": "Колесо: тиков {}, мало для оценки",
        "wheel_unusable": "Колесо: высокое разрешение, счёт недоступен",
        "log_active": "Лог: {}",
        "log_failed": "Лог: ОШИБКА (см. mouse_monitor.log)",
        "map_active": "Карта активна",
        "log_saved": "Лог сохранен",
        "map_saved": "Карта сохранена",
        "lang_choice": "ЯЗЫК:",
        "win_title": "Mouse Monitor Pro v{}",
        "tray_tip": "Mouse Monitor v{}",
        "graph_hz_title": "События курсора, в секунду",
        "graph_dv_title": "dV, относительный индекс (без единиц)",
        "graph_no_data": "нет данных",
        "graph_sec": "с",
        "graph_hint_off": "Графики: скрыты, растяните окно вправо",
        "graph_hint_on": "Графики: частота событий курсора и dV, справа",
        "tray_expand": "Развернуть",
        "tray_exit": "Выход",
        "ov_pos": "XY: {}, {}",
        "ov_accel": "dV: {:>+5}",
        "ov_hz": "Соб/с: {}",
        "ov_cps": "CPS: {}",
        "ov_faults": "DC: L:{} R:{}"
    }
}

class HeatmapManager:
    def __init__(self, grid_size=20):
        self.grid_size = grid_size
        self.data = {}
        self.is_active = False
        self.refresh_screen_metrics()

    def refresh_screen_metrics(self):
        # Поддержка нескольких мониторов (виртуальный экран).
        # Перечитывается на старте каждой сессии: конфигурация дисплеев могла
        # измениться с момента запуска приложения (подключили монитор, сменили
        # разрешение), а от этих значений зависит и маппинг, и размер PNG.
        self.screen_left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        self.screen_top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        self.screen_w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        self.screen_h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)

    def start(self):
        self.data = {}
        self.refresh_screen_metrics()
        self.is_active = True

    def update(self, x, y):
        if not self.is_active: return
        # Учитываем смещение виртуального экрана для корректного маппинга.
        # Координаты подрезаются по границам: курсор может оказаться вне
        # закэшированных метрик (сменилась конфигурация дисплеев посреди
        # сессии), и тогда отрицательный индекс дал бы прямоугольник за
        # пределами холста, то есть молча потерянные события.
        cx = min(max(x, self.screen_left), self.screen_left + self.screen_w - 1)
        cy = min(max(y, self.screen_top), self.screen_top + self.screen_h - 1)
        gx = int((cx - self.screen_left) // self.grid_size)
        gy = int((cy - self.screen_top) // self.grid_size)
        key = (gx, gy)
        self.data[key] = self.data.get(key, 0) + 1

    def save(self):
        # Флаг снимается ПЕРВЫМ делом и на всех исходах: сессия карты
        # закончилась в любом случае. Прежде он оставался поднятым на пустых
        # данных и в ветке except, и следующая сессия -- уже со снятой
        # галочкой -- продолжала копить и записывала PNG, подмешивая туда
        # данные предыдущей.
        self.is_active = False
        if not self.data: return None
        try:
            directory = os.path.join(data_dir(), "heatmaps")
            os.makedirs(directory, exist_ok=True)
                        
            img = Image.new('RGB', (self.screen_w, self.screen_h), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            values = list(self.data.values())
            if not values: return None
            max_val = max(values)
            
            for (gx, gy), val in self.data.items():
                intensity = int((val / max_val) * 255)
                # Градиент от синего к красному
                color = (intensity, 0, 255 - intensity)
                x1, y1 = gx * self.grid_size, gy * self.grid_size
                x2, y2 = x1 + self.grid_size, y1 + self.grid_size
                draw.rectangle([x1, y1, x2, y2], fill=color)
            
            fname = unique_path(
                directory,
                "heatmap_%s" % datetime.now().strftime("%Y%m%d_%H%M%S"), ".png")
            img.save(fname)
            return fname
        except Exception:
            # print уходил в никуда: сборка идёт с console=False.
            logging.exception("не удалось сохранить теплокарту")
            return None

class SessionLogger:
    def __init__(self):
        self.file = None
        self.writer = None
        self.filename = ""
        self.is_active = False

    def start(self):
        """Открывает файл сессии. Возвращает имя либо None, если не удалось.

        Отказ не имеет права уйти наружу: start() зовётся из обработчика
        кнопки уже ПОСЛЕ создания оверлея, а при console=False traceback
        уходит в никуда -- кнопка просто переставала бы работать. Каталог
        проверен на запись ещё в data_dir(), но носитель может отвалиться
        между проверкой и открытием файла.
        """
        try:
            directory = os.path.join(data_dir(), "logs")
            os.makedirs(directory, exist_ok=True)
            self.filename = unique_path(
                directory,
                "session_%s" % datetime.now().strftime("%Y%m%d_%H%M%S"), ".csv")
            # Режим 'x', а не 'w': если имя всё же занято -- например, второй
            # копией приложения, стартовавшей в ту же секунду, -- сессия
            # откажет ВИДИМО (ключ log_failed в UI), а не затрёт чужой лог.
            self.file = open(self.filename, mode='x', newline='', encoding='utf-8')
            self.writer = csv.writer(self.file)
            # Строка версии формата: по ней старые логи отличаются от новых.
            self.writer.writerow([f"# MouseMonitorPro CSV format v{CSV_FORMAT_VERSION}"])
            self.writer.writerow(["Timestamp", "Event", "Flag", "X", "Y", "Hz",
                                  "SpeedChange"])
            self.is_active = True
            return self.filename
        except OSError:
            logging.exception("не удалось открыть лог сессии %s", self.filename)
            self.file = None
            self.writer = None
            self.is_active = False
            return None

    def log(self, event_type, flag, x, y, hz, accel):
        """flag -- какой признак сработал: DC_FAULT_GAP, DC_FAULT_SHORT,
        DC_SUSPECT либо пустая строка. Отдельной колонкой, а не внутри
        события: иначе потом нечем калибровать пороги."""
        if self.is_active and self.writer:
            try:
                self.writer.writerow([datetime.now().isoformat(), event_type,
                                      flag, x, y, hz, accel])
            except Exception:
                logging.exception("не удалось записать строку в лог сессии")

    def stop(self):
        self.is_active = False
        if self.file:
            try:
                self.file.flush()
                self.file.close()
            except (OSError, ValueError):
                # ValueError -- flush() по уже закрытому объекту (проверено).
                # OSError -- диск заполнен либо носитель извлечён.
                logging.exception("не удалось корректно закрыть лог %s", self.filename)
            self.file = None
            self.writer = None

class MouseHardware:
    @staticmethod
    def get_mouse_info():
        try:
            c = wmi.WMI()
            info = []
            seen = set()
            for m in c.Win32_PointingDevice():
                # Дедупликация по DeviceID, а не по строке описания: описания
                # у разных устройств совпадают (Windows отдаёт общее имя
                # HID-драйвера), и склейка по ним потеряла бы устройства.
                if m.DeviceID in seen:
                    continue
                seen.add(m.DeviceID)
                info.append(f"{m.Manufacturer} {m.Name}"
                            f"{device_discriminator(m.DeviceID)}")
            return ", ".join(info) if info else "Generic Mouse"
        except Exception:
            # WMI и COM бросают разнородное: wmi.x_wmi, pywintypes.com_error,
            # AttributeError на отсутствующем классе. Перечислять их -- гадание,
            # поэтому широкий перехват, но обязательно с записью в лог.
            logging.exception("не удалось получить список указывающих устройств")
            return "Generic Mouse"

    @staticmethod
    def get_pointer_speed():
        """Скорость указателя Windows, 1..20 (ползунок в настройках мыши).

        Раньше называлась get_system_dpi_setting и звала
        win32api.SystemParametersInfo, которой в pywin32 не существует вовсе:
        AttributeError глушился голым except, и поле всегда показывало N/A.
        Функция живёт в win32gui.
        """
        try:
            return win32gui.SystemParametersInfo(win32con.SPI_GETMOUSESPEED)
        except (pywintypes.error, NotImplementedError):
            logging.exception("не удалось прочитать SPI_GETMOUSESPEED")
            return None

    @staticmethod
    def get_pointer_precision():
        """Включена ли Enhanced Pointer Precision (ускорение указателя).

        SPI_GETMOUSE возвращает (порог1, порог2, флаг). Пороги пользователю
        не нужны, важен сам факт: при включённом EPP смещение курсора
        нелинейно зависит от скорости движения, а значит искажаются и
        счётчик событий, и расчёт ускорения.

        Возвращает True/False, либо None если прочитать не удалось.
        """
        try:
            return bool(win32gui.SystemParametersInfo(win32con.SPI_GETMOUSE)[2])
        except (pywintypes.error, NotImplementedError, TypeError, IndexError):
            logging.exception("не удалось прочитать SPI_GETMOUSE")
            return None

class FloatingTracker(tk.Toplevel):
    def __init__(self, parent_panel, skin_config, show_config, alpha=0.8,
                 click_through=False, position_mode="cursor"):
        super().__init__(parent_panel.root)
        self.parent_panel = parent_panel
        self.config_data = skin_config
        self.show_config = show_config # Словарь с флагами видимости
        
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", alpha)
        self.configure(bg=self.config_data["bg"])

        self.set_click_through(click_through)
        
        self.font_style = ("Consolas", 9, "bold")
        self.labels = {}

        # Подписи берутся из того же словаря, что и вся панель. Прежде они были
        # захардкожены и оставались английскими при русском интерфейсе.
        # Ширина окна от этого не меняется: самая длинная строка -- координаты
        # ("XY: -1920, -1080", 160 из 172 физ.), а не подпись.
        t = self.tr()

        # Создаем только те элементы, которые выбрал пользователь
        if self.show_config.get('pos'):
            self.labels['pos'] = tk.Label(self, text=t["ov_pos"].format(0, 0), fg=self.config_data["pos_fg"], bg=self.config_data["bg"], font=self.font_style)
            self.labels['pos'].pack(fill="x")

        if self.show_config.get('accel'):
            self.labels['accel'] = tk.Label(self, text=t["ov_accel"].format(0), fg=self.config_data["accel_fg"], bg=self.config_data["bg"], font=self.font_style)
            self.labels['accel'].pack(fill="x")

        if self.show_config.get('hz'):
            self.labels['hz'] = tk.Label(self, text=t["ov_hz"].format(0), fg=self.config_data["hz_fg"], bg=self.config_data["bg"], font=self.font_style)
            self.labels['hz'].pack(fill="x")

        if self.show_config.get('cps'):
            self.labels['cps'] = tk.Label(self, text=t["ov_cps"].format(0), fg=self.config_data["cps_fg"], bg=self.config_data["bg"], font=self.font_style)
            self.labels['cps'].pack(fill="x")

        if self.show_config.get('faults'):
            self.labels['faults'] = tk.Label(self, text=t["ov_faults"].format(0, 0), fg="#e67e22", bg=self.config_data["bg"], font=self.font_style)
            self.labels['faults'].pack(fill="x")

        # Автоматический расчет высоты в зависимости от количества элементов
        active_count = sum(1 for v in self.show_config.values() if v)
        height = max(20, active_count * 20)
        # Размеры нужны для расчёта закреплённой позиции ещё до того, как
        # окно будет отрисовано, поэтому запоминаем, а не спрашиваем winfo_*.
        self.width = px(115)
        self.height = px(height)
        self.geometry(f"{self.width}x{self.height}")
        
        # Смещение окна вниз-вправо от горячей точки курсора. Атрибут
        # отсутствовал вовсе: обращение к нему падало AttributeError, гасилось
        # голым except, и оверлей не следовал за мышью ни разу.
        # Смещение обязано быть строго положительным, иначе горячая точка
        # попадёт внутрь окна и оверлей начнёт сам ловить клики
        # (click-through по умолчанию выключен). Запас сверх габарита курсора
        # (SM_CXCURSOR = 48 px при масштабе 150%) нужен ещё и потому, что окно
        # догоняет курсор с задержкой и на быстром движении вниз-вправо
        # курсор может его настигнуть.
        self.offset = px(24)

        self.position_mode = position_mode
        self.pinned_area = None
        # Счётчик обращений к geometry(): в закреплённом режиме он обязан
        # оставаться неизменным при движении мыши.
        self.geometry_calls = 0

        # Реальная позиция курсора вместо (0, 0): иначе первое же событие
        # движения даёт дистанцию через весь экран и выброс "ускорения",
        # а закрепить оверлей было бы не от чего.
        try:
            self.last_x, self.last_y = win32api.GetCursorPos()
        except pywintypes.error:
            logging.exception("не удалось прочитать позицию курсора")
            self.last_x, self.last_y = 0, 0
        self.last_time = time.perf_counter()
        self.last_velocity = 0
        self.event_times = []
        self.click_times = []
        # Метки времени -- только perf_counter(). Часовое время (time.time())
        # на Windows идёт с шагом глобального таймера (от 1 до 15.6 мс в
        # зависимости от постороннего софта) и непригодно для измерения
        # интервалов в десятки миллисекунд. Смешивание двух шкал приводило
        # к тому, что click_times не чистился и CPS не спадал к нулю.
        self.last_release_times = {"left": -1e9, "right": -1e9}
        self.last_press_times = {"left": -1e9, "right": -1e9}
        # Признак, выставленный на НАЖАТИИ текущего нажатия. Нужен, чтобы
        # отпускание того же эпизода не посчитало его неисправностью повторно.
        self.press_flags = {"left": "", "right": ""}
        self.fault_counts = {"left": 0, "right": 0}
        self.suspect_counts = {"left": 0, "right": 0}
        # Колесо. zeros -- тики, у которых направление потеряно делением на
        # WHEEL_DELTA; в детекции они не участвуют, но считаются, потому что
        # их доля решает, можно ли вообще показывать счёт.
        self.wheel_ticks = 0
        self.wheel_zeros = 0
        self.wheel_reversals = 0
        self.last_wheel_dir = 0
        self.last_wheel_time = -1e9
        self.hz = 0
        self.cps = 0
        self.current_accel = 0
        # Распределение |dV| за сессию. Нормы у величины нет и быть не может,
        # поэтому единственное честное сравнение -- пользователя с самим собой.
        self.dv_samples = []
        self.dv_seen = 0
        self.dv_step = 1            # шаг прореживания, растёт при переполнении
        # Пары последовательных нажатий одной кнопки: (интервал, |dx|, |dy|).
        # Нужны, чтобы сопоставить их с СИСТЕМНЫМИ правилами двойного клика.
        self.dblclk_pairs = []
        self.last_press_pos = {"left": None, "right": None}
        # Межсобытийные интервалы для оценки периода репортов: пары
        # (метка события, интервал до предыдущего). Чистятся не в цикле 10 мс,
        # а при пересчёте оценки раз в RATE_REFRESH -- на 1000 Гц это 2500
        # элементов, и перебирать их сто раз в секунду незачем.
        self.intervals = []
        
        self.apply_position(force=True)

    def tr(self):
        """Словарь перевода: оверлей следует за языком, выбранным в панели.

        Читается обычная строка current_lang, а не Tk-переменная и не метод
        панели: зависимость от родителя должна быть настолько узкой,
        насколько возможно, и одинаковой с MainControlPanel.tr().
        """
        return TRANSLATIONS.get(self.parent_panel.current_lang,
                                TRANSLATIONS["English"])

    @property
    def follow_cursor(self):
        return self.position_mode == "cursor"

    def move_to(self, x, y):
        """Единственное место, откуда двигается окно."""
        self.geometry_calls += 1
        self.geometry(f"+{int(x)}+{int(y)}")

    def set_position_mode(self, mode):
        """Смена режима на лету, при запущенной сессии."""
        self.position_mode = mode
        self.pinned_area = None
        self.apply_position(force=True)

    def pinned_coords(self, area):
        left, top, right, _bottom = area
        margin = px(PINNED_MARGIN)
        if self.position_mode == "top_left":
            x = left + margin
        elif self.position_mode == "top_center":
            x = left + (right - left - self.width) // 2
        else:                                   # top_right
            x = right - self.width - margin
        # По вертикали -- вплотную к верхней границе рабочей области.
        return x, top

    def apply_position(self, force=False):
        """Пересчёт позиции закреплённого оверлея.

        Вызывается на старте сессии, при смене режима и когда курсор ушёл
        с монитора, на котором оверлей закреплён. НЕ вызывается на каждое
        событие движения: geometry() -- самая дорогая часть обработки
        события, и в закреплённом режиме она обязана исчезнуть.

        Проверка "курсор всё ещё на том же мониторе" -- чистая арифметика по
        закэшированному прямоугольнику, без обращений к Win32.
        """
        if self.follow_cursor:
            return
        if not force and self.pinned_area is not None:
            left, top, right, bottom = self.pinned_area
            if left <= self.last_x < right and top <= self.last_y < bottom:
                return
        self.pinned_area = work_area_at(self.last_x, self.last_y)
        try:
            self.move_to(*self.pinned_coords(self.pinned_area))
        except tk.TclError:
            pass

    def update_skin(self, skin_config):
        self.config_data = skin_config
        self.configure(bg=self.config_data["bg"])
        if 'pos' in self.labels: self.labels['pos'].config(fg=self.config_data["pos_fg"], bg=self.config_data["bg"])
        if 'accel' in self.labels: self.labels['accel'].config(fg=self.config_data["accel_fg"], bg=self.config_data["bg"])
        if 'hz' in self.labels: self.labels['hz'].config(fg=self.config_data["hz_fg"], bg=self.config_data["bg"])
        if 'cps' in self.labels: self.labels['cps'].config(fg=self.config_data["cps_fg"], bg=self.config_data["bg"])
        if 'faults' in self.labels: self.labels['faults'].config(bg=self.config_data["bg"])

    def set_click_through(self, enabled):
        """Режим "сквозь окно" снимается так же, как ставится.

        Прежде стиль только выставлялся и только при создании окна, поэтому
        переключение флажка при запущенной сессии не делало ничего.
        WS_EX_LAYERED не снимаем: на нём держится прозрачность.
        """
        try:
            hwnd = win32gui.GetParent(self.winfo_id())
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if enabled:
                style |= win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
            else:
                style &= ~win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
        except (pywintypes.error, tk.TclError):
            logging.exception("не удалось изменить режим click-through")

    def set_alpha(self, alpha):
        """Прозрачность на лету."""
        try:
            self.attributes("-alpha", alpha)
        except tk.TclError:
            pass

    def update_data(self, x, y, now):
        dt = now - self.last_time
        
        # Используем переданный timestamp события (perf_counter)
        if self.event_times:
            self.intervals.append((now, now - self.event_times[-1]))
        self.event_times.append(now)
        
        # Очистка старых меток выполняется в отдельном цикле для плавности
        self.hz = len([t for t in self.event_times if now - t < 1.0])
        self.update_cps_value(now)

        # Ограничиваем частоту обновления расчетов ускорения (не чаще 200Гц)
        if dt > 0.005:
            dx, dy = x - self.last_x, y - self.last_y
            dist = math.sqrt(dx**2 + dy**2)
            
            # Текущая скорость (пиксели в секунду)
            vel = dist / dt
            
            # Изменение скорости курсора. Величина остаётся ИНДИКАТОРОМ,
            # а не измерением: дистанция считается в экранных пикселях уже
            # после баллистики указателя, поэтому физического смысла у неё нет.
            new_accel = (vel - self.last_velocity) / dt

            # Сглаживание с постоянной времени, а не с фиксированным весом:
            # окно теперь одинаковое независимо от частоты прихода событий.
            alpha = 1.0 - math.exp(-dt / ACCEL_TAU)
            self.current_accel += alpha * (new_accel - self.current_accel)
            self.record_dv(dv_index(self.current_accel))
            
            try:
                t = self.tr()
                if 'pos' in self.labels: self.labels['pos'].config(text=t["ov_pos"].format(int(x), int(y)))
                # Знак сохраняется: разгон и торможение обязаны различаться.
                if 'accel' in self.labels: self.labels['accel'].config(text=t["ov_accel"].format(dv_index(self.current_accel)))
                if 'hz' in self.labels: self.labels['hz'].config(text=t["ov_hz"].format(self.hz))
                if 'cps' in self.labels: self.labels['cps'].config(text=t["ov_cps"].format(self.cps))
                if 'faults' in self.labels:
                    self.labels['faults'].config(text=t["ov_faults"].format(self.fault_counts['left'], self.fault_counts['right']))


                # В закреплённом режиме окно не двигается вовсе.
                if self.follow_cursor:
                    self.move_to(int(x) + self.offset, int(y) + self.offset)
            except tk.TclError:
                # Окно оверлея уничтожено между постановкой события в очередь
                # и его разбором -- единственный ожидаемый здесь отказ.
                pass
            
            self.last_x, self.last_y = x, y
            self.last_time, self.last_velocity = now, vel

    def add_click(self, button_name, now, pressed, x=0, y=0):
        """Обрабатывает нажатие либо отпускание. Возвращает метку признака.

        Два признака считаются РАЗДЕЛЬНО, чтобы по логу было видно, какой
        сработал, и чтобы пороги потом было на чём калибровать:

        DC_FAULT_GAP  -- отпускание -> нажатие быстрее DC_FAULT_GAP. Дребезг
            контакта выглядит именно так: контакт разомкнулся и тут же
            замкнулся снова. Прежняя логика мерила интервал НАЖАТИЕ ->
            НАЖАТИЕ и потому записывала в неисправности обычную быструю серию.
        DC_FAULT_SHORT -- само нажатие короче DC_SHORT_PRESS. Дребезговое
            "нажатие" длится единицы миллисекунд, осознанное -- десятки.
        DC_SUSPECT -- промежуток между DC_FAULT_GAP и DC_SUSPECT_GAP.
            Считается отдельным счётчиком и неисправностью не объявляется.

        СЧЁТЧИК растёт на единицу за ЭПИЗОД, а не за признак. Канонический
        отскок (отпустил -> 3 мс -> замкнул на 4 мс -> отпустил) поднимает оба
        признака, но это одно и то же размыкание контакта, увиденное с двух
        сторон: сначала по паузе перед нажатием, потом по длительности самого
        нажатия. Прежде такой эпизод давал +2, и показание вдвое превышало
        число физических отскоков. Информация при этом не теряется -- в
        колонке Flag стоят оба признака через DC_FLAG_SEP.

        now -- метка времени СОБЫТИЯ (perf_counter в момент хука), а не
        момента разбора очереди.
        """
        btn_key = ("left" if "Button.left" in str(button_name)
                   else "right" if "Button.right" in str(button_name)
                   else None)

        if btn_key is None:
            if pressed:
                self.click_times.append(now)
                self.update_cps_value(now)
            return ""

        if not pressed:
            duration = now - self.last_press_times[btn_key]
            self.last_release_times[btn_key] = now
            # Признак, поднятый на нажатии этого же эпизода. Забираем и
            # сбрасываем: эпизод закончился здесь.
            press_flag = self.press_flags[btn_key]
            self.press_flags[btn_key] = ""
            if 0.0 <= duration < DC_SHORT_PRESS:
                # Если эпизод уже объявлен неисправностью на нажатии, второй
                # раз его не считаем -- но признак в Flag дописываем.
                if press_flag != "DC_FAULT_GAP":
                    self.fault_counts[btn_key] += 1
                if press_flag:
                    return press_flag + DC_FLAG_SEP + "DC_FAULT_SHORT"
                return "DC_FAULT_SHORT"
            return ""

        gap = now - self.last_release_times[btn_key]
        # Пара с предыдущим нажатием ТОЙ ЖЕ кнопки -- кандидат в двойной клик.
        # Намерение из потока ввода не наблюдаемо, поэтому пара только
        # сопоставляется с системными правилами, а не объявляется двойным.
        previous_at = self.last_press_times[btn_key]
        previous_pos = self.last_press_pos[btn_key]
        if (previous_pos is not None and previous_at > -1e8
                and len(self.dblclk_pairs) < DBLCLK_PAIR_CAP):
            self.dblclk_pairs.append((now - previous_at,
                                      abs(x - previous_pos[0]),
                                      abs(y - previous_pos[1])))
        self.last_press_pos[btn_key] = (x, y)
        self.last_press_times[btn_key] = now
        self.click_times.append(now)
        self.update_cps_value(now)

        if gap < DC_FAULT_GAP:
            self.fault_counts[btn_key] += 1
            self.press_flags[btn_key] = "DC_FAULT_GAP"
        elif gap < DC_SUSPECT_GAP:
            self.suspect_counts[btn_key] += 1
            self.press_flags[btn_key] = "DC_SUSPECT"
        else:
            self.press_flags[btn_key] = ""
        return self.press_flags[btn_key]

    def record_dv(self, value):
        """Копит |dV| для распределения за сессию, с ограниченной памятью.

        При переполнении выборка прореживается ВДВОЕ, а не обрезается: так
        сохраняется покрытие всей сессии. Обрезание по началу описывало бы
        только первые секунды и молча врало бы про длинный прогон.
        """
        self.dv_seen += 1
        if self.dv_seen % self.dv_step:
            return
        self.dv_samples.append(abs(int(value)))
        if len(self.dv_samples) >= DV_SAMPLE_CAP:
            del self.dv_samples[1::2]
            self.dv_step *= 2

    def add_scroll(self, dx, dy, now):
        """Обрабатывает тик колеса. Возвращает метку признака для CSV.

        dy == 0 при dx == 0 -- НЕ ошибка и не событие: pynput делит сырое
        смещение на WHEEL_DELTA целочисленно, и колесо высокого разрешения
        даёт нули. Направления у такого тика нет, детектировать по нему
        нечего -- он только считается, а решение о годности счёта принимает
        wheel_health() по их доле.

        Горизонтальный тик (dy == 0, dx != 0) -- законное событие наклонного
        колеса, а не потерянное направление: вертикальную историю он не трогает.
        """
        self.wheel_ticks += 1
        if dy == 0:
            if dx == 0:
                self.wheel_zeros += 1
            return ""

        direction = 1 if dy > 0 else -1
        gap = now - self.last_wheel_time
        previous = self.last_wheel_dir
        self.last_wheel_dir = direction
        self.last_wheel_time = now
        if previous and direction != previous and gap < WHEEL_REVERSAL_GAP:
            self.wheel_reversals += 1
            return "WHEEL_REVERSAL"
        return ""

    def update_cps_value(self, now):
        self.click_times = [t for t in self.click_times if now - t < 1.0]
        self.cps = len(self.click_times)
        if 'cps' in self.labels:
            try:
                self.labels['cps'].config(text=self.tr()["ov_cps"].format(self.cps))
            except tk.TclError:
                pass    # виджет уже уничтожен

# --- Графики в реальном времени ----------------------------------------------
# Числа ниже ЗАМЕРЕНЫ до написания кода, а не выбраны на глаз.
#
# Цена кадра (два холста, 300 отсчётов, установившийся режим: линия через
# coords(), подписи не трогаются) -- 0.763 мс медиана / 1.318 p95 на
# минимальной ширине графика и 1.299 / 2.395 на развёрнутом окне.
#
# Тик существующего цикла при ~600 событиях/с стоит 5.582 мс медиана и
# 8.967 мс p95: бюджет 10 мс занят на 56% по медиане и на 90% по p95 ЕЩЁ ДО
# графиков. Рисовать каждый тик нельзя -- получилось бы 6.881 мс по медиане
# и 11.36 мс по p95, то есть период 10 мс перестал бы выдерживаться ровно
# там, где движение быстрое и очередь наполняется быстрее всего.
#
# Поэтому у графиков СВОЙ шаг -- 50 мс. Средняя добавка к тику 1.299/5 =
# 0.260 мс, это 2.6% бюджета.
#
# Почему 50, а не 100: ACCEL_TAU = 0.06 с. Шаг выборки длиннее постоянной
# сглаживания даёт алиасинг -- график терял бы переходы, которые в тот же
# момент видно в подписи оверлея. 50 мс держит шаг НИЖЕ tau. Экономия от
# перехода на 100 мс -- 0.13 мс на тик, платить за неё искажением показания
# незачем.
#
# Почему не 25: выигрыша нет. Частота -- счёт за скользящую секунду, dV
# сглажен с tau = 60 мс; выше 20 Гц в обоих сигналах ничего не лежит.
GRAPH_SAMPLE_MS = 50
GRAPH_WINDOW_S = 15
GRAPH_SLOTS = GRAPH_WINDOW_S * 1000 // GRAPH_SAMPLE_MS   # 300 отсчётов

# Порог показа по СВОБОДНОЙ ширине справа от колонки -- тоже замер, а не
# круглое число. При масштабе 150% самая широкая подпись графика -- русский
# заголовок "dV, относительный индекс (без единиц)", 357 физ.; вместе с
# жёлобом оси Y (47 физ. под "+1200" плюс засечка и зазор) и полями выходит
# 423 физ., то есть 282 логических. Взято 300 логических -- запас 6.4%.
#
# Ниже порога графиков нет СОВСЕМ и площадь под них не резервируется:
# зарезервированная пустота на узком окне -- это отнятое у панели место
# в обмен на ничто.
GRAPH_MIN_WIDTH = 300
GRAPH_GAP = 10               # логических, зазор между двумя графиками
GRAPH_Y_TICKS = 5
GRAPH_X_TICKS = 4
GRAPH_MIN_CEILING = 10       # шкала не схлопывается в ноль на пустых данных


def graph_ceiling(peak):
    """Округляет размах вверх до 1/2/5 * 10^n.

    Шкала обязана быть круглой: подпись "до 837" читается как измерение,
    а это граница шкалы, и никакого измерения за ней нет.
    """
    if peak <= 0:
        return GRAPH_MIN_CEILING
    exponent = 10 ** int(math.floor(math.log10(peak)))
    for factor in (1, 2, 5):
        if peak <= factor * exponent:
            return max(int(factor * exponent), GRAPH_MIN_CEILING)
    return max(int(10 * exponent), GRAPH_MIN_CEILING)


class RingSeries:
    """Кольцевой буфер фиксированной длины под скользящее окно графика.

    Память НЕ растёт с длительностью сессии: список создаётся один раз на
    size элементов и дальше только перезаписывается.

    None -- законное значение и означает "показания в этот момент не было".
    График на таком месте РВЁТ линию. Соединить соседей через пропуск значило
    бы нарисовать показание, которого не измеряли.
    """

    def __init__(self, size):
        self.size = size
        self.data = [None] * size
        self.pos = 0
        self.filled = 0

    def push(self, value):
        self.data[self.pos] = value
        self.pos = (self.pos + 1) % self.size
        if self.filled < self.size:
            self.filled += 1

    def values(self):
        """Отсчёты от старого к новому; длина -- сколько накоплено."""
        if self.filled < self.size:
            return self.data[:self.filled]
        return self.data[self.pos:] + self.data[:self.pos]


class LiveGraph:
    """Один график на tkinter Canvas: ось, подписи, линия.

    Ничего не измеряет и ничего не считает сам: получает готовые значения и
    только раскладывает их по пикселям. Любой собственный расчёт здесь был бы
    ВТОРЫМ источником показания и со временем разошёлся бы с тем, что написано
    в строке панели.

    Элементы холста создаются один раз и потом только двигаются: пересоздание
    каждый кадр замерено дороже (0.921 мс против 0.520 у coords()).
    """

    def __init__(self, parent, symmetric=False, color="#1f6fb2"):
        self.symmetric = symmetric
        self.color = color
        self.canvas = tk.Canvas(parent, width=1, height=1, bg="#ffffff",
                                highlightthickness=1,
                                highlightbackground="#d0d0d0")
        self.title_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.tick_font = tkfont.Font(family="Segoe UI", size=8)
        self.sec_suffix = "s"
        self.item_title = self.canvas.create_text(
            0, 0, anchor="nw", text="", font=self.title_font, fill="#333333")
        self.item_axis_y = self.canvas.create_line(0, 0, 0, 0, fill="#a0a0a0")
        self.item_axis_x = self.canvas.create_line(0, 0, 0, 0, fill="#a0a0a0")
        self.item_empty = self.canvas.create_text(
            0, 0, anchor="center", text="", fill="#909090",
            font=self.tick_font, state="hidden")
        self.grid_lines = [self.canvas.create_line(0, 0, 0, 0, fill="#ededed")
                           for _ in range(GRAPH_Y_TICKS)]
        self.y_labels = [self.canvas.create_text(
            0, 0, anchor="e", text="", font=self.tick_font, fill="#606060")
            for _ in range(GRAPH_Y_TICKS)]
        self.x_labels = [self.canvas.create_text(
            0, 0, anchor="n", text="", font=self.tick_font, fill="#606060")
            for _ in range(GRAPH_X_TICKS)]
        # Линия рисуется отрезками: один отрезок на непрерывный участок
        # данных. Пул растёт по мере надобности и больше не сокращается --
        # лишние элементы просто прячутся.
        self.runs = []
        self.layout_key = None
        # Последняя раскладка поля построения: (left, right, top, bottom,
        # ceiling). Нужна проверкам, чтобы перевести НАРИСОВАННЫЙ пиксель
        # обратно в значение и сверить его со строкой панели. Считать это
        # в стенде заново значило бы завести второй источник уже в проверке.
        self.plot_box = None

    def set_text(self, title, empty_text, sec_suffix):
        """Локализованные подписи. Меняются только при смене языка."""
        self.sec_suffix = sec_suffix
        self.canvas.itemconfigure(self.item_title, text=title)
        self.canvas.itemconfigure(self.item_empty, text=empty_text)
        self.layout_key = None          # заставить пересчитать раскладку

    def y_tick_labels(self, ceiling):
        """Подписи оси Y ТОЧНО по положению линий сетки.

        Округлять нельзя: потолок 10 на четырёх интервалах даёт линию на 7.5,
        и подпись "8" рядом с ней смещает оценку читателя. Поэтому %g --
        дробное значение показывается дробным.
        """
        middle = (GRAPH_Y_TICKS - 1) // 2
        step = float(GRAPH_Y_TICKS - 1)
        if self.symmetric:
            out = []
            for k in range(GRAPH_Y_TICKS):
                if k == middle:
                    out.append("0")
                else:
                    out.append("%+g" % (ceiling - 2.0 * ceiling * k / step))
            return out
        return ["%g" % (ceiling - ceiling * k / step)
                for k in range(GRAPH_Y_TICKS)]

    def x_tick_labels(self):
        out = []
        for k in range(GRAPH_X_TICKS):
            if k == GRAPH_X_TICKS - 1:
                out.append("0")
            else:
                seconds = GRAPH_WINDOW_S - GRAPH_WINDOW_S * k // (GRAPH_X_TICKS - 1)
                out.append("-%d%s" % (seconds, self.sec_suffix))
        return out

    def render(self, values):
        """Перерисовка кадра. values -- от старого к новому, None = пропуск."""
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 2 or height < 2:
            return                      # холст ещё не разложен
        real = [v for v in values if v is not None]
        ceiling = graph_ceiling(max([abs(v) for v in real] or [0]))
        labels = self.y_tick_labels(ceiling)
        left = max(self.tick_font.measure(s) for s in labels) + px(7)
        right = width - px(6)
        top = self.title_font.metrics("linespace") + px(4)
        bottom = height - self.tick_font.metrics("linespace") - px(3)
        if right - left < 2 or bottom - top < 2:
            return                      # места нет даже под оси

        self.plot_box = (left, right, top, bottom, ceiling)
        key = (width, height, ceiling)
        if key != self.layout_key:
            self.layout_key = key
            self.place_axes(left, right, top, bottom, labels)

        self.canvas.itemconfigure(self.item_empty,
                                  state="normal" if not real else "hidden")
        if not real:
            self.canvas.coords(self.item_empty, (left + right) // 2,
                               (top + bottom) // 2)
        self.draw_runs(self.build_runs(values, left, right, top, bottom,
                                       ceiling))

    def place_axes(self, left, right, top, bottom, labels):
        """Оси, сетка и подписи. Зовётся только когда раскладка изменилась."""
        self.canvas.coords(self.item_title, left, px(2))
        self.canvas.coords(self.item_axis_y, left, top, left, bottom)
        self.canvas.coords(self.item_axis_x, left, bottom, right, bottom)
        for k, text in enumerate(labels):
            y = top + (bottom - top) * k / float(GRAPH_Y_TICKS - 1)
            self.canvas.coords(self.y_labels[k], left - px(4), y)
            self.canvas.itemconfigure(self.y_labels[k], text=text)
            self.canvas.coords(self.grid_lines[k], left, y, right, y)
        for k, text in enumerate(self.x_tick_labels()):
            x = left + (right - left) * k / float(GRAPH_X_TICKS - 1)
            self.canvas.coords(self.x_labels[k], x, bottom + px(2))
            self.canvas.itemconfigure(self.x_labels[k], text=text)

    def build_runs(self, values, left, right, top, bottom, ceiling):
        """Разбивает данные на непрерывные участки.

        Пропуск (None) закрывает участок. Именно здесь выполняется требование
        "пустой участок честнее интерполяции": через дырку линия не идёт.
        """
        count = len(values)
        if not count:
            return []
        span = float(GRAPH_SLOTS - 1)
        plot_w = right - left
        plot_h = bottom - top
        runs = []
        current = []
        for index, value in enumerate(values):
            if value is None:
                if current:
                    runs.append(current)
                    current = []
                continue
            x = right - plot_w * (count - 1 - index) / span
            if self.symmetric:
                y = top + plot_h * (0.5 - 0.5 * value / float(ceiling))
            else:
                y = bottom - plot_h * value / float(ceiling)
            current.append((x, min(max(y, top), bottom)))
        if current:
            runs.append(current)
        return runs

    def draw_runs(self, runs):
        while len(self.runs) < len(runs):
            self.runs.append(self.canvas.create_line(0, 0, 0, 0,
                                                     fill=self.color))
        for item, points in zip(self.runs, runs):
            if len(points) == 1:
                # Одиночный отсчёт -- всё равно показание. Рисуется засечкой
                # в один пиксель, а не пропадает.
                x, y = points[0]
                self.canvas.coords(item, x, y, x + 1, y)
            else:
                flat = []
                for x, y in points:
                    flat.append(x)
                    flat.append(y)
                self.canvas.coords(item, *flat)
            self.canvas.itemconfigure(item, state="normal")
        for item in self.runs[len(runs):]:
            self.canvas.itemconfigure(item, state="hidden")


class MainControlPanel:
    def __init__(self, root):
        self.root = root
        # Заголовок ставится и здесь, и в конце setup_ui: при смене языка
        # интерфейс пересобирается, и заголовок обязан пересобраться с ним.
        self.root.title(window_title("English"))
        
        self.tracker = None
        self.current_hz = 0
        self.logger = SessionLogger()
        self.heatmap = HeatmapManager()
        # Очередь событий с потолком: см. EVENT_QUEUE_MAXSIZE.
        self.data_queue = queue.Queue(maxsize=EVENT_QUEUE_MAXSIZE)
        # Очередь команд из фоновых потоков в главный. Поток pystray не имеет
        # права трогать Tk напрямую, поэтому кладёт сюда callable.
        self.command_queue = queue.Queue()
        self.dropped_events = 0
        # Отброшенные синтетические события. В UI не выводится: это не потеря
        # данных, а осознанная фильтрация; нужно для диагностики и проверок.
        self.injected_events = 0
        # Агрегаты сессии -- для сводки. Обнуляются на каждом СТАРТЕ.
        self.session_started = None      # datetime начала, None вне сессии
        self.session_perf0 = 0.0
        self.peak_hz = 0
        self.peak_cps = 0
        self.total_events = 0
        self.total_moves = 0             # событий движения курсора
        self.total_clicks = 0            # нажатий (без отпусканий)
        self.active_seconds = set()      # номера секунд, в которые были события
        self.session_csv = None
        self.session_png = None
        # Последняя оценка периода репортов и лучшая за сессию. Лучшей
        # считается годная с наибольшим числом интервалов: в сводке нужна не
        # та, что пришлась на момент остановки, а самая обеспеченная данными.
        self.rate_estimate = None
        self.best_rate = None
        self.rate_checked_at = 0.0
        self.listener = None
        self.shutting_down = False
        # Иконка публикуется только полностью собранной; главный поток ждёт
        # этого события, а не проверяет self.icon на None.
        self.icon_ready = threading.Event()
        # Значение, отрисованное на иконке в трее. Иконка создаётся с нулём.
        self.tray_icon_value = 0
        # Подсказка трея. Показание периода репортов живёт здесь: в окне для
        # него места нет (замерено -- строке нужно 28 физ. при запасе 17), а
        # подсказка не стоит ни пикселя. Основной вывод -- в сводке сессии.
        self.tray_title = tray_tip("English")
        # Зеркало текущего языка обычной строкой: lang_var -- Tk-переменная,
        # и читать её из потока трея нельзя.
        self.current_lang = "English"
        self.icon = None
                
        # Переменные настроек
        self.lang_var = tk.StringVar(value="English")
        self.show_pos = tk.BooleanVar(value=True)
        self.show_accel = tk.BooleanVar(value=True)
        self.show_hz = tk.BooleanVar(value=True)
        self.show_cps = tk.BooleanVar(value=True)
        self.show_faults = tk.BooleanVar(value=True)
        self.enable_logging = tk.BooleanVar(value=False)
        self.enable_heatmap = tk.BooleanVar(value=False)
        self.overlay_alpha = tk.DoubleVar(value=0.8)
        self.click_through = tk.BooleanVar(value=False)
        self.skin_var = tk.StringVar(value="Dark (Default)")
        # Режим положения хранится внутренним ключом; в OptionMenu лежит
        # локализованная подпись, поэтому переменная и ключ раздельны.
        self.position_mode = "cursor"
        self.position_var = tk.StringVar()

        # Геометрия окна задаётся один раз, при первой сборке интерфейса;
        # дальше пользователь волен менять размер, а minsize не даёт обрезать
        # содержимое.
        self.window_sized = False

        # Кольцевые буферы графиков. Живут независимо от того, показаны
        # графики или нет: иначе при растягивании окна историю пришлось бы
        # начинать с нуля. Память фиксированная -- см. RingSeries.
        self.hz_series = RingSeries(GRAPH_SLOTS)
        self.dv_series = RingSeries(GRAPH_SLOTS)
        self.graph_sampled_at = 0.0
        self.graphs_visible = False

        # Интерфейс: колонка фиксированной ширины, прижатая к ЛЕВОМУ краю.
        # Колонка живёт в столбце 0 и держит свою ширину (weight=0), всё
        # лишнее место забирает пустой столбец 1 (weight=1) справа от неё.
        # Поле между колонкой и краем окна задаётся ЯВНО через padx/pady:
        # раньше его давал остаток места в боковых столбцах, а при
        # выравнивании влево слева никакого остатка нет и колонка легла бы
        # вплотную к рамке.
        root.grid_columnconfigure(0, weight=0)
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(0, weight=1)
        self.frame = ttk.Frame(root, padding=px(PANEL_PAD))
        self.frame.grid(row=0, column=0, sticky="n",
                        padx=px(PANEL_MARGIN), pady=px(PANEL_MARGIN))

        # Графики занимают освободившийся справа столбец. Холсты просят 1x1 и
        # растягиваются сеткой: попроси они настоящий размер, сетка потянула
        # бы за собой окно, и minsize перестал бы означать минимум.
        # В сетку столбец попадает только когда места хватает -- см.
        # update_graph_visibility().
        self.graph_frame = ttk.Frame(root)
        self.hz_graph = LiveGraph(self.graph_frame)
        self.dv_graph = LiveGraph(self.graph_frame, symmetric=True,
                                  color="#b2541f")
        self.hz_graph.canvas.pack(fill="both", expand=True,
                                  pady=(0, px(GRAPH_GAP)))
        self.dv_graph.canvas.pack(fill="both", expand=True)
        root.bind("<Configure>", self.on_root_configure)
        
        # Данные о железе читаются ОДИН раз. WMI-запрос занимает ~150 мс и
        # раньше выполнялся внутри setup_ui, то есть на каждой смене языка,
        # подвешивая интерфейс и накапливая события в очереди.
        self.hw_info = MouseHardware.get_mouse_info()
        self.sys_speed = MouseHardware.get_pointer_speed()
        self.pointer_precision = MouseHardware.get_pointer_precision()

        self.setup_ui()

        # Закрытие крестиком обязано пройти тот же путь, что и выход из трея:
        # раньше обработчика не было вовсе и теплокарта терялась целиком.
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        # Трей. Хук мыши НЕ ставится при запуске: он живёт ровно столько,
        # сколько идёт сессия мониторинга.
        threading.Thread(target=self.setup_tray, daemon=True,
                         name="tray").start()

        # Циклы обновления
        self.update_tray_loop()
        self.process_queue_loop()

    def setup_ui(self):
        # Зеркало языка обновляется здесь, в главном потоке.
        self.current_lang = self.lang_var.get()
        t = TRANSLATIONS[self.current_lang]
        # Заголовок окна пересобирается вместе с интерфейсом: иначе после
        # смены языка он остался бы на прежнем -- ровно тот обрыв цепочки,
        # из-за которого замирали строки панели.
        try:
            self.root.title(window_title(self.current_lang))
        except tk.TclError:
            pass

        # Обновляем меню трея если оно уже создано. Присвоения .menu мало:
        # без update_menu() pystray не перестраивает уже показанное меню.
        if self.icon is not None:
            self.icon.menu = self.build_tray_menu()
            try:
                self.icon.update_menu()
            except Exception:
                logging.exception("не удалось обновить меню трея")

        # Очистка фрейма при смене языка
        for widget in self.frame.winfo_children():
            widget.destroy()
        self.slot_shows = None

        # Распорка задаёт ширину колонки. Без неё ширину определял бы самый
        # широкий потомок, а он у Tk бывает неожиданным: tk.Text по умолчанию
        # просит 80 знаков.
        inner = px(PANEL_WIDTH) - 2 * px(PANEL_PAD)
        ttk.Frame(self.frame, width=inner, height=1).pack()

        # ttk.OptionMenu центрирует свою подпись -- это был последний элемент,
        # выпадавший из общего выравнивания. Собственный стиль прижимает её
        # влево, как и всё остальное в колонке.
        left_menubutton_style()

        # ЕДИНОЕ выравнивание: всё по левому краю колонки, включая заголовки
        # секций. Центрирование части элементов и было причиной того, что на
        # растянутом окне интерфейс разъезжался; левый край -- единственный,
        # который не зависит от ширины.
        def head(text):
            ttk.Label(self.frame, text=text, font=("Segoe UI", 10, "bold"),
                      anchor="w").pack(fill="x", pady=(px(12), px(4)))

        def line(text, font=("Segoe UI", 10)):
            label = ttk.Label(self.frame, text=text, font=font, anchor="w")
            label.pack(fill="x")
            return label

        head(t["lang_choice"])
        self.lang_menu = ttk.OptionMenu(self.frame, self.lang_var,
                                        self.lang_var.get(),
                                        *TRANSLATIONS.keys(),
                                        command=lambda _: self.setup_ui(),
                                        style="Left.TMenubutton")
        self.lang_menu.pack(fill="x")

        head(t["hw_info_title"])
        # width=1: Text просит один знак и растягивается по колонке. С
        # умолчанием в 80 знаков он раздувал бы колонку до своей ширины.
        self.info_text = tk.Text(self.frame, width=1, height=6,
                                 font=("Consolas", 9), bg="#f0f0f0")
        self.update_info_display()
        self.info_text.pack(fill="x")

        head(t["display_settings"])
        for key, variable in (("show_pos", self.show_pos),
                              ("show_accel", self.show_accel),
                              ("show_hz", self.show_hz),
                              ("show_cps", self.show_cps),
                              ("show_faults", self.show_faults),
                              ("enable_logging", self.enable_logging),
                              ("enable_heatmap", self.enable_heatmap)):
            ttk.Checkbutton(self.frame, text=t[key],
                            variable=variable).pack(fill="x")

        head(t["overlay_style"])
        ttk.Checkbutton(self.frame, text=t["click_through"],
                        variable=self.click_through,
                        command=self.on_click_through_change).pack(fill="x")
        line(t["transparency"])
        self.alpha_scale = ttk.Scale(self.frame, from_=0.1, to=1.0,
                                     variable=self.overlay_alpha,
                                     orient="horizontal",
                                     command=self.on_alpha_change)
        self.alpha_scale.pack(fill="x")

        head(t["skin_choice"])
        self.skin_menu = ttk.OptionMenu(self.frame, self.skin_var,
                                        self.skin_var.get(), *SKINS.keys(),
                                        command=self.on_skin_change,
                                        style="Left.TMenubutton")
        self.skin_menu.pack(fill="x")

        head(t["pos_choice"])
        position_labels = {mode: t["pos_" + mode] for mode in POSITION_MODES}
        self.position_var.set(position_labels[self.position_mode])
        self.position_menu = ttk.OptionMenu(
            self.frame, self.position_var, position_labels[self.position_mode],
            *[position_labels[mode] for mode in POSITION_MODES],
            command=lambda chosen: self.on_position_change(chosen, position_labels),
            style="Left.TMenubutton")
        self.position_menu.pack(fill="x")

        btn_text = t["btn_stop"] if self.tracker else t["btn_start"]
        self.btn_toggle = ttk.Button(self.frame, text=btn_text,
                                     command=self.toggle_tracker)
        # fill="x" по КОЛОНКЕ, а не по окну: кнопка больше не растягивается
        # на всю ширину экрана.
        self.btn_toggle.pack(fill="x", pady=(px(16), px(12)))

        # Блок статуса -- часть той же колонки, а не отдельный хвост внизу.
        self.hz_label = line(self.hz_line())
        # Потолок высоты снят вместе со старой вёрсткой, поэтому показание
        # периода и состояние колеса снова живут в панели постоянно.
        self.rate_label = line(self.rate_line())
        self.wheel_label = line(self.wheel_line())
        self.faults_label = line(t["faults_label"].format(0, 0))
        self.suspect_label = line(t["suspect_label"].format(0, 0))
        # Счётчик потерь остаётся условным: "Потеряно событий: 0" -- шум, а не
        # сведения. Место тут больше ни при чём.
        self.dropped_label = ttk.Label(
            self.frame, text=t["dropped_label"].format(self.dropped_events),
            font=("Segoe UI", 10), anchor="w")

        # Пороги обязаны быть видны пользователю как эвристика, а не
        # молчаливое число внутри программы.
        self.dc_note = ttk.Label(
            self.frame, text=t["dc_note"].format(int(DC_FAULT_GAP * 1000),
                                                 int(DC_SHORT_PRESS * 1000),
                                                 int(DC_SUSPECT_GAP * 1000)),
            font=("Segoe UI", 8, "italic"), foreground="#7f8c8d",
            wraplength=inner, justify="left", anchor="w")
        self.dc_note.pack(fill="x", pady=(px(8), 0))

        self.log_status = ttk.Label(self.frame, text="",
                                    font=("Segoe UI", 9, "italic"), anchor="w")
        self.log_status.pack(fill="x", pady=(px(6), 0))

        # Подсказка про графики. Без неё функции для стороннего пользователя
        # не существует: окно по умолчанию открывается минимальным, а при
        # минимальном графиков нет.
        #
        # Текстов ДВА, и оба верны в своём состоянии. Гасить подсказку в пусто
        # нельзя: пустая метка на строку ниже подсказки, minsize к моменту
        # переключения уже посчитан, и на узком окне содержимое переставало
        # помещаться -- 1310 требуемых при minsize 1289. Стенд фазы 12 это
        # поймал. Равенство высот у обоих текстов проверяется машинно.
        self.graph_hint = ttk.Label(
            self.frame, text=self.graph_hint_text(),
            font=("Segoe UI", 8, "italic"), foreground="#7f8c8d",
            wraplength=inner, justify="left", anchor="w")
        self.graph_hint.pack(fill="x", pady=(px(6), 0))

        # Подписи графиков локализованы и пересобираются вместе с панелью.
        self.hz_graph.set_text(t["graph_hz_title"], t["graph_no_data"],
                               t["graph_sec"])
        self.dv_graph.set_text(t["graph_dv_title"], t["graph_no_data"],
                               t["graph_sec"])

        self.fit_window()

    def live_hz(self):
        """Частота событий курсора. ЕДИНСТВЕННЫЙ источник этого показания.

        None означает "показания нет": хук не стоит, сессии нет, и мерить
        нечего. Ноль -- это измеренный ноль, и путать его с отсутствием
        измерения нельзя: строка покажет ноль (так было всегда), а график
        на месте None РАЗОРВЁТ линию, потому что рисовать нечего.
        """
        if self.tracker is None:
            return None
        return self.tracker.hz

    def live_dv(self):
        """Показание dV. ЕДИНСТВЕННЫЙ источник и для оверлея, и для графика.

        Величина относительная: экранные пиксели уже после баллистики
        указателя, без единиц и без нормы. Ни шкалы "хорошо/плохо", ни
        цветовой индикации у неё быть не может.
        """
        if self.tracker is None:
            return None
        return dv_index(self.tracker.current_accel)

    def hz_line(self):
        """Текст строки частоты. Единственное место, где он собирается."""
        value = self.live_hz()
        return self.tr()["hz_label"].format(0 if value is None else value)

    def graph_hint_text(self):
        """Текст подсказки под текущее состояние. Единственное место сборки."""
        t = self.tr()
        return t["graph_hint_on"] if self.graphs_visible else t["graph_hint_off"]

    def on_root_configure(self, event=None):
        """Размер окна изменился.

        В Tk событие <Configure> потомка доходит до привязки на верхнем окне
        через тег bindtags, поэтому чужие события отсеиваются явно -- иначе
        обработчик срабатывал бы на каждый чих внутри панели.
        """
        if event is not None and event.widget is not self.root:
            return
        self.update_graph_visibility()

    def update_graph_visibility(self):
        """Решает, есть ли справа место под графики.

        Ниже порога графиков нет СОВСЕМ и площадь под них не резервируется:
        зарезервированная пустота на узком окне -- это отнятое у панели место
        в обмен на ничто. Порог GRAPH_MIN_WIDTH замерен, см. комментарий
        у константы.
        """
        try:
            free = (self.root.winfo_width() - self.frame.winfo_reqwidth()
                    - 3 * px(PANEL_MARGIN))
            show = free >= px(GRAPH_MIN_WIDTH)
            if show == self.graphs_visible:
                return
            self.graphs_visible = show
            if show:
                self.graph_frame.grid(row=0, column=1, sticky="nsew",
                                      padx=(0, px(PANEL_MARGIN)),
                                      pady=px(PANEL_MARGIN))
            else:
                self.graph_frame.grid_remove()
            hint = getattr(self, "graph_hint", None)
            if hint is not None:
                hint.config(text=self.graph_hint_text())
        except tk.TclError:
            pass

    def sample_graphs(self):
        """Отсчёт и перерисовка графиков. Зовётся из цикла 10 мс.

        Работа делается раз в GRAPH_SAMPLE_MS, а не каждый тик: цена кадра
        замерена и в бюджет тика не влезает, разбор -- у констант.

        Отсчёты берутся ВСЕГДА, даже когда графики скрыты: иначе после
        растягивания окна история начиналась бы с пустого места. Рисование
        при скрытых графиках пропускается -- рисовать некуда.
        """
        now = time.perf_counter()
        if now - self.graph_sampled_at < GRAPH_SAMPLE_MS / 1000.0:
            return
        self.graph_sampled_at = now
        self.hz_series.push(self.live_hz())
        self.dv_series.push(self.live_dv())
        if not self.graphs_visible:
            return
        try:
            self.hz_graph.render(self.hz_series.values())
            self.dv_graph.render(self.dv_series.values())
        except tk.TclError:
            pass        # окно уничтожено между тиками

    def fit_window(self):
        """Подгоняет окно под содержимое и запрещает сжимать его ниже.

        Минимальный размер берётся из ТРЕБУЕМОГО размера колонки, а не из
        зашитого числа: содержимое меняется от языка и от версии, и жёсткий
        потолок 850 был именно попыткой удержать вёрстку, у которой не было
        собственного размера. Теперь размер задаёт контент.

        PANEL_MARGIN прибавляется дважды, потому что столько же задано в
        padx/pady у самой колонки: поле есть с обеих сторон, и minsize обязан
        его вмещать, иначе окно можно было бы сжать ровно на величину поля и
        содержимое обрезалось бы.
        """
        try:
            self.root.update_idletasks()
            width = self.frame.winfo_reqwidth() + 2 * px(PANEL_MARGIN)
            height = self.frame.winfo_reqheight() + 2 * px(PANEL_MARGIN)
            self.root.minsize(width, height)
            if not self.window_sized:
                self.root.geometry("%dx%d" % (width, height))
                self.window_sized = True
        except tk.TclError:
            pass    # окно уже уничтожено

    def tr(self):
        """Словарь перевода. Читает обычную строку, а не Tk-переменную,
        поэтому вызывать можно из любого потока."""
        return TRANSLATIONS.get(self.current_lang, TRANSLATIONS["English"])

    def run_thread_commands(self):
        """Выполняет в главном потоке то, что запросили фоновые потоки.

        Tcl не потокобезопасен: обращение к Tk из потока pystray приводит либо
        к RuntimeError("main thread is not in main loop"), либо к порче
        состояния интерпретатора. Поэтому фоновые потоки не трогают Tk, а
        кладут сюда callable.
        """
        while True:
            try:
                command = self.command_queue.get_nowait()
            except queue.Empty:
                return
            try:
                command()
            except Exception:
                logging.exception("команда из фонового потока завершилась ошибкой")

    def on_skin_change(self, selected_skin):
        if self.tracker:
            skin_config = SKINS.get(selected_skin, SKINS["Dark (Default)"])
            self.tracker.update_skin(skin_config)

    def faults_line(self):
        """Текст строки неисправностей. Единственное место сборки.

        Без сессии -- нули, как и до старта: счёт ведётся по сессии, и итог
        законченной живёт в сводке, а не в панели живых показаний.
        """
        counts = (self.tracker.fault_counts if self.tracker
                  else {'left': 0, 'right': 0})
        return self.tr()["faults_label"].format(counts['left'],
                                                counts['right'])

    def suspect_line(self):
        """То же для подозрительных. Счётчики РАЗНЫЕ, метки разные."""
        counts = (self.tracker.suspect_counts if self.tracker
                  else {'left': 0, 'right': 0})
        return self.tr()["suspect_label"].format(counts['left'],
                                                 counts['right'])

    def update_fault_labels(self):
        """Неисправности и подозрительные -- РАЗНЫЕ счётчики и разные метки.

        Раньше здесь стоял выход `if self.tracker is None: return`, и после
        СТОП обе метки навсегда держали счётчики законченной сессии: панель
        одновременно показывала "событий 0/с", "прокрутки не было" и "ошибок
        L:6". Тот же обрыв цепочки, что у строки колеса в фазе 13 и у строки
        частоты в фазе 14 -- третий случай одного класса.
        """
        try:
            self.faults_label.config(text=self.faults_line())
            self.suspect_label.config(text=self.suspect_line())
        except tk.TclError:
            pass

    def on_alpha_change(self, _value=None):
        """Прозрачность применяется на лету, как смена скина."""
        if self.tracker is not None:
            self.tracker.set_alpha(self.overlay_alpha.get())

    def on_click_through_change(self):
        """Режим "сквозь окно" применяется на лету."""
        if self.tracker is not None:
            self.tracker.set_click_through(self.click_through.get())

    def on_position_change(self, chosen_label, position_labels):
        """Смена положения применяется на лету, как смена скина."""
        for mode, label in position_labels.items():
            if label == chosen_label:
                self.position_mode = mode
                break
        if self.tracker is not None:
            self.tracker.set_position_mode(self.position_mode)

    def process_queue_loop(self):
        """Периодический цикл главного потока."""
        if self.shutting_down:
            return
        self.run_thread_commands()
        # Командой из фонового потока мог оказаться shutdown() -- это путь
        # выхода из трея. Тогда root уже уничтожен, и всё, что ниже, работает
        # с мёртвым интерпретатором: сегодня безвредно, но проверка стоит
        # дешевле, чем помнить об этом при каждой следующей правке.
        if self.shutting_down:
            return
        self.process_events()
        self.update_live_labels()
        self.root.after(10, self.process_queue_loop)

    def process_events(self):
        """Разбор накопленных событий ввода.

        Вызывается и циклом каждые 10 мс, и отдельно при остановке сессии:
        события, уже лежащие в очереди, принадлежат сессии и обязаны попасть
        в лог и теплокарту до их закрытия.
        """
        t = self.tr()
        try:
            while True:
                item = self.data_queue.get_nowait()
                etype = item[0]
                self.total_events += 1
                if self.session_started is not None:
                    # "Активная секунда" -- секунда, в которую было хоть одно
                    # событие. Определение грубое, зато однозначное, и в сводке
                    # названо словами.
                    self.active_seconds.add(int(item[-1] - self.session_perf0))
                
                if etype == "move":
                    _, x, y, ts = item
                    self.total_moves += 1
                    # Обрабатываем логгер и теплокарту даже если трекера нет (но мониторинг запущен)
                    if self.logger.is_active:
                        # Тот же масштаб, что на оверлее: одна величина --
                        # одно число.
                        accel = dv_index(self.tracker.current_accel) if self.tracker else 0
                        self.logger.log("Move", "", x, y, self.current_hz, accel)
                    if self.heatmap.is_active:
                        self.heatmap.update(x, y)

                    if self.tracker:
                        self.tracker.update_data(x, y, ts)
                        self.current_hz = self.tracker.hz
                        self.hz_label.config(text=t["hz_label"].format(self.current_hz))
                
                elif etype == "click":
                    _, x, y, button, pressed, ts = item
                    if pressed:
                        self.total_clicks += 1
                    flag = ""
                    if self.tracker:
                        # Метка времени СОБЫТИЯ, а не момента разбора очереди.
                        flag = self.tracker.add_click(button, ts, pressed, x, y)
                        self.update_fault_labels()

                    if self.logger.is_active:
                        hz = self.tracker.hz if self.tracker else self.current_hz
                        accel = dv_index(self.tracker.current_accel) if self.tracker else 0
                        # Пишутся и нажатия, и отпускания: без отпусканий
                        # признак короткого нажатия потом не проверить.
                        action = "Press" if pressed else "Release"
                        self.logger.log(f"{action}_{button}", flag, x, y, hz, accel)

                elif etype == "scroll":
                    _, x, y, dx, dy, ts = item
                    flag = ""
                    if self.tracker:
                        flag = self.tracker.add_scroll(dx, dy, ts)

                    if self.logger.is_active:
                        hz = self.tracker.hz if self.tracker else self.current_hz
                        accel = dv_index(self.tracker.current_accel) if self.tracker else 0
                        # Scroll_Zero -- тик, потерявший направление при делении
                        # на WHEEL_DELTA. Пишется отдельным значением, а не
                        # молчит: по логу должно быть видно, что счёт по этому
                        # колесу вести нельзя.
                        if dy > 0:
                            action = "Scroll_Up"
                        elif dy < 0:
                            action = "Scroll_Down"
                        elif dx > 0:
                            action = "Scroll_Right"
                        elif dx < 0:
                            action = "Scroll_Left"
                        else:
                            action = "Scroll_Zero"
                        self.logger.log(action, flag, x, y, hz, accel)
                        
        except queue.Empty:
            pass

    def update_live_labels(self):
        """Затухание счётчиков и обновление меток. Только главный поток."""
        t = self.tr()

        # Периодическая очистка старых событий (decay)
        if self.tracker:
            now = time.perf_counter()
            self.tracker.event_times = [ts for ts in self.tracker.event_times if now - ts < 1.0]
            self.tracker.click_times = [ts for ts in self.tracker.click_times if now - ts < 1.0]
            self.tracker.hz = len(self.tracker.event_times)
            self.tracker.cps = len(self.tracker.click_times)
            # Здесь же гасится и current_hz. Прежде он писался ТОЛЬКО при
            # разборе события движения: событий нет -- значение не меняется,
            # и число на иконке трея замирало навсегда, а колонка Hz после
            # паузы несла частоту до паузы.
            self.current_hz = self.tracker.hz
            self.peak_hz = max(self.peak_hz, self.tracker.hz)
            self.peak_cps = max(self.peak_cps, self.tracker.cps)
            self.refresh_rate_estimate(now)


            # Если движения нет, плавно снижаем ускорение
            if now - self.tracker.last_time > 0.1:
                self.tracker.current_accel *= 0.5
                if abs(self.tracker.current_accel) < 1: self.tracker.current_accel = 0
            
            try:
                # Обновляем текст меток напрямую через словарь labels
                if 'hz' in self.tracker.labels: self.tracker.labels['hz'].config(text=t["ov_hz"].format(self.tracker.hz))
                if 'cps' in self.tracker.labels: self.tracker.labels['cps'].config(text=t["ov_cps"].format(self.tracker.cps))
                if 'accel' in self.tracker.labels: self.tracker.labels['accel'].config(text=t["ov_accel"].format(self.live_dv()))
                if 'faults' in self.tracker.labels:
                    self.tracker.labels['faults'].config(text=t["ov_faults"].format(self.tracker.fault_counts['left'], self.tracker.fault_counts['right']))

            except tk.TclError:
                # Трекер уничтожен нажатием "стоп" в этом же проходе цикла.
                pass

            # Закреплённый оверлей переезжает, только если курсор ушёл на
            # другой монитор. Проверка живёт здесь, в цикле 10 мс, а не в
            # обработке каждого события движения.
            self.tracker.apply_position()
        else:
            # Сессии нет -- показывать нечего, иконка трея обязана вернуться
            # к нулю, а не сохранять последнее значение прошлой сессии.
            self.current_hz = 0
        try:
            # Текст обновляется ВСЕГДА, независимо от видимости: скрытая
            # строка остаётся честной, если слот освободится.
            # Счётчик потерь намеренно ПЕРЕЖИВАЕТ остановку, в отличие от
            # показаний мыши рядом. Это сообщение не про устройство, а про
            # саму программу -- "я потеряла столько-то событий", -- и гасить
            # его на СТОП значило бы прятать потерю ровно в тот момент, когда
            # её замечают. Обнуляется он на СТАРТЕ следующей сессии, так что
            # чужие потери в новую сессию не переезжают.
            self.dropped_label.config(
                text=t["dropped_label"].format(self.dropped_events))
            # Частота обновляется БЕЗУСЛОВНО. Раньше это делалось внутри
            # ветки "если сессия идёт", и после остановки метка навсегда
            # оставалась с последней частотой сессии -- ровно тот же обрыв
            # в конце цепочки, что и со строкой колеса в фазе 13.
            self.hz_label.config(text=self.hz_line())
            # Счётчики кнопок -- тоже БЕЗУСЛОВНО. См. update_fault_labels().
            self.update_fault_labels()
            self.rate_label.config(text=self.rate_line())
            # Колесо обновляется здесь же. В фазе 11 эта строка была ЗАМЕНЕНА
            # на строку периода -- показание тогда уехало в подсказку трея, --
            # а в фазе 12, когда виджет вернулся в панель, обновление не
            # восстановили. Метка держала текст, поставленный при сборке
            # интерфейса, то есть "прокрутки не было" навсегда.
            self.wheel_label.config(text=self.wheel_line())
            self.update_status_slot()
        except tk.TclError:
            pass
        self.sample_graphs()

    def refresh_rate_estimate(self, now):
        """Пересчёт оценки периода репортов раз в RATE_REFRESH.

        Здесь только обслуживание окна и выбор лучшей за сессию оценки;
        все условия годности живут в report_rate_estimate() и только там.
        """
        if self.tracker is None or now - self.rate_checked_at < RATE_REFRESH:
            return
        self.rate_checked_at = now
        window = [pair for pair in self.tracker.intervals
                  if now - pair[0] < RATE_WINDOW]
        self.tracker.intervals = window
        self.rate_estimate = report_rate_estimate([gap for _, gap in window])
        if self.rate_estimate["state"] == RATE_OK:
            if (self.best_rate is None
                    or self.rate_estimate["samples"] > self.best_rate["samples"]):
                self.best_rate = self.rate_estimate

    def rate_line(self, estimate=None):
        """Строка показания периода: число ТОЛЬКО в состоянии RATE_OK.

        Ступень отраслевой шкалы приписывается лишь тогда, когда период в неё
        уверенно попал. Состояния "мало данных" и "движение медленное" из
        фазы 8 приоритетнее: нет годных данных -- нет и ступени.
        """
        t = self.tr()
        data = estimate if estimate is not None else self.rate_estimate
        if data is None:
            return t["rate_unsure"]
        if data["state"] == RATE_SLOW:
            return t["rate_slow"]
        if data["state"] != RATE_OK:
            return t["rate_unsure"]
        period = "%.2f" % data["period_ms"]
        hz = "%.0f" % data["hz"]
        step, verdict = polling_step(data["period_ms"])
        if verdict == STEP_OK:
            return t["rate_ok_step"].format(period, hz, step)
        if verdict == STEP_BETWEEN:
            return t["rate_ok_between"].format(period, hz)
        return t["rate_ok_fine"].format(period, hz)

    def wheel_line(self):
        """Строка состояния колеса. Число -- ТОЛЬКО в состоянии WHEEL_OK."""
        t = self.tr()
        health = self.wheel_state()
        if health["state"] == WHEEL_OK:
            return t["wheel_ok"].format(health["ticks"], health["reversals"])
        if health["state"] == WHEEL_UNUSABLE:
            return t["wheel_unusable"]
        if health["state"] == WHEEL_FEW:
            return t["wheel_few"].format(health["ticks"])
        return t["wheel_none"]

    def wheel_state(self):
        """Здоровье колеса по текущему трекеру. Решение о годности -- целиком
        в wheel_health(), здесь только сбор аргументов."""
        if self.tracker is None:
            return wheel_health(0, 0, 0)
        return wheel_health(self.tracker.wheel_ticks, self.tracker.wheel_zeros,
                            self.tracker.wheel_reversals)

    def update_status_slot(self):
        """Условная строка счётчика потерь.

        До фазы 12 здесь шла борьба за единственную свободную строку между
        счётчиком потерь и показаниями: высота окна была зашита и место
        кончалось. Вёрстка теперь определяет размер окна сама, бороться не за
        что, и показания живут постоянными строками.

        Счётчик потерь остался УСЛОВНЫМ по другой причине: "Потеряно событий:
        0" -- шум, а не сведения. Появляется он только когда есть о чём
        сообщать, и тогда сдвигает содержимое вниз, а minsize не даёт окну
        обрезать его.

        Перепаковка делается только при смене состояния: дёргать pack сто раз
        в секунду незачем.
        """
        wanted = "dropped" if self.dropped_events > 0 else None
        if wanted == self.slot_shows:
            return
        try:
            self.dropped_label.pack_forget()
            if wanted == "dropped":
                self.dropped_label.pack(fill="x", after=self.suspect_label)
        except tk.TclError:
            return
        self.slot_shows = wanted
        self.fit_window()

    def summary_inconsistencies(self, health, best):
        """Противоречия ВНУТРИ самой сводки. Пустой список -- норма.

        Это не тесты и не замена им. Дефект session_csv нашёлся ЧТЕНИЕМ сводки
        при 256 зелёных проверках: файл написал "csv: not enabled" при
        включённом логе, и ни одна проверка не поймала, потому что ловить надо
        было не поведение, а СОГЛАСОВАННОСТЬ вывода с самим собой. Здесь
        собраны сочетания чисел, которые не могут встретиться одновременно;
        каждое означает, что где-то выше напечатана неправда.
        """
        found = []
        # Именно с движениями: сессия из одних кликов законно имеет нулевую
        # частоту курсора, и сравнение со ВСЕМИ событиями давало ложное
        # срабатывание. Ложное "этому файлу нельзя верить" хуже, чем его
        # отсутствие -- поймано собственным стендом.
        if self.total_moves > 0 and self.peak_hz == 0:
            found.append("peak event rate is 0 while %d cursor moves were"
                         " processed" % self.total_moves)
        if (self.session_csv is None and self.logger.filename
                and os.path.exists(self.logger.filename)):
            found.append("csv reported as not enabled, but %s exists"
                         % os.path.basename(self.logger.filename))
        if self.session_png is None and self.heatmap.data:
            found.append("heatmap reported as not enabled, but %d cells were"
                         " collected" % len(self.heatmap.data))
        if (best is not None and best["state"] == RATE_OK
                and best["samples"] < RATE_MIN_SAMPLES):
            found.append("report period estimated from %d intervals, below the"
                         " floor of %d" % (best["samples"], RATE_MIN_SAMPLES))
        if self.tracker is not None:
            faults = sum(self.tracker.fault_counts.values())
            suspects = sum(self.tracker.suspect_counts.values())
            if (faults or suspects) and self.total_clicks == 0:
                found.append("button faults counted (%d fault, %d suspicious)"
                             " with no clicks recorded" % (faults, suspects))
        if health["reversals"] and not health["ticks"]:
            found.append("wheel reversals counted with no wheel ticks")
        duration = time.perf_counter() - self.session_perf0
        # Допуск в 2 с: активные секунды считаются по номеру корзины, и сессия
        # длиной полсекунды законно попадает в две корзины на границе.
        if len(self.active_seconds) > duration + 2:
            found.append("active time %d s exceeds session duration %.1f s"
                         % (len(self.active_seconds), duration))
        return found

    def write_session_summary(self):
        """Текстовая сводка рядом с CSV. Отдельный файл, а не строки в UI:
        места в окне нет, а в файле оно есть, и читать сводку удобнее, чем
        CSV на сто тысяч строк.

        Порядок разделов: сперва то, что есть почти всегда, затем условное.
        Пустой условный раздел печатается ОДНОЙ строкой, а не выбрасывается:
        файл уходит в баг-репорты, и молчание там двусмысленно -- читатель не
        отличит "прокрутки не было" от "сборка старая, колесо не умеет". Но и
        десяти строк ради "ничего не произошло" наверху быть не должно.

        Никогда не роняет остановку сессии: сводка -- удобство, а не данные.
        """
        if self.session_started is None:
            return None
        # Сводка -- технический артефакт рядом с CSV, и язык у неё такой же:
        # английский. Локализованы показания в UI, а не содержимое файлов.
        try:
            directory = os.path.join(data_dir(), "logs")
            os.makedirs(directory, exist_ok=True)
            path = unique_path(
                directory,
                "session_%s_summary" % self.session_started.strftime(
                    "%Y%m%d_%H%M%S"), ".txt")
            duration = time.perf_counter() - self.session_perf0
            best = self.best_rate
            health = self.wheel_state()

            lines = []
            add = lines.append
            add("MouseMonitorPro -- session summary")
            # Шапка опознания: файл уйдёт в баг-репорт, и читающий должен
            # понимать, от какой сборки он, не спрашивая автора.
            add("summary format v%d | app v%s | CSV format v%d | %s | Python %s"
                % (SUMMARY_FORMAT_VERSION, APP_VERSION, CSV_FORMAT_VERSION,
                   "frozen EXE" if getattr(sys, "frozen", False) else "from source",
                   "%d.%d.%d" % sys.version_info[:3]))
            add("=" * 62)
            add("")

            add("SESSION")
            add("-" * 62)
            add("started        : %s" % self.session_started.isoformat(
                timespec="seconds"))
            add("duration       : %.1f s" % duration)
            add("active         : %d s  (seconds in which at least one event"
                " arrived)" % len(self.active_seconds))
            add("events total   : %d" % self.total_events)
            add("cursor moves   : %d" % self.total_moves)
            add("peak event rate: %d /s  (cursor moves only)" % self.peak_hz)
            add("peak CPS       : %d" % self.peak_cps)
            add("")

            add("REPORT PERIOD ESTIMATE")
            add("-" * 62)
            if best is not None and best["state"] == RATE_OK:
                add("estimate       : %.2f ms  (~%.0f Hz)"
                    % (best["period_ms"], best["hz"]))
                step, verdict = polling_step(best["period_ms"])
                if verdict == STEP_OK:
                    add("standard step  : %d Hz -- the measured period lands on"
                        " it within %.0f%%" % (step, RATE_STEP_TOLERANCE * 100))
                elif verdict == STEP_BETWEEN:
                    add("standard step  : NONE -- the period sits between the")
                    add("                 industry steps (%s Hz)."
                        % ", ".join(str(x) for x in POLLING_STEPS))
                    add("                 Steps are a factor of two apart, so a")
                    add("                 miss means the measurement is poor,")
                    add("                 not that the device runs in between.")
                else:
                    add("standard step  : NOT RESOLVABLE -- at this period the")
                    add("                 %.1f ms histogram bin is wider than"
                        " the" % (RATE_BIN * 1000))
                    add("                 %.0f%% tolerance, so neighbouring"
                        " steps" % (RATE_STEP_TOLERANCE * 100))
                    add("                 cannot be told apart.")
                add("sample         : %d intervals, %.0f events/s in window,"
                    " mode holds %.1f%%"
                    % (best["samples"], best["rate"], best["mode_share"] * 100))
                add("")
                add("harmonic ladder -- share of intervals near k x period:")
                for k, share in best["ladder"]:
                    bar = "#" * int(share * 60)
                    add("  %dx  %6.2f ms  %-60s %5.1f%%"
                        % (k, best["period_ms"] * k, bar, share * 100))
                add("")
                add("Decaying peaks at multiples of the base period are the")
                add("signature of a periodic source some of whose reports move")
                add("the cursor by less than a pixel. A smeared distribution")
                add("would mean the estimate is not trustworthy -- see"
                    " tests/probe_step1.py.")
            else:
                add("estimate       : NOT AVAILABLE")
                add("No valid sample was collected during this session.")
                add("The estimate needs sustained fast movement: at least"
                    " %.0f events/s" % RATE_MIN_RATE)
                add("over a %.0f s window, %d intervals, and a histogram mode"
                    " holding %.0f%%." % (RATE_WINDOW, RATE_MIN_SAMPLES,
                                          RATE_MIN_MODE_SHARE * 100))
                add("Below that, the histogram shows how often the cursor"
                    " crosses pixel")
                add("boundaries, not how often the device reports. Measured:"
                    " at 17 events/s")
                add("the same method produced a confident 7.0 ms mode that was"
                    " simply wrong.")
            add("")

            add("CURSOR SPEED CHANGE (dV)")
            add("-" * 62)
            samples = sorted(self.tracker.dv_samples) if self.tracker else []
            if not samples:
                add("no movement data in this session")
            else:
                add("dV is a RELATIVE index, not a measurement: screen pixels")
                add("after pointer ballistics, no physical units, no industry")
                add("norm. None is invented here. The numbers below describe")
                add("THIS session, to compare against your own other sessions")
                add("taken with the same pointer settings.")
                add("")
                add("samples        : %d%s" % (len(samples),
                    "" if self.tracker.dv_step == 1
                    else " (every %dth, decimated to stay bounded)"
                         % self.tracker.dv_step))
                add("median |dV|    : %d" % percentile(samples, 0.5))
                add("90th percentile: %d" % percentile(samples, 0.9))
                add("peak |dV|      : %d" % samples[-1])
            add("")

            add("BUTTONS")
            add("-" * 62)
            if self.tracker is None:
                add("no button data in this session")
            elif self.total_clicks == 0:
                add("no clicks in this session")
            else:
                add("clicks         : %d" % self.total_clicks)
                add("faults         : L:%d R:%d   (episodes, not signals)"
                    % (self.tracker.fault_counts["left"],
                       self.tracker.fault_counts["right"]))
                add("suspicious     : L:%d R:%d"
                    % (self.tracker.suspect_counts["left"],
                       self.tracker.suspect_counts["right"]))
                add("thresholds     : fault < %d ms or press < %d ms,"
                    " suspicious < %d ms"
                    % (int(DC_FAULT_GAP * 1000), int(DC_SHORT_PRESS * 1000),
                       int(DC_SUSPECT_GAP * 1000)))
                add("HEURISTIC, never calibrated against a chattering switch."
                    " A rising count")
                add("is a reason to look closer, not a verdict; the CSV Flag"
                    " column marks")
                add("every click that fired it.")
                add("")
                gap_ms, box_w, box_h = double_click_limits()
                pairs = self.tracker.dblclk_pairs
                qualify = sorted(int(delta * 1000) for delta, dx, dy in pairs
                                 if delta * 1000 <= gap_ms
                                 and dx <= box_w and dy <= box_h)
                add("double-click vs system rules")
                add("  same-button pairs   : %d" % len(pairs))
                add("  satisfy the rules   : %d" % len(qualify))
                if qualify:
                    add("  median interval     : %d ms" % percentile(qualify, 0.5))
                    add("  fastest             : %d ms" % qualify[0])
                add("  system threshold    : %d ms (GetDoubleClickTime)%s"
                    % (gap_ms, "" if gap_ms == WIN_DEFAULT_DOUBLECLICK_MS
                       else "  -- Windows default is %d"
                            % WIN_DEFAULT_DOUBLECLICK_MS))
                add("  system rectangle    : %d x %d px (SM_CXDOUBLECLK /"
                    " SM_CYDOUBLECLK)" % (box_w, box_h))
                add("  Intent is not observable from the input stream: a slow")
                add("  deliberate pair and a failed double-click look the same.")
                add("  And whether the receiving application treated a")
                add("  qualifying pair as a double-click is its own decision --")
                add("  this only says the pair satisfies the system rules.")
            add("")

            add("SCROLL WHEEL")
            add("-" * 62)
            if health["state"] == WHEEL_UNUSABLE:
                add("ticks          : %d" % health["ticks"])
                add("reversals      : NOT AVAILABLE")
                add("%d of %d ticks (%.0f%%) arrived with no direction at all."
                    % (health["zeros"], health["ticks"],
                       health["zero_share"] * 100))
                add("That is what a high-resolution (free-spin) wheel looks"
                    " like from here:")
                add("it sends increments smaller than one detent, and the input"
                    " library")
                add("divides them by 120 with integer division, so they arrive"
                    " as zero.")
                add("Direction is gone, so wear cannot be detected. Those ticks"
                    " are")
                add("recorded in the CSV as Scroll_Zero if logging was on.")
            elif health["state"] == WHEEL_OK:
                add("ticks          : %d" % health["ticks"])
                add("reversals      : %d  (ticks against the current direction"
                    " within %d ms)"
                    % (health["reversals"], int(WHEEL_REVERSAL_GAP * 1000)))
                add("directionless  : %d" % health["zeros"])
                add("HEURISTIC threshold, never calibrated against a worn"
                    " encoder. Deliberate")
                add("direction changes faster than %d ms count too. The CSV"
                    " Flag column marks"
                    % int(WHEEL_REVERSAL_GAP * 1000))
                add("every tick that fired it.")
            elif health["state"] == WHEEL_FEW:
                add("ticks          : %d" % health["ticks"])
                add("reversals      : not judged -- fewer than %d ticks is too"
                    " little to say" % WHEEL_MIN_TICKS)
                add("                 anything about the encoder.")
            else:
                add("no scrolling in this session")
            add("")

            add("QUEUE AND FILTERING")
            add("-" * 62)
            if self.dropped_events == 0 and self.injected_events == 0:
                add("nothing dropped, no synthetic input filtered")
            else:
                add("dropped events : %d  (queue cap %d)"
                    % (self.dropped_events, EVENT_QUEUE_MAXSIZE))
                add("synthetic      : %d  (LLMHF_INJECTED, filtered out)"
                    % self.injected_events)
            add("")

            add("POINTER SETTINGS AT SESSION START")
            add("-" * 62)
            if self.sys_speed is None:
                add("speed          : unknown")
            else:
                add("speed          : %d/20 on the 1..20 slider%s"
                    % (self.sys_speed,
                       "  (Windows default)"
                       if self.sys_speed == WIN_DEFAULT_POINTER_SPEED
                       else "  -- Windows default is %d"
                            % WIN_DEFAULT_POINTER_SPEED))
            if self.pointer_precision is None:
                add("enhanced prec. : unknown")
            elif self.pointer_precision:
                add("enhanced prec. : ON -- cursor displacement depends"
                    " non-linearly on")
                add("                 movement speed, so both dV and the report"
                    " period")
                add("                 estimate are distorted by it.")
            else:
                add("enhanced prec. : off -- displacement stays proportional to"
                    " movement,")
                add("                 which is the condition for dV and the"
                    " period estimate")
                add("                 to mean anything at all.")
            add("devices        : %s" % self.hw_info)
            add("")

            add("FILES")
            add("-" * 62)
            add("csv            : %s" % (os.path.basename(self.session_csv)
                                         if self.session_csv else "not enabled"))
            add("heatmap        : %s" % (os.path.basename(self.session_png)
                                         if self.session_png else "not enabled"))

            problems = self.summary_inconsistencies(health, best)
            if problems:
                add("")
                add("INCONSISTENCIES")
                add("-" * 62)
                add("This summary contradicts itself, so the numbers above are")
                add("not trustworthy. Please attach this file to a bug report.")
                for problem in problems:
                    add("inconsistency: %s" % problem)

            add("")
            add("All numbers are summed over every device that moves the"
                " cursor;")
            add("a low-level hook cannot tell them apart. See README.")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
            return path
        except OSError:
            logging.exception("не удалось записать сводку сессии")
            return None

    def on_mouse_move(self, x, y, injected=False):
        """Исполняется ВНУТРИ низкоуровневого хука: ни Tk, ни блокировок,
        только постановка в очередь.

        injected -- событие сгенерировано программно (SendInput/mouse_event),
        а не устройством. Такие события к телеметрии мыши отношения не имеют
        и отбрасываются. Значение по умолчанию False существует ради
        проверок: вызов обработчика напрямую, в обход хука, фильтром не
        режется, и подсовывать флаг для тестов не требуется.
        """
        if injected:
            self.injected_events += 1
            return
        try:
            self.data_queue.put_nowait(("move", x, y, time.perf_counter()))
        except queue.Full:
            # Единственный писатель счётчика -- этот поток, поэтому += корректен
            # без блокировки; главный поток счётчик только читает.
            self.dropped_events += 1

    def on_click(self, x, y, button, pressed, injected=False):
        if injected:
            self.injected_events += 1
            return
        try:
            self.data_queue.put_nowait(
                ("click", x, y, button, pressed, time.perf_counter()))
        except queue.Full:
            self.dropped_events += 1

    def on_scroll(self, x, y, dx, dy, injected=False):
        """Тик колеса. Как и остальные обработчики -- только в очередь."""
        if injected:
            self.injected_events += 1
            return
        try:
            self.data_queue.put_nowait(
                ("scroll", x, y, dx, dy, time.perf_counter()))
        except queue.Full:
            self.dropped_events += 1

    def update_info_display(self):
        t = self.tr()
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", "end")
        speed = t["unknown"] if self.sys_speed is None else f"{self.sys_speed}/20"
        if self.pointer_precision is None:
            precision = t["unknown"]
        else:
            precision = t["state_on"] if self.pointer_precision else t["state_off"]

        self.info_text.insert("1.0", f"{t['device']}: {self.hw_info}\n")
        self.info_text.insert("end", f"{t['win_speed']}: {speed}\n")
        self.info_text.insert("end", f"{t['pointer_precision']}: {precision}")
        self.info_text.config(state="disabled")

    def start_listener(self):
        """Ставит низкоуровневый хук мыши. Хук живёт ровно столько, сколько
        идёт сессия: раньше он ставился в __init__ и не снимался никогда,
        то есть "СТОП" не останавливал мониторинг."""
        if self.listener is not None:
            return
        self.listener = mouse.Listener(on_move=self.on_mouse_move,
                                       on_click=self.on_click,
                                       on_scroll=self.on_scroll)
        self.listener.start()
        logging.info("хук мыши установлен")

    def stop_listener(self):
        if self.listener is None:
            return
        try:
            self.listener.stop()
        except Exception:
            logging.exception("не удалось снять хук мыши")
        self.listener = None
        logging.info("хук мыши снят; отфильтровано синтетических событий: %d",
                     self.injected_events)

    def toggle_tracker(self):
        t = self.tr()
        if self.tracker is None:
            skin = SKINS.get(self.skin_var.get(), SKINS["Dark (Default)"])
            show_config = {
                'pos': self.show_pos.get(),
                'accel': self.show_accel.get(),
                'hz': self.show_hz.get(),
                'cps': self.show_cps.get(),
                'faults': self.show_faults.get()
            }
            if not any(show_config.values()) and not self.enable_logging.get() and not self.enable_heatmap.get(): 
                return
                
            self.tracker = FloatingTracker(
                self, 
                skin, 
                show_config, 
                alpha=self.overlay_alpha.get(),
                click_through=self.click_through.get(),
                position_mode=self.position_mode
            )
            
            # Обнуление сессионного состояния идёт ПЕРВЫМ, до открытия
            # артефактов: иначе оно затирает имена, которые записывают ветки
            # логирования и теплокарты ниже, и сводка врала "csv: not enabled"
            # при включённом логе.
            self.dropped_events = 0
            self.injected_events = 0
            self.session_started = datetime.now()
            self.session_perf0 = time.perf_counter()
            self.peak_hz = 0
            self.peak_cps = 0
            self.total_events = 0
            self.total_moves = 0
            self.total_clicks = 0
            self.active_seconds = set()
            self.session_csv = None
            self.session_png = None
            self.rate_estimate = None
            self.best_rate = None
            self.rate_checked_at = 0.0

            status_parts = []
            if self.enable_logging.get():
                fname = self.logger.start()
                # Отказ открытия лога виден пользователю, а не только в
                # диагностическом логе: сессия при этом продолжается.
                status_parts.append(t["log_active"].format(os.path.basename(fname))
                                    if fname else t["log_failed"])
                self.session_csv = fname

            if self.enable_heatmap.get():
                self.heatmap.start()
                status_parts.append(t["map_active"])

            # Хук ставится последним: счётчики уже обнулены, и поток хука не
            # может написать в них до сброса.
            self.start_listener()
            self.log_status.config(text=" | ".join(status_parts))
            self.btn_toggle.config(text=t["btn_stop"])
        else:
            self.stop_session()

    def stop_session(self):
        """Останавливает сессию: снимает хук, дочитывает очередь, закрывает
        лог и сохраняет теплокарту."""
        t = self.tr()

        # Сначала снимаем хук -- новых событий больше не будет.
        self.stop_listener()
        # Затем добираем уже накопленное: эти события принадлежат сессии.
        self.process_events()

        status_parts = []
        if self.logger.is_active:
            self.logger.stop()
            status_parts.append(t["log_saved"])

        if self.heatmap.is_active:
            saved = self.heatmap.save()
            if saved:
                self.session_png = saved
                status_parts.append(t["map_saved"])

        # Сводка пишется ПОСЛЕ закрытия лога и сохранения карты -- чтобы знать
        # их имена -- и ДО сноса оверлея, потому что берёт счётчики из него.
        # Проверенный порядок останова (хук -> очередь -> лог -> PNG ->
        # оверлей) при этом не меняется: добавлен шаг, а не переставлены
        # существующие.
        self.write_session_summary()
        self.session_started = None
        # Оценка периода принадлежит сессии и обязана уйти вместе с ней.
        # Иначе строка панели держит "Период репортов: 1.00 мс (~1000 Гц)"
        # рядом с "События курсора: 0/с" -- утверждение про настоящее время,
        # измеренное в прошлом. Четвёртый случай того же класса, что
        # wheel_label (фаза 13), hz_label и счётчики кнопок (фаза 15).
        #
        # ПОСЛЕ write_session_summary() -- не раньше. Сводке нужен best_rate,
        # он живёт до следующего СТАРТА и здесь не трогается, но порядок
        # важен: сброс перед записью сводки был бы ровно той ошибкой, от
        # которой предостерегает комментарий выше про порядок останова.
        self.rate_estimate = None

        try:
            self.log_status.config(text=" | ".join(status_parts))
        except tk.TclError:
            pass

        if self.tracker is not None:
            self.tracker.destroy()
            self.tracker = None

        try:
            self.btn_toggle.config(text=t["btn_start"])
        except tk.TclError:
            pass

    def create_dynamic_icon(self, text):
        img = Image.new('RGB', (64, 64), color=(20, 20, 20))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], outline=(46, 204, 113), width=4)

        font = tray_font()
        text_str = str(text)
        # Центрирование по РЕАЛЬНЫМ метрикам текста. Прежняя оценка ширины
        # как len(text) * 14 разъезжалась на трёх и четырёх знаках.
        left, top, right, bottom = d.textbbox((0, 0), text_str, font=font)
        d.text(((64 - (right - left)) // 2 - left,
                (64 - (bottom - top)) // 2 - top),
               text_str, fill=(255, 255, 255), font=font)
        return img

    def build_tray_menu(self):
        """Меню трея. Пункты НЕ трогают Tk: они лишь ставят команду в очередь
        главного потока."""
        t = self.tr()
        return pystray.Menu(
            pystray.MenuItem(t["tray_expand"], self.request_expand),
            pystray.MenuItem(t["tray_exit"], self.request_shutdown),
        )

    def request_expand(self, icon=None, item=None):
        """Вызывается из потока pystray."""
        self.command_queue.put(self.root.deiconify)

    def request_shutdown(self, icon=None, item=None):
        """Вызывается из потока pystray."""
        self.command_queue.put(self.shutdown)

    def setup_tray(self):
        try:
            icon = pystray.Icon("mouse_pro", self.create_dynamic_icon(0),
                                self.tray_tip_base())
            icon.menu = self.build_tray_menu()
            # Публикуем только полностью собранный объект, затем сообщаем
            # главному потоку, что им можно пользоваться.
            self.icon = icon
            self.icon_ready.set()
            icon.run()
        except Exception:
            logging.exception("поток иконки в трее завершился аварийно")

    def update_tray_loop(self):
        if self.shutting_down:
            return
        # Перерисовываем ТОЛЬКО при изменившемся значении. pystray на каждое
        # присвоение .icon сериализует картинку во временный ICO-файл на диске
        # (_assert_icon_handle -> serialized_image); при неизменном показании
        # это была запись на диск дважды в секунду всё время работы.
        if (self.icon_ready.is_set() and self.icon.visible
                and self.current_hz != self.tray_icon_value):
            try:
                self.icon.icon = self.create_dynamic_icon(self.current_hz)
                self.tray_icon_value = self.current_hz
            except Exception:
                logging.exception("не удалось обновить иконку в трее")

        # Подсказка обновляется по тому же правилу, что и иконка: только при
        # изменившемся тексте. Смена title дёргает Shell_NotifyIcon, и звать
        # его дважды в секунду без нужды незачем.
        if self.icon_ready.is_set() and self.icon.visible:
            title = self.tray_title_text()
            if title != self.tray_title:
                try:
                    self.icon.title = title
                    self.tray_title = title
                except Exception:
                    logging.exception("не удалось обновить подсказку в трее")
        self.root.after(500, self.update_tray_loop)

    def tray_tip_base(self):
        """Имя с версией для подсказки трея, на текущем языке."""
        return tray_tip(self.current_lang)

    def tray_title_text(self):
        """Текст подсказки в трее. Единственное место сборки.

        Вынесен из update_tray_loop ради проверяемости: там он собирался за
        условием `icon_ready`, а в стенде настоящей иконки трея нет, и
        проверить подсказку прогоном было нечем. Ровно так же незаметно
        замерла бы и она.

        Версия дописана к имени, а состояние колеса -- после него: подсказка
        и раньше состояла из двух частей, порядок не менялся, добавилось
        только "v{версия}" в первой. Длина остаётся далеко под TRAY_TIP_LIMIT,
        это проверяется стендом на всех состояниях колеса и обоих языках.
        """
        if self.tracker is None:
            return self.tray_tip_base()
        return "%s -- %s" % (self.tray_tip_base(), self.wheel_line())

    def shutdown(self):
        """Единственная точка выхода: и крестик окна, и пункт трея.

        Раньше обработчика WM_DELETE_WINDOW не было вовсе: закрытие окна
        теряло теплокарту целиком и оставляло CSV с несброшенным буфером.
        """
        if self.shutting_down:
            return
        self.shutting_down = True
        logging.info("завершение работы")

        if self.tracker is not None or self.logger.is_active or self.heatmap.is_active:
            self.stop_session()
        self.stop_listener()

        if self.icon_ready.is_set():
            try:
                self.icon.stop()
            except Exception:
                logging.exception("не удалось остановить иконку в трее")

        self.root.destroy()

if __name__ == "__main__":
    setup_logging()

    awareness, method = enable_dpi_awareness()
    root = tk.Tk()
    dpi, scale = apply_ui_scaling(root)

    logging.info("старт: DPI awareness=%s (через %s); DPI=%d; масштаб UI=%.2f",
                 awareness, method, dpi, scale)
    if awareness not in ("PER_MONITOR_AWARE", "SYSTEM_AWARE"):
        logging.warning(
            "процесс НЕ является DPI-осведомлённым (%s): координаты мыши и "
            "метрики экрана будут логическими, теплокарта -- уменьшенной",
            awareness)

    app = MainControlPanel(root)
    root.mainloop()
