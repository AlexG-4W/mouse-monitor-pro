"""Проверка критериев приёмки Фазы 15 -- живые надписи в ОБОИХ состояниях.

Четыре бага одного класса: `wheel_label` (фаза 13), `hz_label` (фаза 14),
`faults_label` с `suspect_label` и `rate_label` (фаза 15). Механизм каждый раз
один: обновление метки лежит внутри `if self.tracker:`, за ранним `return` или
читает поле, которое на СТОП не сбрасывается, -- и после остановки метка
навсегда держит значение законченной сессии. Панель при этом одновременно
утверждает, что сессии нет и что прямо сейчас есть шесть ошибок кнопки и
период репортов 1.00 мс.

Первые три нашлись случайно. Четвёртый (`rate_label`) нашёл ЭТОТ НАБОР на
первом же прогоне -- причём только тот его раздел, который ДОВОДИТ оценку до
годного состояния. Общая проверка той же строки в разделе 3 проходила
вхолостую: синтетика не давала годной оценки, строка всё время стояла в
"недостаточно данных", и сравнение с покоем было тождеством (грабли №3 --
молчаливо-зелёная проверка). Оба раздела оставлены нарочно: второй
показывает, зачем нужен первый.

Набор построен на трёх опорах:

  1. Надписи ПЕРЕЧИСЛЯЮТСЯ САМИ. Каждая метка панели обязана быть отнесена
     к одному из известных видов; незнакомая метка -- отказ с её именем.
     Забыть внести новую строку в проверку становится трудно.
  2. Каждая живая надпись проверяется в ДВУХ состояниях: во время сессии и
     после СТОП. Числа между наборами данных НАМЕРЕННО разные.
  3. Структурная страховка: ни одно обновление живой надписи не имеет права
     стоять внутри `if self.tracker:` -- это проверяется по дереву разбора,
     а не текстовым поиском.
"""
import ast
import io
import os
import re
import sys
import time
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mouse_info_app as A

ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print("  [%s] %-58s %s" % ("PASS" if cond else "FAIL", name, detail))


class FakeListener:
    def __init__(self, **kwargs):
        pass

    def start(self):
        pass

    def stop(self):
        pass


A.mouse.Listener = FakeListener
A.setup_logging()
A.enable_dpi_awareness()
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT_DIR, "mouse_info_app.py"),
              encoding="utf-8").read()

root = tk.Tk()
root.withdraw()
A.apply_ui_scaling(root)
app = A.MainControlPanel(root)
root.update()

# Виды надписей.
#   live     -- показание мыши: меняется в сессии, ПОСЛЕ СТОП возвращается
#               к состоянию покоя, потому что мерить больше нечего
#   program  -- сообщение о самой программе: переживает СТОП намеренно
#   session  -- статус сессии (имена файлов), меняется на старте и остановке
#   layout   -- зависит от размера окна, а не от сессии
#   static   -- не меняется никогда
KINDS = {
    "hz_label": "live",
    "rate_label": "live",
    "wheel_label": "live",
    "faults_label": "live",
    "suspect_label": "live",
    "dropped_label": "program",
    "log_status": "session",
    "graph_hint": "layout",
    "dc_note": "static",
}
LIVE = sorted(name for name, kind in KINDS.items() if kind == "live")


def tick(times=1):
    for _ in range(times):
        app.process_events()
        app.update_live_labels()
        root.update()


def text_of(name):
    return getattr(app, name).cget("text")


def feed_moves(count, base):
    now = time.perf_counter()
    for i in range(count):
        app.data_queue.put_nowait(("move", base + i * 5, base + i * 3,
                                   now + i * 0.003))


def feed_clicks(count, gap, button="Button.left", base=500):
    now = time.perf_counter()
    for i in range(count):
        app.data_queue.put_nowait((
            "click", base, base, button, True, now + i * gap))
        app.data_queue.put_nowait((
            "click", base, base, button, False, now + i * gap + 0.004))


