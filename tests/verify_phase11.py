"""Проверка критериев приёмки Фазы 11."""
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
        pass

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


# --- 1. привязка к отраслевой шкале -------------------------------------------
print("=== 1. ступень называется только при уверенном попадании ===")
for step in A.POLLING_STEPS:
    period = 1000.0 / step
    got, verdict = A.polling_step(period)
    resolvable = period * A.RATE_STEP_TOLERANCE >= A.RATE_BIN * 1000.0 / 2.0
    if resolvable:
        check("точная ступень %d Гц опознана" % step,
              got == step and verdict == A.STEP_OK, "%s %s" % (verdict, got))
    else:
        check("ступень %d Гц объявлена неразличимой" % step,
              verdict == A.STEP_TOO_FINE, verdict)

edge_in = 1.0 * (1.0 - A.RATE_STEP_TOLERANCE) + 0.001
edge_out = 1.0 * (1.0 - A.RATE_STEP_TOLERANCE) - 0.001
check("на краю допуска ступень ещё опознаётся",
      A.polling_step(edge_in)[0] == 1000, "%.3f мс" % edge_in)
check("за краем допуска -- уже нет",
      A.polling_step(edge_out)[1] == A.STEP_BETWEEN, "%.3f мс" % edge_out)

mid = (1.0 + 0.5) / 2.0
got, verdict = A.polling_step(mid)
check("середина промежутка 1000..2000 -> между ступенями",
      got is None and verdict == A.STEP_BETWEEN, "%.2f мс -> %s" % (mid, verdict))
check("посередине ступень НЕ подгоняется", got is None)

check("4000 Гц объявлен неразличимым",
      A.polling_step(1000.0 / 4000)[1] == A.STEP_TOO_FINE)
check("8000 Гц объявлен неразличимым",
      A.polling_step(1000.0 / 8000)[1] == A.STEP_TOO_FINE)
check("нулевой период не даёт ступени", A.polling_step(0)[0] is None)

print()
print("=== 2. допуск обоснован числом, а не подобран ===")
half_bin = A.RATE_BIN * 1000.0 / 2.0
bin_at_1000 = A.RATE_BIN * 1000.0 / 1.0
check("допуск не меньше ширины корзины на 1000 Гц",
      A.RATE_STEP_TOLERANCE >= bin_at_1000,
      "допуск %.2f, корзина %.2f периода" % (A.RATE_STEP_TOLERANCE, bin_at_1000))
check("допуск сильно меньше расстояния между ступенями",
      A.RATE_STEP_TOLERANCE < 0.25,
      "середина промежутка -- 25%% ниже верхней ступени")
# Срез по границе ФУНКЦИИ: деление по первой пустой строке попадало внутрь
# строки документации и проверяло не тело.
step_body = SRC.split("def polling_step")[1].split("\ndef ")[0]
check("граница различимости выводится из корзины",
      "RATE_BIN" in step_body, "полукорзина %.3f мс" % half_bin)

# --- 3. приоритет состояний из фазы 8 сохранён ---------------------------------
print()
print("=== 3. нет годных данных -- нет и ступени ===")
for state in (A.RATE_SLOW, A.RATE_UNSURE):
    app.rate_estimate = {"state": state, "period_ms": None, "hz": None,
                         "mode_share": 0.0, "samples": 0, "rate": 5.0,
                         "ladder": []}
    line = app.rate_line()
    check("состояние %s: числа нет" % state,
          not any(ch.isdigit() for ch in line), line)
    check("состояние %s: ступени нет" % state,
          not any(str(x) in line for x in A.POLLING_STEPS), line)

app.rate_estimate = {"state": A.RATE_OK, "period_ms": 1.00, "hz": 1000.0,
                     "mode_share": 0.3, "samples": 600, "rate": 900.0,
                     "ladder": []}
line_step = app.rate_line()
app.rate_estimate = {"state": A.RATE_OK, "period_ms": 0.75, "hz": 1333.0,
                     "mode_share": 0.3, "samples": 600, "rate": 900.0,
                     "ladder": []}
line_between = app.rate_line()
print("   %r" % line_step)
print("   %r" % line_between)
check("попадание: ступень названа", "1000" in line_step)
check("промах: ступень НЕ названа",
      "2000" not in line_between and "standard 1000" not in line_between,
      line_between)
check("промах назван словами", line_between != line_step)
app.rate_estimate = None

