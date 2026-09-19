"""Таблица срабатываний детектора дребезга по скоростям клика.

Две модели скважности:
  A) 50%          -- нажатие и пауза равны половине периода
  B) нажатие 40 мс -- фиксированная длительность нажатия, пауза = остаток
Модель B физически невозможна выше 25 кликов/с: период становится короче
самого нажатия.
"""
import tkinter as tk

import os
import sys

# Стенд лежит в tests/, приложение -- на уровень выше.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mouse_info_app as A

root = tk.Tk()
root.withdraw()
A.enable_dpi_awareness()
A.apply_ui_scaling(root)


class FakePanel:
    pass


fp = FakePanel()
fp.root = root
SHOW = {'pos': False, 'accel': False, 'hz': False, 'cps': False, 'faults': True}


def run(press_s, gap_s, clicks=10):
    """Возвращает (GAP-ошибок, SHORT-ошибок, подозрений)."""
    t = A.FloatingTracker(fp, A.SKINS["Dark (Default)"], SHOW,
                          alpha=0.8, click_through=False, position_mode="cursor")
    now = 1000.0
    gap_n = short_n = susp_n = 0
    for _ in range(clicks):
        f = t.add_click("Button.left", now, True)
        if f == "DC_FAULT_GAP":
            gap_n += 1
        elif f == "DC_SUSPECT":
            susp_n += 1
        now += press_s
        f = t.add_click("Button.left", now, False)
        if f == "DC_FAULT_SHORT":
            short_n += 1
        now += gap_s
    t.destroy()
    return gap_n, short_n, susp_n


print("пороги: GAP < %.0f мс | SHORT < %.0f мс | SUSPECT < %.0f мс"
      % (A.DC_FAULT_GAP * 1000, A.DC_SHORT_PRESS * 1000, A.DC_SUSPECT_GAP * 1000))
print("10 кликов в каждой серии\n")

hdr = "%-8s %-9s %-9s %8s %8s %10s %8s" % (
    "кликов/с", "нажатие", "пауза", "GAP", "SHORT", "ошибок", "подозр.")

for model, label in (("A", "модель A: скважность 50%"),
                     ("B", "модель B: нажатие 40 мс")):
    print(label)
    print("  " + hdr)
    print("  " + "-" * len(hdr))
    for cps in (12, 16, 20, 24, 30, 40):
        period = 1.0 / cps
        if model == "A":
            press = gap = period / 2.0
        else:
            press = 0.040
            gap = period - press
        if gap <= 0:
            print("  %-8d %-9s %-9s %8s %8s %10s %8s"
                  % (cps, "40 мс", "-", "-", "-", "невозможно", "-"))
            continue
        g, sh, su = run(press, gap)
        print("  %-8d %-9s %-9s %8d %8d %10d %8d"
              % (cps, "%.0f мс" % (press * 1000), "%.0f мс" % (gap * 1000),
                 g, sh, g + sh, su))
    print()

root.destroy()