# --- 1. надписи перечисляются сами ------------------------------------------------
print("=== 1. каждая надпись панели классифицирована ===")
found = set()
for name in dir(app):
    if name.startswith("_"):
        continue
    try:
        widget = getattr(app, name)
    except Exception:
        continue
    if isinstance(widget, ttk.Label):
        try:
            parent = widget.winfo_parent()
        except tk.TclError:
            continue
        if parent == app.frame.winfo_pathname(app.frame.winfo_id()):
            found.add(name)
print("   найдено меток в колонке: %s" % ", ".join(sorted(found)))
unknown = found - set(KINDS)
check("незнакомых меток нет", not unknown,
      "не классифицированы: %s" % sorted(unknown) if unknown else "")
missing = set(KINDS) - found
check("все объявленные метки на месте", not missing,
      "пропали: %s" % sorted(missing) if missing else "")
check("живых надписей не меньше пяти", len(LIVE) >= 5, str(LIVE))

# --- 2. состояние покоя -----------------------------------------------------------
print()
print("=== 2. состояние покоя запомнено до первой сессии ===")
idle = {name: text_of(name) for name in KINDS}
for name in LIVE:
    print("   покой: %-14s %r" % (name, idle[name]))
check("до старта сессии нет", app.tracker is None)

# --- 3. сессия A -> сессия B -> СТОП ------------------------------------------------
print()
print("=== 3. каждая живая надпись: сессия -> другая сессия -> СТОП ===")
app.toggle_tracker()
root.update()
feed_moves(40, 400)
feed_clicks(5, A.DC_FAULT_GAP / 2)                      # даст ошибки слева
feed_clicks(4, (A.DC_SUSPECT_GAP + A.DC_FAULT_GAP) / 2,
            button="Button.right")                      # подозрительные справа
for _ in range(A.WHEEL_MIN_TICKS + 2):
    app.on_scroll(400, 400, 0, -1)
app.dropped_events = 3
tick(2)
state_a = {name: text_of(name) for name in KINDS}

# Набор B: числа ДРУГИЕ. Совпадение значений сделало бы "текст изменился"
# бессмысленным -- см. грабли №7.
feed_moves(17, 900)
feed_clicks(3, A.DC_FAULT_GAP / 2)
feed_clicks(2, (A.DC_SUSPECT_GAP + A.DC_FAULT_GAP) / 2, button="Button.right")
for _ in range(3):
    app.on_scroll(900, 900, 0, 1)
app.dropped_events = 11
tick(2)
state_b = {name: text_of(name) for name in KINDS}

for name in LIVE:
    if name == "rate_label":
        continue        # у него отдельный раздел: нужны условия годности
    print("   %-14s A=%r B=%r" % (name, state_a[name], state_b[name]))
    check("%s: живая в сессии (A != покой)" % name,
          state_a[name] != idle[name], state_a[name])
    check("%s: следит за источником (B != A)" % name,
          state_b[name] != state_a[name], state_b[name])

app.stop_session()
tick(5)
state_stop = {name: text_of(name) for name in KINDS}
print()
for name in LIVE:
    print("   после СТОП: %-14s %r" % (name, state_stop[name]))
    check("%s: после СТОП вернулась в покой" % name,
          state_stop[name] == idle[name],
          "%r при покое %r" % (state_stop[name], idle[name]))
    check("%s: и не держит значение сессии" % name,
          state_stop[name] != state_b[name] or state_b[name] == idle[name],
          state_stop[name])

# --- 4. счётчик потерь -- намеренное исключение --------------------------------------
print()
print("=== 4. счётчик потерь переживает СТОП намеренно ===")
check("в сессии счётчик менялся", state_b["dropped_label"]
      != state_a["dropped_label"],
      "%r -> %r" % (state_a["dropped_label"], state_b["dropped_label"]))
check("после СТОП сообщение о потере НЕ спрятано",
      state_stop["dropped_label"] == state_b["dropped_label"],
      state_stop["dropped_label"])
check("и число потерь в нём то же", "11" in state_stop["dropped_label"],
      state_stop["dropped_label"])
app.toggle_tracker()
root.update()
tick(2)
check("новая сессия обнуляет счётчик, чужие потери не переезжают",
      text_of("dropped_label") == idle["dropped_label"],
      text_of("dropped_label"))
check("и сам счётчик обнулён", app.dropped_events == 0,
      str(app.dropped_events))
