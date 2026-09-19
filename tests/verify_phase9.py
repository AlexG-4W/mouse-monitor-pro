"""Проверка критериев приёмки Фазы 9."""
import csv
import io
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mouse_info_app as A

ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print("  [%s] %-54s %s" % ("PASS" if cond else "FAIL", name, detail))


class FakeListener:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeListener.last = self

    def start(self):
        pass

    def stop(self):
        pass


A.mouse.Listener = FakeListener
SRC = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "mouse_info_app.py"), encoding="utf-8").read()

A.setup_logging()
A.enable_dpi_awareness()
root = tk.Tk()
root.withdraw()
A.apply_ui_scaling(root)
app = A.MainControlPanel(root)
root.update()
LOGS = os.path.join(A.data_dir(), "logs")
MAPS = os.path.join(A.data_dir(), "heatmaps")


# --- 1. перезапись артефактов ------------------------------------------------
print("=== 1. две сессии в одну секунду не затирают друг друга ===")
os.makedirs(LOGS, exist_ok=True)
stem = "collision_%d" % int(time.time())
first = A.unique_path(LOGS, stem, ".csv")
io.open(first, "w", encoding="utf-8").write("first")
second = A.unique_path(LOGS, stem, ".csv")
io.open(second, "w", encoding="utf-8").write("second")
third = A.unique_path(LOGS, stem, ".csv")
check("второе имя отличается от первого", first != second,
      os.path.basename(second))
check("суффикс читаемый и сортируемый", os.path.basename(second).endswith("_2.csv"),
      os.path.basename(second))
check("третье имя тоже свободно", third not in (first, second)
      and os.path.basename(third).endswith("_3.csv"), os.path.basename(third))
check("первый файл цел", io.open(first, encoding="utf-8").read() == "first")
for path in (first, second):
    os.remove(path)

# сквозняк: две сессии подряд, гарантированно внутри одной секунды
before = set(os.listdir(LOGS))
before_maps = set(os.listdir(MAPS)) if os.path.isdir(MAPS) else set()
made = []
for run in range(2):
    app.enable_logging.set(True)
    app.enable_heatmap.set(True)
    app.toggle_tracker()
    root.update()
    for i in range(20):
        app.on_mouse_move(400 + i * 5, 300 + i * 3)
    app.process_events()
    made.append(app.logger.filename)
    app.stop_session()
    root.update()
new_csv = sorted(set(os.listdir(LOGS)) - before)
new_png = sorted((set(os.listdir(MAPS)) if os.path.isdir(MAPS) else set())
                 - before_maps)
print("   CSV: %s" % new_csv)
print("   PNG: %s" % new_png)
check("две сессии дали ДВА разных CSV", made[0] != made[1],
      "%s vs %s" % (os.path.basename(made[0]), os.path.basename(made[1])))
check("оба CSV существуют", all(os.path.isfile(x) for x in made))
check("оба CSV непустые", all(os.path.getsize(x) > 0 for x in made))
# Отбор по подстроке, а не по концу имени: суффикс столкновения встаёт ПОСЛЕ
# "_summary", и проверка на endswith("_summary.txt") ловила бы только первую.
summaries = [n for n in new_csv if "_summary" in n]
check("две сводки, а не одна", len(summaries) == 2, str(summaries))
check("две теплокарты, а не одна", len(new_png) == 2, str(new_png))
# Имена артефактов обязаны доехать до сводки: обнуление сессионного состояния
# стоит ПЕРЕД их открытием, иначе оно их затирает (найдено чтением сводки).
last_summary = os.path.join(LOGS, sorted(summaries)[-1])
summary_text = io.open(last_summary, encoding="utf-8").read()
check("в сводке названо имя CSV, а не 'not enabled'",
      ".csv" in summary_text and "csv            : not enabled" not in summary_text,
      [l for l in summary_text.splitlines() if l.startswith("csv")])
check("в сводке названо имя теплокарты",
      ".png" in summary_text,
      [l for l in summary_text.splitlines() if l.startswith("heatmap")])
check("CSV открывается в режиме 'x', а не 'w'", "mode='x'" in SRC)

# --- 2. колесо: подписка и путь события --------------------------------------
print()
print("=== 2. колесо доезжает до очереди и CSV ===")
app.enable_heatmap.set(False)
app.enable_logging.set(True)
app.toggle_tracker()
root.update()
check("on_scroll подписан у слушателя",
      "on_scroll" in getattr(FakeListener, "last").kwargs,
      str(sorted(getattr(FakeListener, "last").kwargs)))
size0 = app.data_queue.qsize()
app.on_scroll(100, 200, 0, 1)
app.on_scroll(100, 200, 0, -1)
check("тики попали в очередь", app.data_queue.qsize() - size0 == 2,
      "+%d" % (app.data_queue.qsize() - size0))
inj0 = app.injected_events
app.on_scroll(100, 200, 0, 1, True)
check("синтетический тик отфильтрован", app.injected_events - inj0 == 1)
check("и в очередь не попал", app.data_queue.qsize() - size0 == 2)
app.process_events()

