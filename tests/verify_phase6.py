"""Проверка критериев приёмки Фазы 6."""
import ast
import csv
import glob
import io
import os
import re
import sys
import time
import tkinter as tk
import tkinter.font as tkfont

# Стенд лежит в tests/, приложение -- на уровень выше.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mouse_info_app as A

ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print("  [%s] %-54s %s" % ("PASS" if cond else "FAIL", name, detail))


class FakeListener:
    """Хук не ставим: стенд не должен ловить настоящую мышь."""

    def __init__(self, **kwargs):
        pass

    def start(self):
        pass

    def stop(self):
        pass


A.mouse.Listener = FakeListener

A.setup_logging()
A.enable_dpi_awareness()
root = tk.Tk()
root.withdraw()
A.apply_ui_scaling(root)
app = A.MainControlPanel(root)
root.update()


# --- 1. дребезг: один эпизод -- одна единица -------------------------------
print("=== 1. счётчик дребезга считает эпизоды, а не признаки ===")
tracker = A.FloatingTracker(app, A.SKINS["Dark (Default)"],
                            {'pos': True, 'accel': True, 'hz': True,
                             'cps': True, 'faults': True})


def episode(events):
    tracker.fault_counts["left"] = 0
    tracker.suspect_counts["left"] = 0
    tracker.last_press_times["left"] = -1e9
    tracker.last_release_times["left"] = -1e9
    tracker.press_flags["left"] = ""
    flags = [tracker.add_click("Button.left", t, p) for t, p in events]
    return flags, tracker.fault_counts["left"], tracker.suspect_counts["left"]


# канонический отскок: отпустил -> 3 мс -> замкнул на 4 мс -> отпустил
flags, faults, suspects = episode([(1.000, True), (1.050, False),
                                   (1.053, True), (1.057, False)])
print("  канонический отскок -> флаги %s" % flags)
check("канонический отскок: счётчик +1, а не +2", faults == 1,
      "fault_counts=%d" % faults)
both = A.DC_FLAG_SEP.join(("DC_FAULT_GAP", "DC_FAULT_SHORT"))
check("во Flag видны ОБА признака", both in flags, repr(both))
check("оба признака в одной ячейке, через разделитель",
      any(A.DC_FLAG_SEP in f for f in flags), repr(A.DC_FLAG_SEP))
check("информация о GAP не потеряна", any(f == "DC_FAULT_GAP" for f in flags))

flags, faults, _ = episode([(1.000, True), (1.050, False)])
check("обычный клик 50 мс -- не ошибка", faults == 0, "fault_counts=%d" % faults)

flags, faults, _ = episode([(1.000, True), (1.005, False)])
check("одиночное короткое нажатие 5 мс: +1", faults == 1 and
      flags[-1] == "DC_FAULT_SHORT", "%s fault_counts=%d" % (flags, faults))

flags, faults, suspects = episode([(1.000, True), (1.050, False),
                                   (1.070, True), (1.075, False)])
check("подозрительная пауза + короткое нажатие: +1 ошибка",
      faults == 1 and suspects == 1, "%s ошибок=%d подозр.=%d"
      % (flags[-1], faults, suspects))

flags, faults, _ = episode([(1.000, True), (1.050, False),
                            (1.053, True), (1.057, False),
                            (1.060, True), (1.064, False)])
check("два отскока подряд считаются как два", faults == 2,
      "fault_counts=%d" % faults)

flags, faults, _ = episode([(1.000, False)])
check("отпускание без нажатия ошибкой не считается", faults == 0,
      "%s" % flags)
tracker.destroy()


# --- 2. dV: одно число для экрана и для CSV --------------------------------
print()
print("=== 2. SpeedChange в CSV == dV на экране ===")
check("dv_index -- единая точка масштабирования", A.dv_index(44639.9) == 446,
      "dv_index(44639.9)=%d" % A.dv_index(44639.9))
check("делитель вынесен в константу", A.DV_SCALE == 100, "DV_SCALE=%d" % A.DV_SCALE)

app.enable_logging.set(True)
app.enable_heatmap.set(False)
app.toggle_tracker()
root.update()
x = y = 500
for i in range(30):
    x += 20 + i * 4
    y += 10
    app.on_mouse_move(x, y)
    time.sleep(0.008)
    app.process_events()
on_screen = app.tracker.labels['accel'].cget("text")
expected = A.dv_index(app.tracker.current_accel)
csv_path = app.logger.filename
app.stop_session()
root.update()

rows = [r for r in csv.reader(io.open(csv_path, encoding="utf-8"))
        if len(r) == 7 and r[1] == "Move"]
last_csv = int(rows[-1][6])
print("  на оверлее %r | последнее SpeedChange в CSV %d" % (on_screen, last_csv))
check("порядок величины совпал (не 100x)", abs(last_csv) < 10000,
      "было бы ~%d при старом масштабе" % (last_csv * 100))
check("число на оверлее -- это dv_index(current_accel)",
      str(expected) in on_screen, "%r содержит %d" % (on_screen, expected))