app.stop_session()
tick(2)

# --- 5. строка периода репортов в обоих состояниях -------------------------------------
print()
print("=== 5. строка периода: годная оценка -> СТОП ===")
app.toggle_tracker()
root.update()
# Условия годности: не меньше RATE_MIN_RATE событий/с и RATE_MIN_SAMPLES
# интервалов в окне RATE_WINDOW. Метки времени -- от perf_counter и близкие
# к настоящему времени, иначе пруннинг окон врёт (грабли №5).
now = time.perf_counter()
count = A.RATE_MIN_SAMPLES * 3
for i in range(count):
    app.data_queue.put_nowait(("move", 500 + (i % 7), 500 + (i % 5),
                               now - (count - i) * 0.001))
app.process_events()
app.rate_checked_at = 0.0
app.refresh_rate_estimate(time.perf_counter())
app.update_live_labels()
root.update()
rate_live = text_of("rate_label")
print("   оценка: %r" % (app.rate_estimate or {}).get("state"))
print("   строка: %r" % rate_live)
check("оценка периода стала годной",
      app.rate_estimate is not None
      and app.rate_estimate["state"] == A.RATE_OK,
      str((app.rate_estimate or {}).get("state")))
check("строка периода показывает число, а не 'нет данных'",
      rate_live != idle["rate_label"] and rate_live == app.rate_line(),
      rate_live)
app.stop_session()
tick(5)
print("   после СТОП: %r" % text_of("rate_label"))
check("после СТОП строка периода вернулась в покой",
      text_of("rate_label") == idle["rate_label"], text_of("rate_label"))

# --- 6. надписи оверлея ------------------------------------------------------------------
print()
print("=== 6. оверлей: движение идёт -> движение прекратилось ===")
app.toggle_tracker()
root.update()
feed_moves(50, 700)
feed_clicks(3, 0.2)
tick(2)
moving = {key: widget.cget("text")
          for key, widget in app.tracker.labels.items()}
for key in sorted(moving):
    print("   движение: %-8s %r" % (key, moving[key]))
check("оверлей показывает частоту", "50" in moving.get("hz", ""),
      moving.get("hz"))
check("оверлей показывает координаты", moving.get("pos", "") != "",
      moving.get("pos"))

deadline = time.perf_counter() + 1.4
while time.perf_counter() < deadline:
    tick(1)
    time.sleep(0.005)
stopped = {key: widget.cget("text")
           for key, widget in app.tracker.labels.items()}
for key in sorted(stopped):
    print("   покой   : %-8s %r" % (key, stopped[key]))
check("частота на оверлее затухла до нуля",
      stopped.get("hz") == A.TRANSLATIONS[app.current_lang]["ov_hz"].format(0),
      stopped.get("hz"))
check("dV на оверлее затух до нуля",
      "0" in stopped.get("accel", "") and stopped.get("accel") != moving.get("accel"),
      stopped.get("accel"))
check("частота действительно менялась, а не была нулём всегда",
      moving.get("hz") != stopped.get("hz"),
      "%r -> %r" % (moving.get("hz"), stopped.get("hz")))
check("координаты держат ПОСЛЕДНЕЕ положение, а не гаснут",
      stopped.get("pos") == moving.get("pos"), stopped.get("pos"))

# --- 7. подсказка трея -------------------------------------------------------------------
print()
print("=== 7. подсказка трея в обоих состояниях ===")
for _ in range(A.WHEEL_MIN_TICKS + 3):
    app.on_scroll(700, 700, 0, -1)
tick(2)
tray_live = app.tray_title_text()
print("   в сессии  : %r" % tray_live)
check("подсказка в сессии несёт состояние колеса",
      tray_live == "%s -- %s" % (app.tray_tip_base(), app.wheel_line())
      and tray_live != app.tray_tip_base(), tray_live)
app.stop_session()
tick(3)
print("   после СТОП: %r" % app.tray_title_text())
check("после СТОП подсказка вернулась к имени программы",
      app.tray_title_text() == app.tray_tip_base(), app.tray_title_text())
check("подсказка собирается в одном месте",
      "def tray_title_text" in SRC
      and "title = self.tray_title_text()" in SRC)

