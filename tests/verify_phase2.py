"""Проверка критериев приёмки Фазы 2."""
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
    print("  [%s] %-50s %s" % ("PASS" if cond else "FAIL", name, detail))


A.setup_logging()
A.enable_dpi_awareness()
root = tk.Tk()
root.withdraw()
A.apply_ui_scaling(root)

print("=== 1. чтение параметров указателя ===")
speed = A.MouseHardware.get_pointer_speed()
epp = A.MouseHardware.get_pointer_precision()
print("  get_pointer_speed()     =", repr(speed))
print("  get_pointer_precision() =", repr(epp))
check("скорость -- число, не None", isinstance(speed, int), repr(speed))
check("скорость в диапазоне 1..20", isinstance(speed, int) and 1 <= speed <= 20, repr(speed))
check("EPP -- bool, не None", isinstance(epp, bool), repr(epp))
check("старое имя удалено", not hasattr(A.MouseHardware, "get_system_dpi_setting"))

print()
print("=== 2. оверлей следует за курсором ===")


class FakePanel:
    pass


fp = FakePanel()
fp.root = root
# Оверлей берёт подписи из TRANSLATIONS по языку панели (Фаза 6),
# поэтому двойник обязан объявить язык, как это делает настоящая панель.
fp.current_lang = "English"
show = {'pos': True, 'accel': True, 'hz': True, 'cps': True, 'faults': True}
t = A.FloatingTracker(fp, A.SKINS["Dark (Default)"], show, alpha=0.8, click_through=False)
t.update()
print("  offset =", t.offset, "px (px(24) при масштабе %.2f)" % A.UI_SCALE)
check("offset определён и положителен", getattr(t, "offset", 0) > 0, str(getattr(t, "offset", None)))

positions = []
for (mx, my) in ((400, 300), (900, 650), (1500, 200), (700, 1000)):
    t.update_data(mx, my, time.perf_counter())
    t.update_idletasks()
    t.update()
    geo = t.geometry()
    wx, wy = int(geo.split("+")[1]), int(geo.split("+")[2])
    positions.append((mx, my, wx, wy))
    time.sleep(0.02)

for mx, my, wx, wy in positions:
    print("  курсор (%5d,%5d) -> окно (%5d,%5d)  смещение (%+d,%+d)"
          % (mx, my, wx, wy, wx - mx, wy - my))

moved = len({(wx, wy) for _, _, wx, wy in positions}) == len(positions)
check("окно меняет позицию вслед за курсором", moved)
correct = all(wx == mx + t.offset and wy == my + t.offset for mx, my, wx, wy in positions)
check("позиция равна курсор+offset", correct)

print()
print("=== 3. горячая точка курсора вне окна оверлея ===")
t.update_data(800, 500, time.perf_counter())
t.update_idletasks()
t.update()
hwnd = win32gui.GetParent(t.winfo_id())
l, tp, r, b = win32gui.GetWindowRect(hwnd)
cur = win32api.GetSystemMetrics(win32con.SM_CXCURSOR)
print("  окно на экране: (%d,%d)-(%d,%d) | курсор был в (800,500) | SM_CXCURSOR=%d" % (l, tp, r, b, cur))
inside = (l <= 800 <= r) and (tp <= 500 <= b)
check("горячая точка НЕ внутри окна", not inside,
      "иначе оверлей ловил бы клики сам")
check("offset перекрывает габарит курсора", t.offset >= cur * 0.6,
      "offset=%d, курсор=%d" % (t.offset, cur))

print()
print("=== 4. типы except сузились ===")
import io
src = io.open("mouse_info_app.py", encoding="utf-8").read()
check("голых 'except:' не осталось", "except:" not in src,
      "найдено %d" % src.count("except:"))

root.destroy()
print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
raise SystemExit(0 if all(ok) else 1)