base = time.perf_counter()
app.data_queue.put_nowait(("scroll", 10, 20, 0, 1, base))
app.data_queue.put_nowait(("scroll", 10, 20, 0, -1, base + 0.010))
app.data_queue.put_nowait(("scroll", 10, 20, 1, 0, base + 0.200))
app.data_queue.put_nowait(("scroll", 10, 20, 0, 0, base + 0.400))
app.process_events()
csv_path = app.logger.filename
app.stop_session()
root.update()
rows = [r for r in csv.reader(io.open(csv_path, encoding="utf-8")) if len(r) == 7]
events = [r[1] for r in rows if r[1].startswith("Scroll")]
flags = [r[2] for r in rows if r[1].startswith("Scroll")]
print("   события: %s" % events)
print("   признаки: %s" % flags)
check("Scroll_Up записан", "Scroll_Up" in events)
check("Scroll_Down записан", "Scroll_Down" in events)
check("горизонтальный тик записан отдельно", "Scroll_Right" in events)
check("тик без направления записан как Scroll_Zero", "Scroll_Zero" in events)
check("WHEEL_REVERSAL виден в колонке Flag", "WHEEL_REVERSAL" in flags)
with io.open(csv_path, encoding="utf-8") as fh:
    version = fh.readline().strip()
# Через константу и ">=", а не через прибитое "v4": подъём формата в будущем
# -- законное изменение, и ронять им стенд про колесо незачем.
check("формат CSV поднят под события колеса",
      version.endswith("v%d" % A.CSV_FORMAT_VERSION)
      and A.CSV_FORMAT_VERSION >= 4, version)
check("набор колонок не менялся",
      rows[0] == ["Timestamp", "Event", "Flag", "X", "Y", "Hz", "SpeedChange"],
      str(rows[0]))

# --- 3. детектор реверса ------------------------------------------------------
print()
print("=== 3. детектор обратного тика ===")
tracker = A.FloatingTracker(app, A.SKINS["Dark (Default)"],
                            {'pos': True, 'accel': True, 'hz': True,
                             'cps': True, 'faults': True})


def scroll_series(events):
    tracker.wheel_ticks = tracker.wheel_zeros = tracker.wheel_reversals = 0
    tracker.last_wheel_dir = 0
    tracker.last_wheel_time = -1e9
    return [tracker.add_scroll(dx, dy, t) for t, dx, dy in events]


flags = scroll_series([(1.0, 0, -1), (1.02, 0, -1), (1.03, 0, 1),
                       (1.04, 0, -1)])
check("обратный тик внутри порога -> WHEEL_REVERSAL",
      tracker.wheel_reversals == 2, "реверсов %d, флаги %s"
      % (tracker.wheel_reversals, [f or "-" for f in flags]))

scroll_series([(1.0, 0, -1), (1.1, 0, -1), (1.2, 0, -1)])
check("ровная прокрутка -- ноль реверсов", tracker.wheel_reversals == 0)

scroll_series([(1.0, 0, -1), (1.5, 0, 1)])
check("осознанная смена направления через 500 мс -- не реверс",
      tracker.wheel_reversals == 0)

scroll_series([(1.0, 0, 0), (1.01, 0, 0), (1.02, 0, 0)])
check("тики без направления не считаются реверсами",
      tracker.wheel_reversals == 0 and tracker.wheel_zeros == 3,
      "нулевых %d" % tracker.wheel_zeros)

scroll_series([(1.0, 1, 0), (1.01, -1, 0)])
check("горизонтальные тики не нулевые и не реверсы",
      tracker.wheel_zeros == 0 and tracker.wheel_reversals == 0,
      "нулевых %d" % tracker.wheel_zeros)

scroll_series([(1.0, 0, -1), (1.01, 0, 0), (1.02, 0, 1)])
check("нулевой тик не рвёт вертикальную историю",
      tracker.wheel_reversals == 1, "реверсов %d" % tracker.wheel_reversals)
tracker.destroy()

# --- 4. dy == 0 систематически: счёт объявляется недоступным ------------------
print()
print("=== 4. колесо высокого разрешения -- счёт НЕДОСТУПЕН, а не молчание ===")
check("ниже порога доли нулей -- счёт годен",
      A.wheel_health(20, 2, 3)["state"] == A.WHEEL_OK,
      "доля %.0f%%" % (A.wheel_health(20, 2, 3)["zero_share"] * 100))
bad = A.wheel_health(20, 15, 3)
check("выше порога -- WHEEL_UNUSABLE", bad["state"] == A.WHEEL_UNUSABLE,
      "доля %.0f%%" % (bad["zero_share"] * 100))
check("все нули -- WHEEL_UNUSABLE",
      A.wheel_health(10, 10, 0)["state"] == A.WHEEL_UNUSABLE)
check("прокрутки не было -- WHEEL_NONE",
      A.wheel_health(0, 0, 0)["state"] == A.WHEEL_NONE)
