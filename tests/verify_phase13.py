"""Проверка критериев приёмки Фазы 13.

Главное здесь -- СКВОЗНАЯ проверка: от постановки события в очередь до текста,
который видит пользователь. Баг фазы 13 (строка колеса навсегда застряла на
"прокрутки не было") пережил 404 проверки именно потому, что все они смотрели
на промежуточные звенья: стенд фазы 9 звал wheel_line(), стенд фазы 12
проверял, что виджет упакован. Работали оба, а метка молчала.
"""
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
        FakeListener.kwargs = kwargs

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


# --- 1. цепочка колеса целиком, звено за звеном --------------------------------
print("=== 1. от колбэка pynput до текста в панели ===")
app.toggle_tracker()
root.update()
app.update_live_labels()
idle_text = app.wheel_label.cget("text")
check("подписка on_scroll не потерялась",
      "on_scroll" in FakeListener.kwargs, str(sorted(FakeListener.kwargs)))

size0 = app.data_queue.qsize()
for _ in range(6):
    app.on_scroll(500, 400, 0, -1)
check("обработчик кладёт тики в очередь",
      app.data_queue.qsize() - size0 == 6,
      "+%d" % (app.data_queue.qsize() - size0))

app.process_events()
check("трекер посчитал тики", app.tracker.wheel_ticks == 6,
      "ticks=%d" % app.tracker.wheel_ticks)
check("wheel_state() видит их", app.wheel_state()["ticks"] == 6)
check("wheel_line() их называет", "6" in app.wheel_line(), app.wheel_line())

app.update_live_labels()
root.update()
live_text = app.wheel_label.cget("text")
print("   до прокрутки %r -> после %r" % (idle_text, live_text))
check("ТЕКСТ В ПАНЕЛИ изменился", live_text != idle_text)
check("ТЕКСТ В ПАНЕЛИ совпал с источником", live_text == app.wheel_line(),
      live_text)
check("в панели видно число тиков", "6" in live_text, live_text)

# --- 2. сквозная проверка ВСЕХ живых строк --------------------------------------
print()
print("=== 2. каждая живая строка отражает свой источник ===")
now = time.perf_counter()
for i in range(40):
    app.data_queue.put_nowait(("move", 400 + i * 6, 300 + i * 3,
                               now + i * 0.004))
for i in range(3):
    app.data_queue.put_nowait(("click", 400, 300, "Button.left", True,
                               now + 0.5 + i * 0.2))
    app.data_queue.put_nowait(("click", 400, 300, "Button.left", False,
                               now + 0.5 + i * 0.2 + 0.005))
app.dropped_events = 4
app.process_events()
app.update_live_labels()
root.update()

t = app.tr()
sources = (
    ("hz_label", lambda: t["hz_label"].format(app.tracker.hz)),
    ("rate_label", app.rate_line),
    ("wheel_label", app.wheel_line),
    ("faults_label", lambda: t["faults_label"].format(
        app.tracker.fault_counts["left"], app.tracker.fault_counts["right"])),
    ("suspect_label", lambda: t["suspect_label"].format(
        app.tracker.suspect_counts["left"],
        app.tracker.suspect_counts["right"])),
    ("dropped_label", lambda: t["dropped_label"].format(app.dropped_events)),
)
for name, source in sources:
    shown = getattr(app, name).cget("text")
    expected = source()
    check("%s показывает то, что даёт источник" % name, shown == expected,
          "%r против %r" % (shown, expected))

check("дребезг доехал до панели",
      str(app.tracker.fault_counts["left"]) in app.faults_label.cget("text")
      and app.tracker.fault_counts["left"] > 0,
      app.faults_label.cget("text"))
check("счётчик потерь доехал до панели",
      "4" in app.dropped_label.cget("text"), app.dropped_label.cget("text"))

