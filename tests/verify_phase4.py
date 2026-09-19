"""Проверка критериев приёмки Фазы 4."""
import csv
import math
import os
import sys
import time
import tkinter as tk

import win32api
import win32con
import win32gui

import os
import sys

# Стенд лежит в tests/, приложение -- на уровень выше.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mouse_info_app as A

ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print("  [%s] %-56s %s" % ("PASS" if cond else "FAIL", name, detail))


A.setup_logging()
A.enable_dpi_awareness()
root = tk.Tk()
root.withdraw()
A.apply_ui_scaling(root)


class FakePanel:
    pass


fp = FakePanel()
fp.root = root
# Оверлей берёт подписи из TRANSLATIONS по языку панели (Фаза 6),
# поэтому двойник обязан объявить язык, как это делает настоящая панель.
fp.current_lang = "English"
SHOW = {'pos': True, 'accel': True, 'hz': True, 'cps': True, 'faults': True}


def tracker():
    return A.FloatingTracker(fp, A.SKINS["Dark (Default)"], SHOW, alpha=0.8,
                             click_through=False, position_mode="cursor")


print("пороги: ошибка <%.0f мс, подозрение <%.0f мс, короткое нажатие <%.0f мс | tau=%.0f мс"
      % (A.DC_FAULT_GAP * 1000, A.DC_SUSPECT_GAP * 1000,
         A.DC_SHORT_PRESS * 1000, A.ACCEL_TAU * 1000))
print()

print("=== 1. осознанный быстрый клик (drag-click) не даёт DC_FAULT ===")
t = tracker()
now = 1000.0
# 12 кликов, скважность 50% при 16 кликов/с: нажатие 31 мс, пауза 31 мс
for _ in range(12):
    t.add_click("Button.left", now, True)
    now += 0.031
    t.add_click("Button.left", now, False)
    now += 0.031
print("  нажатие 31 мс, пауза 31 мс (16 кликов/с): ошибок=%d подозрений=%d"
      % (t.fault_counts['left'], t.suspect_counts['left']))
check("ложных DC_FAULT нет", t.fault_counts['left'] == 0, str(t.fault_counts['left']))
check("серия не попала и в подозрительные (пауза 31 мс > 25)",
      t.suspect_counts['left'] == 0, "подозрений: %d" % t.suspect_counts['left'])
t.destroy()

# граница, начиная с которой порог 25 мс даёт ложные срабатывания
for cps in (12, 16, 20, 24, 30):
    tt = tracker()
    n = 1000.0
    half = (1.0 / cps) / 2.0
    for _ in range(10):
        tt.add_click("Button.left", n, True); n += half
        tt.add_click("Button.left", n, False); n += half
    print("    %2d кликов/с (скважность 50%%, пауза %.0f мс): ошибок=%d подозрений=%d"
          % (cps, half * 1000, tt.fault_counts['left'], tt.suspect_counts['left']))
    tt.destroy()

print()
print("=== 2. дребезг: отпускание -> нажатие через 5 мс ===")
t = tracker()
now = 1000.0
t.add_click("Button.left", now, True)
now += 0.050
f_rel = t.add_click("Button.left", now, False)
now += 0.005                                   # дребезг: повторное замыкание
f_press = t.add_click("Button.left", now, True)
print("  отпускание -> %r | повторное нажатие через 5 мс -> %r" % (f_rel, f_press))
check("признак GAP сработал", f_press == "DC_FAULT_GAP", repr(f_press))
check("счётчик ошибок вырос", t.fault_counts['left'] == 1, str(t.fault_counts['left']))
check("счётчик подозрений не тронут", t.suspect_counts['left'] == 0)
t.destroy()

print()
print("=== 3. дребезг: аномально короткое нажатие 5 мс ===")
t = tracker()
now = 2000.0
t.add_click("Button.left", now, True)
now += 0.005
f = t.add_click("Button.left", now, False)
print("  нажатие длительностью 5 мс -> %r" % f)
check("признак SHORT сработал", f == "DC_FAULT_SHORT", repr(f))
check("счётчик ошибок вырос", t.fault_counts['left'] == 1)
check("признаки различимы", "GAP" not in (f or ""), repr(f))
t.destroy()