# --- 8. структурная страховка: обновления вне ветки сессии ---------------------------------
print()
print("=== 8. ни одно обновление живой строки не заперто в ветке сессии ===")
tree = ast.parse(SRC)
target = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "update_live_labels":
        target = node
check("update_live_labels найдена в дереве разбора", target is not None)


def guarded_by_tracker(node):
    """Тест ветки -- это `self.tracker` (или `self.tracker is not None`)."""
    test = node.test
    if isinstance(test, ast.Compare) and len(test.comparators) == 1:
        test = test.left
    return (isinstance(test, ast.Attribute) and test.attr == "tracker"
            and isinstance(test.value, ast.Name) and test.value.id == "self")


def calls_in(body):
    """Имена вида self.X_label.config и self.update_fault_labels.

    Принимает СПИСОК узлов (тело ветви), а не узел: ast.walk по списку
    падает на отсутствии _fields.
    """
    out = set()
    for sub in [n for root_node in body for n in ast.walk(root_node)]:
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if (isinstance(func, ast.Attribute) and func.attr == "config"
                and isinstance(func.value, ast.Attribute)
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "self"):
            out.add(func.value.attr)
        if (isinstance(func, ast.Attribute)
                and func.attr == "update_fault_labels"):
            out.add("faults_label")
            out.add("suspect_label")
    return out


locked = set()
if target is not None:
    for node in ast.walk(target):
        if isinstance(node, ast.If) and guarded_by_tracker(node):
            locked |= calls_in(node.body)
print("   обновляется ТОЛЬКО внутри `if self.tracker:`: %s"
      % (sorted(locked) or "ничего"))
for name in LIVE:
    check("%s обновляется вне ветки сессии" % name, name not in locked,
          "заперта в `if self.tracker:`" if name in locked else "")
check("счётчики кнопок больше не выходят по раннему return",
      "if self.tracker is None:\n            return"
      not in SRC.split("def update_fault_labels")[1].split("\n    def ")[0])

# --- 9. смена языка не рвёт ни одного состояния ---------------------------------------------
print()
print("=== 9. смена языка в обоих состояниях ===")
for lang in ("Русский", "English"):
    app.lang_var.set(lang)
    app.setup_ui()
    root.update()
    t = A.TRANSLATIONS[lang]
    check("%s: покой после смены языка -- на этом языке" % lang,
          text_of("hz_label") == t["hz_label"].format(0),
          text_of("hz_label"))
    app.toggle_tracker()
    root.update()
    feed_moves(23, 300)
    for _ in range(A.WHEEL_MIN_TICKS + 1):
        app.on_scroll(300, 300, 0, -1)
    tick(2)
    check("%s: в сессии строки живые" % lang,
          text_of("hz_label") == app.hz_line()
          and "23" in text_of("hz_label")
          and text_of("wheel_label") == app.wheel_line(),
          text_of("hz_label"))
    app.stop_session()
    tick(3)
    check("%s: после СТОП вернулись в покой на этом языке" % lang,
          text_of("hz_label") == t["hz_label"].format(0)
          and text_of("wheel_label") == t["wheel_none"],
          "%r / %r" % (text_of("hz_label"), text_of("wheel_label")))

# --- 10. документация не разошлась с кодом ------------------------------------------------
print()
print("=== 10. числа в документации привязаны к константам ===")
README = io.open(os.path.join(ROOT_DIR, "README.md"), encoding="utf-8").read()
# HANDOFF необязателен: в публичный комплект он не входит. Число проверок
# при этом ДОЛЖНО совпадать с файлом и без него -- run_all.py сверяет его с
# README, и плавающее число сломало бы ту сверку. Поэтому проверки по HANDOFF
# не выбрасываются, а становятся условными, и режим печатается явно: пустая
# проверка не должна выглядеть содержательной (грабли №3).
HANDOFF_PATH = os.path.join(ROOT_DIR, "docs", "HANDOFF.md")
HANDOFF_PRESENT = os.path.exists(HANDOFF_PATH)
HANDOFF = (io.open(HANDOFF_PATH, encoding="utf-8").read()
           if HANDOFF_PRESENT else "")