# --- 3. ни одна живая строка не застряла на тексте сборки -------------------------
print()
print("=== 3. ни одна строка не осталась текстом времени сборки ===")
build_time = {}
app.stop_session()
# Цикл 10 мс мог ещё не наступить: гасим показания явно, иначе setup_ui
# соберёт метки со значениями прошлой сессии и "текст времени сборки"
# окажется не тем, что бывает при запуске.
app.update_live_labels()
root.update()
app.setup_ui()
root.update()
for name, _ in sources:
    build_time[name] = getattr(app, name).cget("text")

app.toggle_tracker()
root.update()
now = time.perf_counter()
# Число движений НАМЕРЕННО другое, чем в разделе 2: совпадение значений
# сделало бы проверку "текст изменился" бессмысленной.
for i in range(25):
    app.data_queue.put_nowait(("move", 700 + i * 5, 500 + i * 2,
                               now + i * 0.004))
# Тиков берём БОЛЬШЕ порога WHEEL_MIN_TICKS: ниже него состояние отдельное
# (WHEEL_FEW), и проверять надо оба, что и делается ниже.
for _ in range(A.WHEEL_MIN_TICKS + 2):
    app.on_scroll(700, 500, 0, 1)
app.data_queue.put_nowait(("click", 700, 500, "Button.left", True, now + 0.4))
app.data_queue.put_nowait(("click", 700, 500, "Button.left", False, now + 0.402))
app.dropped_events = 9
app.process_events()
app.update_live_labels()
root.update()
changed = [name for name, _ in sources
           if getattr(app, name).cget("text") != build_time[name]]
print("   изменились после подачи данных: %s" % changed)
check("частота обновилась", "hz_label" in changed)
check("колесо обновилось", "wheel_label" in changed)
check("дребезг обновился", "faults_label" in changed)
check("потери обновились", "dropped_label" in changed)

# --- 4. обновление переживает смену языка ------------------------------------------
print()
print("=== 3b. мало тиков -- отдельное состояние, а не 'не крутили' ===")
few = A.wheel_health(A.WHEEL_MIN_TICKS - 1, 0, 0)
check("тики есть, но мало -> WHEEL_FEW", few["state"] == A.WHEEL_FEW,
      few["state"])
check("совсем без тиков -> WHEEL_NONE",
      A.wheel_health(0, 0, 0)["state"] == A.WHEEL_NONE)
app.stop_session()
root.update()
app.toggle_tracker()
root.update()
for _ in range(A.WHEEL_MIN_TICKS - 1):
    app.on_scroll(300, 300, 0, -1)
app.process_events()
app.update_live_labels()
text_few = app.wheel_label.cget("text")
print("   %d тиков -> %r" % (app.tracker.wheel_ticks, text_few))
check("панель не утверждает, что прокрутки не было",
      text_few != A.TRANSLATIONS[app.current_lang]["wheel_none"], text_few)
check("и называет число тиков",
      str(app.tracker.wheel_ticks) in text_few, text_few)

print()
print("=== 4. смена языка не рвёт обновление ===")
app.lang_var.set("Русский")
app.setup_ui()
root.update()
for _ in range(5):
    app.on_scroll(700, 500, 0, -1)
app.process_events()
app.update_live_labels()
root.update()
ru_text = app.wheel_label.cget("text")
check("после смены языка строка колеса живая",
      ru_text == app.wheel_line() and "Колесо" in ru_text, ru_text)
check("и число тиков в ней есть",
      str(app.tracker.wheel_ticks) in ru_text, ru_text)
app.lang_var.set("English")
app.setup_ui()
root.update()

# --- 5. обновление есть в коде для каждой живой метки -------------------------------
print()
print("=== 5. страховка: обновление каждой метки видно в коде ===")
SRC = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "mouse_info_app.py"), encoding="utf-8").read()
body = SRC.split("def update_live_labels")[1].split("\n    def ")[0]
for name in ("hz_label", "rate_label", "wheel_label", "dropped_label"):
    check("%s обновляется в цикле" % name, name + ".config" in body)
check("счётчики дребезга обновляются отдельным вызовом",
      "update_fault_labels()" in body)

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
app.stop_session()
app.shutdown()
sys.exit(0 if all(ok) else 1)