# --- 4. распределение dV, без выдуманных норм ----------------------------------
print()
print("=== 4. dV: распределение вместо нормы ===")
app.enable_logging.set(False)
app.enable_heatmap.set(False)
app.toggle_tracker()
root.update()
base = time.perf_counter()
for i in range(400):
    app.data_queue.put_nowait(("move", 300 + (i * 13) % 700,
                               200 + (i * 7) % 400, base + i * 0.008))
app.process_events()
app.update_live_labels()
samples = app.tracker.dv_samples
check("выборка dV собрана", len(samples) > 50, "%d" % len(samples))
check("значения неотрицательные", all(v >= 0 for v in samples))
ordered = sorted(samples)
check("медиана не больше 90-го процентиля",
      A.percentile(ordered, 0.5) <= A.percentile(ordered, 0.9),
      "%d <= %d" % (A.percentile(ordered, 0.5), A.percentile(ordered, 0.9)))
check("90-й процентиль не больше пика",
      A.percentile(ordered, 0.9) <= ordered[-1])

before = set(os.listdir(LOGS))
app.stop_session()
root.update()
fresh = [n for n in set(os.listdir(LOGS)) - before if "_summary" in n]
text = io.open(os.path.join(LOGS, fresh[0]), encoding="utf-8").read() if fresh else ""
dv_block = text.split("CURSOR SPEED CHANGE")[1].split("BUTTONS")[0] if text else ""
check("раздел dV есть", "CURSOR SPEED CHANGE" in text)
check("величина названа относительной", "RELATIVE" in dv_block)
check("сказано, что нормы нет", "no industry" in dv_block
      and "None is invented" in dv_block)
check("даны медиана, процентиль и пик",
      "median |dV|" in dv_block and "90th percentile" in dv_block
      and "peak |dV|" in dv_block)
for word in ("normal range", "recommended", "good", "bad"):
    check("нет выдуманной нормы: %r" % word, word not in dv_block.lower(),
          word)

print()
print("=== 5. прореживание держит память и покрытие ===")
tracker = A.FloatingTracker(app, A.SKINS["Dark (Default)"],
                            {'pos': True, 'accel': True, 'hz': True,
                             'cps': True, 'faults': True})
for i in range(A.DV_SAMPLE_CAP * 3):
    tracker.record_dv(i)
check("выборка ограничена потолком", len(tracker.dv_samples) <= A.DV_SAMPLE_CAP,
      "%d при потолке %d" % (len(tracker.dv_samples), A.DV_SAMPLE_CAP))
check("шаг прореживания вырос", tracker.dv_step > 1, "шаг %d" % tracker.dv_step)
check("покрыт весь диапазон, а не начало",
      tracker.dv_samples[-1] > A.DV_SAMPLE_CAP * 2,
      "последнее значение %d" % tracker.dv_samples[-1])

# --- 6. двойной клик против системных правил -----------------------------------
print()
print("=== 6. двойной клик: сопоставление с системными правилами ===")
gap_ms, box_w, box_h = A.double_click_limits()
print("   система: порог %d мс, прямоугольник %dx%d px" % (gap_ms, box_w, box_h))
check("порог прочитан и правдоподобен", 100 <= gap_ms <= 5000, gap_ms)
check("прямоугольник прочитан", box_w >= 1 and box_h >= 1,
      "%dx%d" % (box_w, box_h))

tracker.dblclk_pairs = []
tracker.last_press_times["left"] = -1e9
tracker.last_press_pos["left"] = None
now = 100.0
tracker.add_click("Button.left", now, True, 500, 400)
tracker.add_click("Button.left", now + 0.05, False, 500, 400)
tracker.add_click("Button.left", now + 0.10, True, 501, 400)
check("пара с предыдущим нажатием записана", len(tracker.dblclk_pairs) == 1,
      str(tracker.dblclk_pairs))
delta, dx, dy = tracker.dblclk_pairs[0]
check("интервал измерен верно", abs(delta - 0.10) < 0.001, "%.3f с" % delta)
check("смещение измерено верно", dx == 1 and dy == 0, "%d,%d" % (dx, dy))

tracker.add_click("Button.left", now + 0.20, False, 501, 400)
tracker.add_click("Button.left", now + 0.30, True, 501 + box_w + 20, 400)
far = tracker.dblclk_pairs[-1]
check("далёкая пара записана, но вне прямоугольника",
      far[1] > box_w, "смещение %d при пределе %d" % (far[1], box_w))
