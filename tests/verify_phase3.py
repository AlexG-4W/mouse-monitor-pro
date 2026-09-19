"""Проверка критериев приёмки Фазы 3."""
import os
import queue
import sys
import threading
import time
import tkinter as tk

import os
import sys

# Стенд лежит в tests/, приложение -- на уровень выше.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mouse_info_app as A

ok = []
tray_errors = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print("  [%s] %-52s %s" % ("PASS" if cond else "FAIL", name, detail))


# Ловим ЛЮБОЕ исключение в фоновых потоках -- прежде здесь падал setup_tray.
def _hook(args):
    tray_errors.append("%s: %s" % (args.exc_type.__name__, args.exc_value))


threading.excepthook = _hook

A.setup_logging()
A.enable_dpi_awareness()
root = tk.Tk()
root.withdraw()
A.apply_ui_scaling(root)

# считаем обращения к WMI
wmi_calls = {"n": 0}
_orig_wmi = A.MouseHardware.get_mouse_info


def counting_wmi():
    wmi_calls["n"] += 1
    return _orig_wmi()


A.MouseHardware.get_mouse_info = staticmethod(counting_wmi)

app = A.MainControlPanel(root)
root.update()

print("=== 1. хук ставится только на время сессии ===")
check("после запуска приложения хука нет", app.listener is None, repr(app.listener))
app.enable_heatmap.set(True)
app.enable_logging.set(True)
app.toggle_tracker()
root.update()
check("после START хук установлен", app.listener is not None)
check("поток слушателя жив", app.listener is not None and app.listener.running)
lst = app.listener
app.toggle_tracker()
root.update()
time.sleep(0.4)
check("после STOP хук снят", app.listener is None)
check("поток слушателя остановлен", not lst.running)

print()
print("=== 2. WMI опрашивается один раз ===")
before = wmi_calls["n"]
app.lang_var.set("Русский")
app.setup_ui()
root.update()
app.lang_var.set("English")
app.setup_ui()
root.update()
check("две смены языка не добавили WMI-запросов", wmi_calls["n"] == before,
      "было %d, стало %d" % (before, wmi_calls["n"]))
check("всего WMI-запросов за сессию == 1", wmi_calls["n"] == 1, str(wmi_calls["n"]))

print()
print("=== 3. потоковая безопасность трея ===")
check("иконка опубликована через Event", app.icon_ready.wait(timeout=10))
check("поток трея не бросил исключений", not tray_errors, "; ".join(tray_errors))
check("меню собирается без Tk", app.build_tray_menu() is not None)

# команда из фонового потока исполняется главным
marker = []
threading.Thread(target=lambda: app.command_queue.put(lambda: marker.append(1)),
                 name="fake-tray").start()
time.sleep(0.2)
app.run_thread_commands()
check("команда фонового потока выполнена в главном", marker == [1], str(marker))

print()
print("=== 4. очередь ограничена, потери считаются ===")
check("maxsize выставлен", app.data_queue.maxsize == A.EVENT_QUEUE_MAXSIZE,
      str(app.data_queue.maxsize))
app.dropped_events = 0
while not app.data_queue.empty():
    app.data_queue.get_nowait()
overflow = A.EVENT_QUEUE_MAXSIZE + 500
for i in range(overflow):
    app.on_mouse_move(i, i)
print("  подано %d событий при потолке %d" % (overflow, A.EVENT_QUEUE_MAXSIZE))
check("очередь не превысила потолок", app.data_queue.qsize() == A.EVENT_QUEUE_MAXSIZE,
      str(app.data_queue.qsize()))
check("лишние события посчитаны как потери", app.dropped_events == 500,
      str(app.dropped_events))
app.update_live_labels()
root.update()
check("счётчик потерь виден в UI", "500" in app.dropped_label.cget("text"),
      repr(app.dropped_label.cget("text")))
while not app.data_queue.empty():
    app.data_queue.get_nowait()

print()
print("=== 5. каталоги данных не зависят от CWD ===")
print("  data_dir() =", A.data_dir())
check("data_dir абсолютный", os.path.isabs(A.data_dir()))
check("data_dir рядом с приложением", A.data_dir() == A.app_dir(), A.data_dir())

print()
print("=== 6. закрытие крестиком сохраняет и PNG, и CSV ===")
check("WM_DELETE_WINDOW назначен", root.protocol("WM_DELETE_WINDOW") != "",
      repr(root.protocol("WM_DELETE_WINDOW")))
app.enable_heatmap.set(True)
app.enable_logging.set(True)
# Снимок каталога берётся ровно перед ЭТОЙ сессией: раньше он стоял в секции 1,
# и к проверке накапливались PNG от двух сессий сразу.
_hm_dir = os.path.join(A.data_dir(), "heatmaps")
pngs_before = set(os.listdir(_hm_dir)) if os.path.isdir(_hm_dir) else set()
app.toggle_tracker()
root.update()
for i in range(300):
    app.on_mouse_move(400 + i, 300 + (i % 100))
root.update()
csv_name = app.logger.filename
app.shutdown()          # ровно то, что делает крестик
check("CSV закрыт", app.logger.file is None)
check("CSV существует", os.path.isfile(csv_name), csv_name)
hm_dir = os.path.join(A.data_dir(), "heatmaps")
# По РАЗНИЦЕ каталога, а не по его непустоте: файлы накапливаются от прогона
# к прогону, и проверка "хотя бы один PNG существует" проходила бы вхолостую
# даже при полностью сломанном сохранении.
pngs_after = set(os.listdir(hm_dir)) if os.path.isdir(hm_dir) else set()
made_png = sorted(pngs_after - pngs_before)
check("PNG теплокарты создан крестиком", len(made_png) == 1, str(made_png))
check("хук снят при выходе", app.listener is None)
check("повторный shutdown безвреден", app.shutdown() is None)

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 1)