if not HANDOFF_PRESENT:
    print("   docs/HANDOFF.md отсутствует -- проверки по нему условны")

# Каждая пара -- утверждение документации и константа, из которой оно взято.
# "146 проверок" пережили в README несколько фаз именно потому, что ни одно
# число не было ни к чему привязано. Число наборов и проверок сверяет
# run_all.py (там оно известно после прогона), остальное -- здесь.
CLAIMS = [
    ("порог ошибки по паузе", "under **8 ms**", int(A.DC_FAULT_GAP * 1000) == 8),
    ("порог короткого нажатия", "shorter than **15 ms**",
     int(A.DC_SHORT_PRESS * 1000) == 15),
    ("порог подозрительного", "between **8 and 25 ms**",
     int(A.DC_SUSPECT_GAP * 1000) == 25),
    ("обратный тик колеса", "**within 50 ms**",
     int(A.WHEEL_REVERSAL_GAP * 1000) == 50),
    ("допуск ступени", "tolerance is 12%", A.RATE_STEP_TOLERANCE == 0.12),
    ("корзина гистограммы", "binned at 0.1 ms", A.RATE_BIN == 0.0001),
    ("шаг графика", "the graphs every 50 ms", A.GRAPH_SAMPLE_MS == 50),
    ("окно графика", "300 samples, 15 seconds",
     A.GRAPH_SLOTS == 300 and A.GRAPH_WINDOW_S == 15),
    ("постоянная сглаживания", "smoothing constant is 60 ms",
     int(A.ACCEL_TAU * 1000) == 60),
    ("версия CSV", "CSV format v4", A.CSV_FORMAT_VERSION == 4),
]
for name, quote, matches in CLAIMS:
    check("README говорит про %s" % name, quote in README, quote)
    check("...и это совпадает с константой", matches)

check("README про условия годности оценки",
      "at least %d events/s" % int(A.RATE_MIN_RATE) in README
      and "%d-second window" % int(A.RATE_WINDOW) in README
      and "at least %d\nintervals" % A.RATE_MIN_SAMPLES in README
      and "at least %d%%" % int(A.RATE_MIN_MODE_SHARE * 100) in README,
      "%d/%d/%d/%d" % (A.RATE_MIN_RATE, A.RATE_WINDOW, A.RATE_MIN_SAMPLES,
                       A.RATE_MIN_MODE_SHARE * 100))
# Падеж не диктуем: сверяется ЧИСЛО рядом со словом. Иначе грамотно
# написанная строка ("61 ключу") роняла бы проверку, а неуклюжая
# ("61 ключей") проходила -- проверка воспитывала бы плохой текст.
keys_count = len(A.TRANSLATIONS["English"])
lines_count = sum(1 for _ in io.open(
    os.path.join(ROOT_DIR, "mouse_info_app.py"), encoding="utf-8"))
check("HANDOFF знает актуальное число ключей локализации",
      not HANDOFF_PRESENT
      or re.search(r"\*\*%d ключ\w*\*\*" % keys_count, HANDOFF) is not None,
      "в коде %d%s" % (keys_count,
                       "" if HANDOFF_PRESENT else " (файла нет)"))
check("HANDOFF знает актуальное число строк файла",
      not HANDOFF_PRESENT
      or re.search(r"\*\*%d строк\w*\*\*" % lines_count, HANDOFF) is not None,
      "в коде %d%s" % (lines_count,
                       "" if HANDOFF_PRESENT else " (файла нет)"))

# Файлы, на которые ссылается документация, обязаны существовать.
# Сверяется ИМЯ файла, а не путь: README пишет часть из них без префикса
# `tests/`, и условие по полному пути молча пропускало два файла из шести --
# проверка была зелёной, ничего не проверяя (грабли №3).
for relative in ("tests/probe_step1.py", "tests/rawinput_probe.py",
                 "tests/dc_table.py", "tests/probe_injected.py",
                 "tests/run_all.py", "MouseMonitorPro.spec"):
    basename = os.path.basename(relative)
    check("README упоминает %s" % basename, basename in README)
    check("...и файл существует",
          os.path.exists(os.path.join(ROOT_DIR, relative.replace("/", os.sep))))