print()
print("=== 4. подозрительный интервал 15 мс -- отдельный счётчик ===")
t = tracker()
now = 3000.0
t.add_click("Button.left", now, True)
now += 0.050
t.add_click("Button.left", now, False)
now += 0.015
f = t.add_click("Button.left", now, True)
print("  отпускание -> нажатие через 15 мс -> %r" % f)
check("признак SUSPECT сработал", f == "DC_SUSPECT", repr(f))
check("счётчик подозрений вырос", t.suspect_counts['left'] == 1)
check("счётчик ОШИБОК не тронут", t.fault_counts['left'] == 0,
      "ошибок: %d" % t.fault_counts['left'])
t.destroy()

print()
print("=== 5. знак: разгон и торможение различаются ===")
t = tracker()
base = t.last_time          # продолжаем часы трекера, иначе dt < 0
# разгон: x = 0.5*a*t^2
a_val = 120000.0
vals_up = []
for i in range(1, 40):
    tt = i * 0.006
    t.update_data(int(0.5 * a_val * tt * tt), 500, base + tt)
    vals_up.append(t.current_accel)
accel_sign = t.current_accel
# торможение: та же траектория задом наперёд по скорости
t2 = tracker()
base2 = t2.last_time
x = 0.0
v = 3000.0
for i in range(1, 40):
    tt = i * 0.006
    v = max(0.0, 3000.0 - 120000.0 * tt)
    x += v * 0.006
    t2.update_data(int(x), 500, base2 + tt)
decel_sign = t2.current_accel
print("  разгон   -> current_accel = %+10.1f  (в UI dV: %+d)" % (accel_sign, int(accel_sign / 100)))
print("  торможение -> current_accel = %+10.1f  (в UI dV: %+d)" % (decel_sign, int(decel_sign / 100)))
check("разгон положительный", accel_sign > 0)
check("торможение отрицательное", decel_sign < 0)
check("знаки различаются", (accel_sign > 0) != (decel_sign > 0))
t.destroy(); t2.destroy()

print()
print("=== 6. сглаживание не зависит от частоты событий ===")


def time_to_63(step_dt):
    """Время выхода на 63% ступеньки new_accel: 0 -> a.

    Сначала равномерное движение (new_accel = 0, показание успокаивается),
    затем включается постоянное ускорение. Без разгонного участка первый же
    вызов даёт скачок из реальной позиции курсора в начало синтетической
    траектории и выброс, который перекрывает любой порог.
    """
    tr = tracker()
    base_t = tr.last_time
    v0 = 2000.0
    a_val = 120000.0
    x = 0.0
    tt = 0.0
    tr.last_x, tr.last_y = 0, 500      # стартуем оттуда же, где траектория

    # фаза A: равномерно, 0.4 с -- показание сходится к нулю
    while tt < 0.40:
        tt += step_dt
        x += v0 * step_dt
        tr.update_data(int(x), 500, base_t + tt)
    settled = tr.current_accel

    # фаза B: ступенька -- включаем постоянное ускорение
    t_step = tt
    v = v0
    reached = None
    while tt < t_step + 1.0:
        tt += step_dt
        v += a_val * step_dt
        x += v * step_dt
        tr.update_data(int(x), 500, base_t + tt)
        if reached is None and tr.current_accel >= 0.63 * a_val:
            reached = tt - t_step
            break
    tr.destroy()
    return reached, settled


t_fast, s_fast = time_to_63(0.006)
t_slow, s_slow = time_to_63(0.020)
print("  события каждые  6 мс: перед ступенькой %+8.1f, 63%% за %.3f с" % (s_fast, t_fast))
print("  события каждые 20 мс: перед ступенькой %+8.1f, 63%% за %.3f с" % (s_slow, t_slow))
ratio = max(t_fast, t_slow) / min(t_fast, t_slow)
old_fast = -0.006 / math.log(0.85)
old_slow = -0.020 / math.log(0.85)
print("  отношение сейчас: %.2f (tau=%.0f мс)" % (ratio, A.ACCEL_TAU * 1000))
print("  прежние 0.85/0.15 дали бы tau %.0f мс против %.0f мс, отношение %.2f"
      % (old_fast * 1000, old_slow * 1000, old_slow / old_fast))
