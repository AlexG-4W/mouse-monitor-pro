"""Проверка критериев приёмки Фазы 3.5."""
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
    print("  [%s] %-54s %s" % ("PASS" if cond else "FAIL", name, detail))


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


def make(mode):
    return A.FloatingTracker(fp, A.SKINS["Dark (Default)"], SHOW,
                             alpha=0.8, click_through=False, position_mode=mode)


def count_geometry(tracker, events=200):
    """Считает РЕАЛЬНЫЕ вызовы geometry(), подменяя метод экземпляра."""
    calls = {"n": 0}
    real = tracker.geometry

    def counting(*a, **kw):
        if a or kw:
            calls["n"] += 1
        return real(*a, **kw)

    tracker.geometry = counting
    # Продолжаем от собственных часов трекера: если начать от perf_counter(),
    # после предыдущего прогона last_time окажется "в будущем", dt выйдет
    # отрицательным и вентиль dt > 0.005 отсечёт все события.
    base = max(time.perf_counter(), tracker.last_time + 0.01)
    for i in range(events):
        # шаг 10 мс: заведомо больше вентиля dt > 0.005 в update_data
        tracker.update_data(600 + (i % 300), 400 + (i % 200), base + i * 0.01)
    tracker.geometry = real
    return calls["n"]


work = A.work_area_at(*win32api.GetCursorPos())
print("рабочая область текущего монитора:", work, "| UI_SCALE =", A.UI_SCALE)
print("ширина оверлея px(115) =", A.px(115), "| отступ px(8) =", A.px(A.PINNED_MARGIN))
print()

print("=== 1. режим 'за курсором' не изменился ===")
t = make("cursor")
t.update()
n = count_geometry(t)
check("geometry() вызывается на каждое движение", n == 200, "вызовов: %d из 200" % n)
t.update_data(900, 700, time.perf_counter() + 10)
t.update_idletasks()
geo = t.geometry().split("+")
check("окно = курсор + offset", (int(geo[1]), int(geo[2])) == (900 + t.offset, 700 + t.offset),
      "окно (%s,%s), ожидалось (%d,%d)" % (geo[1], geo[2], 900 + t.offset, 700 + t.offset))
t.destroy()

print()
print("=== 2. в закреплённом режиме geometry() на движение НЕ вызывается ===")
for mode in ("top_left", "top_center", "top_right"):
    t = make(mode)
    t.update()
    n = count_geometry(t)
    check("режим %-11s -- вызовов geometry() при 200 движениях" % mode, n == 0,
          "вызовов: %d" % n)
    t.destroy()

print()
print("=== 3. координаты закреплённого оверлея ===")
left, top, right, bottom = work
width = A.px(115)
margin = A.px(A.PINNED_MARGIN)
expected = {
    "top_left": (left + margin, top),
    "top_center": (left + (right - left - width) // 2, top),
    "top_right": (right - width - margin, top),
}
for mode, (ex, ey) in expected.items():
    t = make(mode)
    t.update_idletasks()
    t.update()
    hwnd = win32gui.GetParent(t.winfo_id())
    wl, wt, wr, wb = win32gui.GetWindowRect(hwnd)
    print("  %-11s окно на экране (%d,%d)-(%d,%d), ожидалось (%d,%d)"
          % (mode, wl, wt, wr, wb, ex, ey))
    check("%s: позиция совпала" % mode, (wl, wt) == (ex, ey))
    check("%s: вплотную к верху рабочей области" % mode, wt == top,
          "wt=%d, top=%d" % (wt, top))
    check("%s: не вылезает за края" % mode, wl >= left and wr <= right,
          "%d..%d в %d..%d" % (wl, wr, left, right))
    t.destroy()

print()
print("=== 4. переключение режима на лету, в обе стороны ===")
t = make("cursor")
t.update()
n_before = count_geometry(t, 50)
t.set_position_mode("top_right")
t.update_idletasks(); t.update()
hwnd = win32gui.GetParent(t.winfo_id())
wl, wt, _, _ = win32gui.GetWindowRect(hwnd)
check("cursor -> top_right применилось сразу", (wl, wt) == expected["top_right"],
      "(%d,%d)" % (wl, wt))
n_pinned = count_geometry(t, 50)
check("после переключения geometry() на движение молчит", n_pinned == 0, str(n_pinned))

t.set_position_mode("cursor")
t.update()
n_back = count_geometry(t, 50)
check("top_right -> cursor вернуло слежение", n_back == 50,
      "было %d при слежении, стало %d" % (n_before, n_back))
t.destroy()

print()
print("=== 5. ветка смены монитора (логика, НЕ реальный второй монитор) ===")
t = make("top_left")
t.update()
t.pinned_area = (-9999, -9999, -9000, -9000)   # курсора здесь заведомо нет
calls_before = t.geometry_calls
t.last_x, t.last_y = 800, 600
t.apply_position()
check("уход курсора за пределы закреплённой области -> пересчёт",
      t.geometry_calls == calls_before + 1,
      "geometry_calls %d -> %d" % (calls_before, t.geometry_calls))
check("область перечитана на актуальную", t.pinned_area == work, str(t.pinned_area))
calls_before = t.geometry_calls
t.apply_position()
check("курсор внутри области -> пересчёта нет", t.geometry_calls == calls_before)
t.destroy()

print()
print("=== 6. строка устройств различима ===")
info = A.MouseHardware.get_mouse_info()
parts = [p.strip() for p in info.split(",")]
check("записи устройств различаются", len(parts) == len(set(parts)),
      "%d записей, %d уникальных" % (len(parts), len(set(parts))))
print("   ", info)

root.destroy()
print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