check("README больше не утверждает, что колонка центрируется",
      "centres itself" not in README)
check("README описывает графики", "Live graphs" in README)
check("README описывает два состояния живой строки",
      "either shows a live reading or shows nothing" in README)

# --- 11. версия видна пользователю ---------------------------------------------------
print()
print("=== 11. версия сборки видна в интерфейсе ===")
# Заголовок читается ИЗ ОКНА через GetWindowText -- то же, что увидит
# пользователь и что покажет диспетчер задач. Проверять self.root.title()
# значило бы спросить Tk о том, что мы сами ему и сказали.
import win32gui

hwnd = int(root.frame(), 16)
shown = win32gui.GetWindowText(hwnd)
print("   GetWindowText -> %r" % shown)
check("заголовок окна читается из системы", shown != "", repr(shown))
check("в заголовке стоит версия из APP_VERSION",
      shown == "Mouse Monitor Pro v%s" % A.APP_VERSION, shown)
check("и он собран источником, а не набран руками",
      shown == A.window_title(app.current_lang), shown)
# Искать надо ГОТОВУЮ строку заголовка с вшитым номером, а не подстроку
# "v3.1": последняя встречается в комментарии у APP_VERSION как пример того,
# чего делать нельзя, и проверка падала на собственной документации.
check("готовый заголовок с вшитым номером в коде не набран",
      ("Mouse Monitor Pro v%s" % A.APP_VERSION) not in SRC)
check("номер версии объявлен ровно один раз",
      SRC.count('APP_VERSION = "') == 1)

for lang in ("Русский", "English"):
    app.lang_var.set(lang)
    app.setup_ui()
    root.update()
    shown = win32gui.GetWindowText(hwnd)
    check("%s: заголовок пережил смену языка" % lang,
          shown == "Mouse Monitor Pro v%s" % A.APP_VERSION, shown)

# Подсказка трея: версия есть, и длина укладывается в предел Shell_NotifyIcon
# на ВСЕХ состояниях колеса, а не только на том, что попалось в прогоне.
print()
longest = ("", 0)
for lang in A.TRANSLATIONS:
    base = A.tray_tip(lang)
    check("%s: в подсказке трея есть версия" % lang,
          A.APP_VERSION in base, base)
    for key, args in (("wheel_ok", (999999, 99999)), ("wheel_none", ()),
                      ("wheel_few", (9999,)), ("wheel_unusable", ())):
        tip = "%s -- %s" % (base, A.TRANSLATIONS[lang][key].format(*args))
        if len(tip) > longest[1]:
            longest = (tip, len(tip))
print("   самая длинная подсказка: %d знаков при пределе %d"
      % (longest[1], A.TRAY_TIP_LIMIT))
print("   %r" % longest[0])
check("самая длинная подсказка трея влезает в предел",
      longest[1] <= A.TRAY_TIP_LIMIT,
      "%d из %d" % (longest[1], A.TRAY_TIP_LIMIT))

# Версия одна и та же везде, где её видит человек.
check("шапка сводки берёт версию из APP_VERSION",
      "APP_VERSION" in SRC.split("def write_session_summary")[1]
      .split("\n    def ")[0]
      or "APP_VERSION," in SRC)
SPEC = io.open(os.path.join(ROOT_DIR, "MouseMonitorPro.spec"),
               encoding="utf-8").read()
check("README называет ту же версию",
      "v%s" % A.APP_VERSION in README, A.APP_VERSION)
# Манифест -- это XML со своими version="1.0" и 6.0.0.0 у Common-Controls;
# к версии приложения они отношения не имеют и из проверки исключаются.
# Смотрим то, что снаружи манифеста.
outside = SPEC.split('MANIFEST = """')[0] + SPEC.split('"""')[-1]
stray = re.findall(r"\d+\.\d+(?:\.\d+)*", outside)
check("в .spec нет ЧУЖОЙ версии приложения",
      not [v for v in stray if v != A.APP_VERSION], str(stray))
check("имя EXE в .spec и в README совпадают",
      "name='MouseMonitorPro'" in SPEC and "MouseMonitorPro.exe" in README)

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
app.stop_session()
app.shutdown()
sys.exit(0 if all(ok) else 1)