with io.open(csv_path, encoding="utf-8") as fh:
    version_line = fh.readline().strip()
check("версия формата CSV поднята", version_line.endswith("v%d" % A.CSV_FORMAT_VERSION)
      and A.CSV_FORMAT_VERSION >= 3, version_line)


# --- 3. is_active теплокарты снимается на всех исходах ---------------------
print()
print("=== 3. HeatmapManager.save() не оставляет карту активной ===")
hm = A.HeatmapManager()
hm.start()
res = hm.save()
check("пустые данные: save() вернул None", res is None, repr(res))
check("пустые данные: is_active снят", hm.is_active is False,
      "is_active=%s" % hm.is_active)

hm.start()
hm.update(10, 10)
_orig_new = A.Image.new


def boom(*a, **k):
    raise OSError("носитель отвалился (имитация)")


A.Image.new = boom
res = hm.save()
A.Image.new = _orig_new
check("ветка except: save() вернул None", res is None, repr(res))
check("ветка except: is_active снят", hm.is_active is False,
      "is_active=%s" % hm.is_active)

hdir = os.path.join(A.data_dir(), "heatmaps")
before = set(glob.glob(os.path.join(hdir, "*.png"))) if os.path.isdir(hdir) else set()
app.enable_logging.set(False)
app.enable_heatmap.set(True)
app.toggle_tracker()            # сессия 1: галочка ВКЛ, ни одного движения
root.update()
app.stop_session()
root.update()
check("сессия с галочкой и нулём движений: карта не осталась активной",
      app.heatmap.is_active is False, "is_active=%s" % app.heatmap.is_active)

app.enable_heatmap.set(False)
app.toggle_tracker()            # сессия 2: галочка ВЫКЛ
root.update()
for i in range(50):
    app.on_mouse_move(300 + i * 5, 300 + i * 5)
app.process_events()
cells = len(app.heatmap.data)
app.stop_session()
root.update()
after = set(glob.glob(os.path.join(hdir, "*.png")))
check("при выключенной галочке ячейки не копятся", cells == 0, "ячеек=%d" % cells)
check("при выключенной галочке PNG не создан", after == before,
      "новых файлов: %d" % len(after - before))


# --- 4. current_hz гаснет вместе с tracker.hz ------------------------------
print()
print("=== 4. показание частоты спадает к нулю ===")
app.enable_heatmap.set(False)
app.toggle_tracker()
root.update()
for i in range(30):
    app.on_mouse_move(500 + i, 500 + i)
    time.sleep(0.005)
app.process_events()
app.update_live_labels()
hot = app.current_hz
check("во время движения current_hz не ноль", hot > 0, "current_hz=%d" % hot)

t0 = time.perf_counter()
while time.perf_counter() - t0 < 1.5:
    app.process_events()
    app.update_live_labels()
    root.update()
    time.sleep(0.01)
check("после 1.5 с покоя current_hz спал до нуля", app.current_hz == 0,
      "current_hz=%d (было %d)" % (app.current_hz, hot))
check("метка панели тоже нулевая", "0" in app.hz_label.cget("text"),
      repr(app.hz_label.cget("text")))

for i in range(10):
    app.on_mouse_move(700 + i, 700 + i)
app.process_events()
app.update_live_labels()
app.stop_session()
app.update_live_labels()
root.update()
check("после СТОП current_hz обнулён (иконка трея вернётся к нулю)",
      app.current_hz == 0, "current_hz=%d" % app.current_hz)


# --- 5. счётчики -- за сессию -----------------------------------------------
print()
print("=== 5. dropped_events и injected_events сбрасываются на старте ===")
app.toggle_tracker()
root.update()
for i in range(A.EVENT_QUEUE_MAXSIZE + 300):
    app.on_mouse_move(i % 1000, i % 1000)
app.on_click(1, 1, "Button.left", True, True)
first_dropped, first_injected = app.dropped_events, app.injected_events
app.stop_session()
root.update()
print("  сессия 1: dropped=%d injected=%d" % (first_dropped, first_injected))
check("сессия 1 действительно набрала потери", first_dropped == 300,
      "dropped=%d" % first_dropped)
check("сессия 1 отфильтровала синтетическое", first_injected == 1,
      "injected=%d" % first_injected)

app.toggle_tracker()
root.update()
check("на старте сессии 2 dropped обнулён", app.dropped_events == 0,
      "dropped=%d" % app.dropped_events)
check("на старте сессии 2 injected обнулён", app.injected_events == 0,
      "injected=%d" % app.injected_events)
app.update_live_labels()
check("метка потерь в UI показывает ноль", "0" in app.dropped_label.cget("text"),
      repr(app.dropped_label.cget("text")))
app.stop_session()
root.update()


src = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "mouse_info_app.py"), encoding="utf-8").read()

print()
print("=== 6. SessionLogger.start() не бросает наружу ===")
logger = A.SessionLogger()
_orig_makedirs = A.os.makedirs


def boom_makedirs(*a, **k):
    raise OSError("диск заполнен (имитация)")


A.os.makedirs = boom_makedirs
try:
    res = logger.start()
    raised = False