check("мало тиков -- не WHEEL_OK",
      A.wheel_health(A.WHEEL_MIN_TICKS - 1, 0, 0)["state"] != A.WHEEL_OK)
body = SRC.split("def wheel_health")[1].split("\ndef ")[0]
check("решение о годности -- в одном месте",
      SRC.count("WHEEL_ZERO_SHARE") == 2 and "WHEEL_ZERO_SHARE" in body,
      "вхождений константы: %d" % SRC.count("WHEEL_ZERO_SHARE"))
check("состояние присваивается только там",
      SRC.count('out["state"] = WHEEL') == body.count('out["state"] = WHEEL'),
      "%d присваиваний" % SRC.count('out["state"] = WHEEL'))

app.enable_logging.set(False)
app.toggle_tracker()
root.update()
for i in range(12):
    app.data_queue.put_nowait(("scroll", 5, 5, 0, 0, time.perf_counter()))
app.process_events()
line = app.wheel_line()
print("   строка при сплошных нулях: %r" % line)
check("строка говорит о недоступности, а не о нуле реверсов",
      line == A.TRANSLATIONS[app.current_lang]["wheel_unusable"], line)
check("числа в строке нет", not any(ch.isdigit() for ch in line))
seen_before = set(os.listdir(LOGS))
app.stop_session()
root.update()
# Свою сводку берём по РАЗНИЦЕ каталога, а не по имени: имена в стенде
# сталкиваются (все сессии внутри одной секунды), и выбор по имени промахивался.
fresh = [n for n in set(os.listdir(LOGS)) - seen_before if "_summary" in n]
check("сводка сессии создана", len(fresh) == 1, str(fresh))
text = (io.open(os.path.join(LOGS, fresh[0]), encoding="utf-8").read()
        if fresh else "")
check("сводка объявляет счёт недоступным", "reversals      : NOT AVAILABLE" in text)
check("сводка объясняет причину", "integer division" in text
      and "free-spin" in text)

# --- 5. UI: одна строка на двоих ---------------------------------------------
print()
print("=== 5. слот статуса: потери важнее колеса, высота не растёт ===")
# Слот пересчитывается в цикле 10 мс; после stop_session тик может ещё не
# наступить, поэтому прокручиваем его явно, а не полагаемся на root.update().
app.update_live_labels()
root.update_idletasks()
root.update()
# С фазы 12 потолка нет: размер окна задаёт содержимое. Проверяем, что
# minsize вмещает содержимое, а не что оно влезло в зашитое число.
def fits():
    return (root.minsize()[1] >= app.frame.winfo_reqheight()
            and root.minsize()[0] >= app.frame.winfo_reqwidth())


check("вне сессии условной строки нет", app.slot_shows is None,
      str(app.slot_shows))
check("вне сессии содержимое помещается", fits(),
      "minsize %s, требуется %dx%d" % (root.minsize(),
                                       app.frame.winfo_reqwidth(),
                                       app.frame.winfo_reqheight()))

app.toggle_tracker()
root.update()
app.update_live_labels()
root.update_idletasks()
root.update()
# С фазы 12 строка колеса ВЕРНУЛАСЬ в панель постоянной строкой: потолок
# высоты снят, бороться за место больше не нужно.
check("строка колеса живёт в панели",
      app.wheel_label.winfo_manager() == "pack", app.wheel_label.winfo_manager())
check("в сессии условной строки по-прежнему нет", app.slot_shows is None,
      str(app.slot_shows))
check("в сессии содержимое помещается", fits(),
      "minsize %s" % (root.minsize(),))

app.dropped_events = 7
app.update_live_labels()
root.update_idletasks()
root.update()
check("при потерях появляется условная строка", app.slot_shows == "dropped",
      str(app.slot_shows))
check("при потерях содержимое всё ещё помещается", fits(),
      "minsize %s, требуется %d" % (root.minsize(),
                                    app.frame.winfo_reqheight()))
check("текст счётчика потерь верен всегда",
      "7" in app.dropped_label.cget("text"), app.dropped_label.cget("text"))
app.dropped_events = 0
app.update_live_labels()
check("потери ушли -- условная строка убралась", app.slot_shows is None)
app.stop_session()
root.update()

# --- 6. локализация -----------------------------------------------------------
print()
print("=== 6. локализация состояний колеса ===")
for lang in ("English", "Русский"):
    app.lang_var.set(lang)
    app.setup_ui()
    for key in ("wheel_ok", "wheel_none", "wheel_unusable"):
        check("%s: ключ %s есть" % (lang, key), key in A.TRANSLATIONS[lang])
    check("%s: состояния различаются" % lang,
          len({A.TRANSLATIONS[lang][k] for k in
               ("wheel_ok", "wheel_none", "wheel_unusable")}) == 3)
app.lang_var.set("English")
app.setup_ui()

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
app.shutdown()
sys.exit(0 if all(ok) else 1)