check("постоянная времени одинакова в пределах 25%", ratio < 1.25, "%.2f" % ratio)

print()
print("=== 7. прозрачность и click-through на лету ===")
t = tracker()
t.update()
t.set_alpha(0.35)
t.update()
check("alpha применилась", abs(float(t.attributes("-alpha")) - 0.35) < 0.01,
      str(t.attributes("-alpha")))
hwnd = win32gui.GetParent(t.winfo_id())
t.set_click_through(True)
style_on = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
t.set_click_through(False)
style_off = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
check("click-through включается", bool(style_on & win32con.WS_EX_TRANSPARENT))
check("click-through ВЫключается", not (style_off & win32con.WS_EX_TRANSPARENT),
      "exstyle %s -> %s" % (hex(style_on), hex(style_off)))
check("WS_EX_LAYERED сохранён (на нём прозрачность)",
      bool(style_off & win32con.WS_EX_LAYERED))
t.destroy()

print()
print("=== 8. CSV: версия формата и колонка признака ===")
app = A.MainControlPanel(root)
root.update()
app.enable_logging.set(True)
app.toggle_tracker()
root.update()
csv_path = app.logger.filename
ts = time.perf_counter()
app.data_queue.put(("click", 10, 20, "Button.left", True, ts))
app.data_queue.put(("click", 10, 20, "Button.left", False, ts + 0.005))
app.data_queue.put(("move", 30, 40, ts + 0.02))
app.process_events()
root.update()
app.stop_session()
root.update()

with open(csv_path, encoding="utf-8", newline="") as fh:
    rows = list(csv.reader(fh))
print("  строка версии:", rows[0])
print("  шапка        :", rows[1])
for r in rows[2:]:
    print("  запись       :", r)
check("есть строка версии формата",
      rows[0] and rows[0][0].startswith("# MouseMonitorPro CSV format v"), str(rows[0]))
check("колонка Flag в шапке", "Flag" in rows[1], str(rows[1]))
check("колонка SpeedChange вместо Accel", "SpeedChange" in rows[1], str(rows[1]))
events = [r[1] for r in rows[2:]]
flags = [r[2] for r in rows[2:]]
check("пишутся и Press, и Release",
      any(e.startswith("Press_") for e in events) and any(e.startswith("Release_") for e in events),
      str(events))
check("признак DC_FAULT_SHORT виден отдельной колонкой",
      "DC_FAULT_SHORT" in flags, str(flags))
os.remove(csv_path)

print()
print("=== 9. фильтр injected на РЕАЛЬНОМ хуке ===")
start_pos = win32api.GetCursorPos()
app.injected_events = 0
app.toggle_tracker()          # старт сессии -> ставится настоящий хук
root.update()
time.sleep(0.4)
q_before = app.data_queue.qsize()
inj_before = app.injected_events
for i in range(8):
    win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, 1 if i % 2 == 0 else -1, 0, 0, 0)
    time.sleep(0.04)
time.sleep(0.4)
q_after = app.data_queue.qsize()
inj_after = app.injected_events
print("  синтетических движений подано: 8")
print("  injected_events: %d -> %d | размер очереди: %d -> %d"
      % (inj_before, inj_after, q_before, q_after))
check("синтетические события отфильтрованы", inj_after - inj_before >= 8,
      "отфильтровано %d" % (inj_after - inj_before))
check("в очередь они не попали", q_after - q_before <= 2,
      "прирост очереди %d (допуск на реальное движение мыши)" % (q_after - q_before))

# тестовый путь: прямой вызов в обход хука фильтром не режется
app.injected_events = 0
q0 = app.data_queue.qsize()
for i in range(5):
    app.on_mouse_move(700 + i, 500)
check("прямой вызов обработчика фильтром НЕ режется",
      app.data_queue.qsize() - q0 == 5 and app.injected_events == 0,
      "очередь +%d, injected=%d" % (app.data_queue.qsize() - q0, app.injected_events))

app.shutdown()
win32api.SetCursorPos(start_pos)

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
