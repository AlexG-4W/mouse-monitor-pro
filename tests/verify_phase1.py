"""Проверка критериев приёмки Фазы 1. Запускать из каталога проекта."""
import math
import os
import time
import tkinter as tk

import os
import sys

# Стенд лежит в tests/, приложение -- на уровень выше.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mouse_info_app as A

ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print("  [%s] %-52s %s" % ("PASS" if cond else "FAIL", name, detail))


print("=== 1. DPI awareness и масштаб ===")
awareness, method = A.enable_dpi_awareness()
print("  awareness =", awareness, "| через:", method)
check("процесс DPI-осведомлён", awareness in ("PER_MONITOR_AWARE", "SYSTEM_AWARE"), awareness)

root = tk.Tk()
root.withdraw()
dpi, scale = A.apply_ui_scaling(root)
print("  DPI =", dpi, "| UI_SCALE =", scale, "| tk scaling =", root.tk.call("tk", "scaling"))

print()
print("=== 2. схлопывание множителя при 100% (dpi=96) ===")
saved = A.UI_SCALE
A.UI_SCALE = 96 / 96.0
check("px(380) == 380 при dpi=96", A.px(380) == 380, "px(380)=%d" % A.px(380))
check("px(780) == 780 при dpi=96", A.px(780) == 780, "px(780)=%d" % A.px(780))
check("px(115) == 115 при dpi=96", A.px(115) == 115, "px(115)=%d" % A.px(115))
A.UI_SCALE = saved
print("  (текущий множитель восстановлен: %.2f -> px(380)=%d)" % (A.UI_SCALE, A.px(380)))

print()
print("=== 3. теплокарта в физическом разрешении ===")
hm = A.HeatmapManager()
hm.start()
print("  метрики после start():", hm.screen_w, "x", hm.screen_h)
for i in range(4000):
    a = i / 4000 * math.tau * 3
    hm.update(int(hm.screen_w / 2 + math.cos(a) * i / 12),
              int(hm.screen_h / 2 + math.sin(a) * i / 18))
f = hm.save()
from PIL import Image
size = Image.open(f).size
print("  PNG:", f, size)
check("PNG равен физическому виртуальному экрану", size == (hm.screen_w, hm.screen_h), str(size))
check("PNG больше прежних 1707x960", size[0] > 1707, str(size))
# Снимок PNG больше НЕ копируется в baseline/: копия ничего не утверждала
# (размер проверен выше), зато каждый прогон оставлял в дереве репозитория
# изменённый файл -- у любого, кто склонировал проект и запустил тесты.
os.remove(f)

print()
print("=== 4. перечитывание метрик на старте сессии ===")
hm.screen_w, hm.screen_h = 1, 1          # имитируем устаревшие метрики
hm.start()
check("start() перечитал метрики экрана", (hm.screen_w, hm.screen_h) != (1, 1),
      "%dx%d" % (hm.screen_w, hm.screen_h))

print()
print("=== 5. CPS спадает до нуля ===")


class FakePanel:
    pass


fp = FakePanel()
fp.root = root
# Оверлей берёт подписи из TRANSLATIONS по языку панели (Фаза 6),
# поэтому двойник обязан объявить язык, как это делает настоящая панель.
fp.current_lang = "English"
show = {'pos': True, 'accel': True, 'hz': True, 'cps': True, 'faults': True}
t = A.FloatingTracker(fp, A.SKINS["Dark (Default)"], show, alpha=0.8, click_through=False)

t.add_click("Button.left", time.perf_counter(), True)
time.sleep(0.15)
t.add_click("Button.left", time.perf_counter(), True)
print("  сразу после 2 кликов          : cps =", t.cps)
check("после 2 кликов cps == 2", t.cps == 2)

t0 = time.perf_counter()
while time.perf_counter() - t0 < 2.5:
    n = time.perf_counter()
    t.update_data(500 + int(50 * math.sin(n * 7)), 500 + int(50 * math.cos(n * 7)), n)
    time.sleep(0.004)
print("  спустя 2.5 с без кликов       : cps =", t.cps, "| len(click_times) =", len(t.click_times))
check("cps спал до 0", t.cps == 0, "cps=%d" % t.cps)
check("click_times очищен", len(t.click_times) == 0, "len=%d" % len(t.click_times))

print()
print("=== 6. геометрия оверлея отмасштабирована ===")
# Окно надо отрисовать: до этого geometry() возвращает "1x1".
t.update_idletasks()
t.update()
geom = t.geometry().split("+")[0]
print("  геометрия оверлея:", geom, "| ожидалось %dx%d" % (A.px(115), A.px(5 * 20)))
check("ширина оверлея == px(115)", geom.split("x")[0] == str(A.px(115)), geom)

root.destroy()
print()
print("ИТОГО: %d из %d проверок пройдено" % (sum(ok), len(ok)))
raise SystemExit(0 if all(ok) else 1)