tracker.destroy()

print()
print("=== 7. формулировки: правила, а не вердикт ===")


def feed_pairs():
    now = time.perf_counter()
    for i in range(3):
        base_t = now + i * 0.5
        app.data_queue.put_nowait(("click", 700, 500, "Button.left", True, base_t))
        app.data_queue.put_nowait(("click", 700, 500, "Button.left", False,
                                   base_t + 0.02))
        app.data_queue.put_nowait(("click", 701, 500, "Button.left", True,
                                   base_t + 0.09))
        app.data_queue.put_nowait(("click", 701, 500, "Button.left", False,
                                   base_t + 0.11))


app.toggle_tracker()
root.update()
feed_pairs()
app.process_events()
app.update_live_labels()
before = set(os.listdir(LOGS))
app.stop_session()
root.update()
fresh = [n for n in set(os.listdir(LOGS)) - before if "_summary" in n]
dbl = io.open(os.path.join(LOGS, fresh[0]), encoding="utf-8").read() if fresh else ""
block = dbl.split("double-click vs system rules")[1].split("SCROLL WHEEL")[0] \
    if "double-click vs system rules" in dbl else ""
print("   пар в сводке: %s"
      % [l.strip() for l in block.split("\n") if "pairs" in l])
check("раздел двойного клика есть", "double-click vs system rules" in dbl)
check("пары посчитаны", "same-button pairs" in block)
check("формулировка -- удовлетворяет правилам",
      "satisfy the rules" in block)
check("НЕ утверждается, что был засчитан двойным",
      "was a double" not in block.lower()
      and "treated as a double" not in block.lower()
      or "its own decision" in block)
check("сказано, что намерение не наблюдаемо",
      "Intent is not observable" in block)
check("названы источники значений",
      "GetDoubleClickTime" in block and "SM_CXDOUBLECLK" in block)
check("отличие от значения по умолчанию отмечено",
      ("Windows default is" in block) == (gap_ms != A.WIN_DEFAULT_DOUBLECLICK_MS),
      "порог %d, дефолт %d" % (gap_ms, A.WIN_DEFAULT_DOUBLECLICK_MS))

print()
print("=== 8. системные эталоны со шкалой ===")
pointer = dbl.split("POINTER SETTINGS")[1].split("FILES")[0] if dbl else ""
check("скорость показана со шкалой", "on the 1..20 slider" in pointer, pointer[:60])
check("отметка про значение по умолчанию соответствует факту",
      ("(Windows default)" in pointer)
      == (app.sys_speed == A.WIN_DEFAULT_POINTER_SPEED),
      "скорость %s" % app.sys_speed)
check("EPP объяснён как условие линейности",
      "condition for" in pointer or "distorted" in pointer,
      [l.strip() for l in pointer.split("\n") if "enhanced" in l])

print()
print("=== 9. UI: приоритет частоте, окно не выросло ===")
# Слот пересчитывается в цикле 10 мс; после stop_session тик может ещё не
# наступить. Прокручиваем явно, как это делает боевой after(10).
app.update_live_labels()
root.update_idletasks()
root.update()
# С фазы 12 показание частоты -- постоянная строка панели, потолка высоты нет.
check("строка периода живёт в панели постоянно",
      app.rate_label.winfo_manager() == "pack", app.rate_label.winfo_manager())
check("вне сессии условной строки нет", app.slot_shows is None,
      str(app.slot_shows))
app.toggle_tracker()
root.update()
app.update_live_labels()
root.update_idletasks()
root.update()
check("в сессии содержимое помещается",
      root.minsize()[1] >= app.frame.winfo_reqheight(),
      "minsize %d, требуется %d" % (root.minsize()[1],
                                    app.frame.winfo_reqheight()))
check("показание частоты видно в панели",
      app.rate_label.cget("text") == app.rate_line(),
      app.rate_label.cget("text"))
app.dropped_events = 3
app.update_live_labels()
root.update_idletasks()
check("потери показываются отдельной строкой", app.slot_shows == "dropped")
check("и содержимое всё ещё помещается",
      root.minsize()[1] >= app.frame.winfo_reqheight())
app.dropped_events = 0
app.update_live_labels()
check("потери ушли -- строка убралась", app.slot_shows is None)
app.stop_session()
root.update()

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
app.shutdown()
sys.exit(0 if all(ok) else 1)