except OSError:
    res = "ИСКЛЮЧЕНИЕ"
    raised = True
finally:
    A.os.makedirs = _orig_makedirs
check("OSError не уходит в обработчик кнопки", not raised, repr(res))
check("start() вернул None", res is None, repr(res))
check("логгер остался неактивным", logger.is_active is False)
check("отказ виден пользователю отдельным ключом",
      "log_failed" in A.TRANSLATIONS["English"] and
      "log_failed" in A.TRANSLATIONS["Русский"])

print()
print("=== 7. ui_elements удалён ===")
check("ui_elements не осталось в исходнике", "ui_elements" not in src)

print()
print("=== 8. monitor_dpi: типы проставлены ===")
fn = src.split("def monitor_dpi")[1].split("\ndef ")[0]
for name in ("GetDpiForWindow", "MonitorFromPoint", "GetDpiForMonitor",
             "GetDC", "GetDeviceCaps"):
    check("%s имеет argtypes" % name, "%s.argtypes" % name in fn)
check("monitor_dpi по-прежнему возвращает реальный DPI",
      A.monitor_dpi(root.winfo_id()) >= 96, A.monitor_dpi(root.winfo_id()))

print()
print("=== 9. локализация оверлея ===")
tree = ast.parse(src)
tr = None
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "TRANSLATIONS":
        tr = ast.literal_eval(node.value)
sets = {lang: set(d) for lang, d in tr.items()}
en, ru = sets["English"], sets["Русский"]
check("наборы ключей идентичны", en == ru,
      "English %d, Русский %d" % (len(en), len(ru)))
ov_keys = {"ov_pos", "ov_accel", "ov_hz", "ov_cps", "ov_faults"}
check("ключи оверлея есть в обоих словарях", ov_keys <= en and ov_keys <= ru,
      ", ".join(sorted(ov_keys)))
check("подпись частоты действительно переведена",
      tr["English"]["ov_hz"] != tr["Русский"]["ov_hz"],
      "%r -> %r" % (tr["English"]["ov_hz"], tr["Русский"]["ov_hz"]))
used = set(re.findall(r'''t\[["']([a-z_0-9]+)["']\]''', src))
used |= {k for k in en if k.startswith("pos_")}
# С фазы 12 подписи чекбоксов берутся в цикле как t[key], и регулярка их не
# видит. Ключ считается потреблённым и тогда, когда встречается литералом ВНЕ
# словаря переводов: сам словарь из поиска вырезан, иначе засчитывалось бы его
# собственное определение.
_ts = src.index("TRANSLATIONS = {")
_te = src.index("class HeatmapManager")
outside = src[:_ts] + src[_te:]
used |= {k for k in en if (chr(34) + k + chr(34)) in outside}
check("у каждого ключа есть потребитель", not (en - used),
      "без потребителя: %s" % sorted(en - used))
check("захардкоженного текста в UI не осталось",
      not re.findall(r'text="[A-Za-z]', src))

# ширина оверлея не изменилась и русская подпись в неё влезает
font = tkfont.Font(root=root, font=("Consolas", 9, "bold"))
width = A.px(115)
widest = max(font.measure(s) for s in (
    tr["Русский"]["ov_hz"].format(1000),
    tr["Русский"]["ov_pos"].format(-1920, -1080),
    tr["Русский"]["ov_accel"].format(-1234),
    tr["Русский"]["ov_cps"].format(99),
    tr["Русский"]["ov_faults"].format(99, 99)))
check("ширина оверлея осталась px(115)", width == A.px(115), "%d физ." % width)
check("самая длинная русская строка влезает", widest <= width,
      "%d из %d физ." % (widest, width))

for lang in ("English", "Русский"):
    app_lang = A.TRANSLATIONS[lang]
    check("%s: подписи оверлея непустые" % lang,
          all(app_lang[k] for k in ov_keys))

# --- 10. путь трея: цикл не работает после root.destroy() -------------------
# ИДЁТ ПОСЛЕДНИМ: проверка уничтожает корневое окно.
print()
print("=== 10. цикл не работает после root.destroy() (путь трея) ===")
body = src.split("def process_queue_loop")[1].split("def process_events")[0]
check("shutting_down проверяется дважды", body.count("self.shutting_down") == 2,
      "проверок в теле цикла: %d" % body.count("self.shutting_down"))
check("проверка стоит ПОСЛЕ run_thread_commands",
      body.index("run_thread_commands") < body.rindex("self.shutting_down")
      < body.index("self.process_events"))

after_destroy = []
_orig_process_events = app.process_events


def spy_process_events():
    if app.shutting_down:
        after_destroy.append("process_events")
    return _orig_process_events()


app.process_events = spy_process_events
app.request_shutdown()          # ровно то, что делает пункт меню трея
for _ in range(3):
    try:
        root.update()
    except tk.TclError:
        break
    time.sleep(0.02)
check("после destroy цикл к Tk больше не возвращается", not after_destroy,
      "лишних проходов: %d" % len(after_destroy))
check("shutdown идемпотентен", app.shutting_down is True)
app.shutdown()

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
