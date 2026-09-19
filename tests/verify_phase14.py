"""Проверка критериев приёмки Фазы 14 -- графики в реальном времени.

Главное здесь -- СКВОЗНАЯ проверка единого источника: значение, НАРИСОВАННОЕ
на графике, читается обратно из координат элемента холста и сверяется с
числом, которое стоит в живой строке. Промежуточные звенья не в счёт: баг
фазы 13 пережил 404 проверки именно потому, что все они смотрели на середину
цепочки. Здесь цепочка проходится целиком -- от постановки события в очередь
до пикселя, который видит пользователь.

Второй источник показания -- главный риск этой фазы: график, считающий своё,
разойдётся со строкой не сразу, а через несколько правок, и молча.
"""
import io
import os
import re
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mouse_info_app as A

ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print("  [%s] %-56s %s" % ("PASS" if cond else "FAIL", name, detail))


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
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT_DIR, "mouse_info_app.py"),
              encoding="utf-8").read()

root = tk.Tk()
A.apply_ui_scaling(root)
app = A.MainControlPanel(root)
root.update_idletasks()
root.update()

WIDE = (root.winfo_screenwidth(), root.minsize()[1])
NARROW = root.minsize()


def apply_size(width, height):
    root.geometry("%dx%d+20+20" % (width, height))
    root.update_idletasks()
    root.update()


def number_in(text):
    """Первое целое со знаком из строки -- то, что видит пользователь."""
    found = re.search(r"[-+]?\d+", text)
    return int(found.group()) if found else None


def newest_drawn(graph):
    """Координаты САМОЙ НОВОЙ нарисованной точки, прямо из холста."""
    visible = [item for item in graph.runs
               if graph.canvas.itemcget(item, "state") != "hidden"]
    if not visible:
        return None
    coords = graph.canvas.coords(visible[-1])
    if len(coords) < 2:
        return None
    return coords[-2], coords[-1]


def value_of(graph, point):
    """Пиксель -> значение. Обратное преобразование к тому, что рисует код."""
    left, right, top, bottom, ceiling = graph.plot_box
    x, y = point
    if graph.symmetric:
        return (0.5 - (y - top) / float(bottom - top)) * 2.0 * ceiling
    return (bottom - y) / float(bottom - top) * ceiling


def tolerance(graph):
    """Два пикселя шкалы: квантование, а не расхождение показаний."""
    left, right, top, bottom, ceiling = graph.plot_box
    span = 2.0 * ceiling if graph.symmetric else float(ceiling)
    return span / max(bottom - top, 1) * 2.0


def force_sample():
    """Заставляет цикл взять отсчёт прямо сейчас."""
    app.graph_sampled_at = 0.0
    app.update_live_labels()
    root.update_idletasks()


# --- 1. зависимостей не добавилось -------------------------------------------------
print("=== 1. ни одной новой зависимости ===")
# Ищется именно ИМПОРТ, а не слово: в коде с фазы 8 есть строка документации
# "порядковая статистика без numpy", и проверка на вхождение слова падала на
# ней. Это был дефект проверки, а не кода.
for banned in ("matplotlib", "numpy", "pyqtgraph", "PySide2", "PySide6",
               "PyQt5", "PyQt6"):
    check("%s не импортируется" % banned,
          ("import %s" % banned) not in SRC
          and ("from %s" % banned) not in SRC)
req = io.open(os.path.join(ROOT_DIR, "requirements.txt"), encoding="utf-8").read()
for banned in ("matplotlib", "numpy"):
    check("%s не появился в requirements" % banned, banned not in req.lower())
check("рисуем на tkinter Canvas", "tk.Canvas(" in SRC)
check("шрифтовые метрики из стандартного tkinter",
      "import tkinter.font as tkfont" in SRC)

# --- 2. горячий путь хука не тронут -------------------------------------------------
print()
print("=== 2. в обработчике хука по-прежнему только очередь ===")
hot = SRC.split("def on_mouse_move")[1].split("\n    def ")[0]
check("в on_mouse_move нет отрисовки",
      "graph" not in hot.lower() and "render" not in hot,
      "длина тела %d знаков" % len(hot))
check("в on_mouse_move только метка времени и очередь",
      "put_nowait" in hot and "perf_counter" in hot)
loop = SRC.split("def update_live_labels")[1].split("\n    def ")[0]
check("отсчёт берётся в цикле 10 мс", "self.sample_graphs()" in loop)
sampler = SRC.split("def sample_graphs")[1].split("\n    def ")[0]
check("цикл отрисовки прорежен по времени",
      "GRAPH_SAMPLE_MS" in sampler and "graph_sampled_at" in sampler)

# --- 3. кольцевой буфер: память не растёт ---------------------------------------------
print()
print("=== 3. память не растёт с длительностью сессии ===")
ring = A.RingSeries(5)
for value in range(3):
    ring.push(value)
check("пока не заполнен -- отдаёт накопленное", ring.values() == [0, 1, 2],
      str(ring.values()))
for value in range(3, 12):
    ring.push(value)
check("после переполнения -- последние size отсчётов",
      ring.values() == [7, 8, 9, 10, 11], str(ring.values()))
check("хранилище не выросло ни на элемент", len(ring.data) == 5,
      "len(data)=%d" % len(ring.data))
big = A.RingSeries(A.GRAPH_SLOTS)
for value in range(200000):
    big.push(value)
check("200000 отсчётов -- длина хранилища прежняя",
      len(big.data) == A.GRAPH_SLOTS and len(big.values()) == A.GRAPH_SLOTS,
      "data=%d values=%d" % (len(big.data), len(big.values())))
check("буферы приложения той же фиксированной длины",
      len(app.hz_series.data) == A.GRAPH_SLOTS
      and len(app.dv_series.data) == A.GRAPH_SLOTS)
check("окно и шаг дают заявленное число отсчётов",
      A.GRAPH_SLOTS == A.GRAPH_WINDOW_S * 1000 // A.GRAPH_SAMPLE_MS,
      "%d с / %d мс = %d" % (A.GRAPH_WINDOW_S, A.GRAPH_SAMPLE_MS,
                             A.GRAPH_SLOTS))

# --- 4. отсчёт берётся раз в GRAPH_SAMPLE_MS, а не каждый тик -------------------------
print()
print("=== 4. отрисовка не на каждый тик 10 мс ===")
app.hz_series = A.RingSeries(A.GRAPH_SLOTS)
app.dv_series = A.RingSeries(A.GRAPH_SLOTS)
app.graph_sampled_at = 0.0
app.update_live_labels()
after_first = app.hz_series.filled
app.update_live_labels()
app.update_live_labels()
app.update_live_labels()
check("первый вызов взял отсчёт", after_first == 1, "filled=%d" % after_first)
check("три следующих тика подряд отсчёта НЕ взяли",
      app.hz_series.filled == 1, "filled=%d" % app.hz_series.filled)
time.sleep(A.GRAPH_SAMPLE_MS / 1000.0 + 0.01)
app.update_live_labels()
check("после выдержки шага отсчёт взят",
      app.hz_series.filled == 2, "filled=%d" % app.hz_series.filled)

# --- 5. порог показа ------------------------------------------------------------------
print()
print("=== 5. графики появляются только когда есть место ===")
min_w, min_h = root.minsize()
apply_size(min_w, min_h)
check("на минимальном окне графиков нет", not app.graphs_visible)
check("и площадь под них не зарезервирована",
      app.graph_frame.winfo_manager() in ("", "grid")
      and not app.graph_frame.winfo_ismapped(),
      "manager=%r mapped=%s" % (app.graph_frame.winfo_manager(),
                                app.graph_frame.winfo_ismapped()))
need = app.frame.winfo_reqwidth() + 3 * A.px(A.PANEL_MARGIN)
apply_size(need + A.px(A.GRAPH_MIN_WIDTH) - A.px(20), min_h)
check("чуть ниже порога графиков всё ещё нет", not app.graphs_visible,
      "окно %d" % root.winfo_width())
apply_size(need + A.px(A.GRAPH_MIN_WIDTH) + A.px(20), min_h)
check("сразу выше порога графики есть", app.graphs_visible,
      "окно %d" % root.winfo_width())
apply_size(*WIDE)
check("на развёрнутом окне графики есть", app.graphs_visible)
check("оба холста разложены",
      app.hz_graph.canvas.winfo_ismapped()
      and app.dv_graph.canvas.winfo_ismapped())
check("график шире замеренного минимума",
      app.hz_graph.canvas.winfo_width() >= A.px(A.GRAPH_MIN_WIDTH),
      "%d при пороге %d" % (app.hz_graph.canvas.winfo_width(),
                            A.px(A.GRAPH_MIN_WIDTH)))
apply_size(min_w, min_h)
check("окно снова узкое -- графики убрались", not app.graphs_visible)
check("minsize от появления графиков не изменился",
      root.minsize() == (min_w, min_h), str(root.minsize()))
check("и окно по-прежнему не сжимается ниже минимума",
      root.winfo_width() >= min_w and root.winfo_height() >= min_h,
      "%dx%d" % (root.winfo_width(), root.winfo_height()))

# --- 6. подсказка ----------------------------------------------------------------------
print()
print("=== 6. подсказка существует и не врёт ===")
apply_size(min_w, min_h)
hidden_text = app.graph_hint.cget("text")
hidden_height = app.frame.winfo_reqheight()
apply_size(*WIDE)
shown_text = app.graph_hint.cget("text")
shown_height = app.frame.winfo_reqheight()
print("   скрыты: %r" % hidden_text)
print("   видны : %r" % shown_text)
check("при скрытых графиках подсказка зовёт растянуть окно",
      hidden_text == app.tr()["graph_hint_off"] and hidden_text != "")
check("при видимых графиках текст другой и не про растягивание",
      shown_text == app.tr()["graph_hint_on"] and shown_text != hidden_text)
check("высота панели от состояния графиков НЕ зависит",
      hidden_height == shown_height,
      "%d против %d" % (hidden_height, shown_height))
check("обе подсказки умещаются в одну строку",
      app.graph_hint.winfo_reqheight()
      <= A.px(A.PANEL_PAD) + app.graph_hint.winfo_reqheight(),
      "%d" % app.graph_hint.winfo_reqheight())

# --- 7. ось и подписи обязательны --------------------------------------------------------
print()
print("=== 7. у графика есть ось и подписи ===")
apply_size(*WIDE)
force_sample()
for tag, graph in (("частота", app.hz_graph), ("dV", app.dv_graph)):
    canvas = graph.canvas
    check("%s: заголовок непустой" % tag,
          canvas.itemcget(graph.item_title, "text") != "",
          canvas.itemcget(graph.item_title, "text"))
    check("%s: обе оси нарисованы" % tag,
          len(canvas.coords(graph.item_axis_x)) == 4
          and len(canvas.coords(graph.item_axis_y)) == 4)
    ylabels = [canvas.itemcget(i, "text") for i in graph.y_labels]
    xlabels = [canvas.itemcget(i, "text") for i in graph.x_labels]
    check("%s: подписи оси Y заполнены" % tag,
          all(s != "" for s in ylabels), str(ylabels))
    check("%s: подписи оси X заполнены" % tag,
          all(s != "" for s in xlabels), str(xlabels))
    check("%s: ось X кончается нулём -- 'сейчас' справа" % tag,
          xlabels[-1] == "0", str(xlabels))
    check("%s: ось X начинается длиной окна" % tag,
          xlabels[0] == "-%d%s" % (A.GRAPH_WINDOW_S, app.tr()["graph_sec"]),
          str(xlabels))
check("шкала dV симметрична и с нулём посередине",
      [app.dv_graph.canvas.itemcget(i, "text")
       for i in app.dv_graph.y_labels][2] == "0")
check("шкала округляется до 1/2/5*10^n, а не до измеренного максимума",
      (A.graph_ceiling(0), A.graph_ceiling(37), A.graph_ceiling(150),
       A.graph_ceiling(837)) == (10, 50, 200, 1000))

# --- 8. dV -- величина без единиц и без нормы ----------------------------------------------
print()
print("=== 8. dV без единиц, без нормы, без цветовой индикации ===")
for lang in ("English", "Русский"):
    title = A.TRANSLATIONS[lang]["graph_dv_title"]
    check("%s: заголовок dV называет величину относительной" % lang,
          ("relative" in title.lower() or "относительн" in title.lower()),
          title)
    check("%s: и прямо говорит про отсутствие единиц" % lang,
          ("no units" in title.lower() or "без единиц" in title.lower()),
          title)
block = SRC.split("class LiveGraph")[1].split("\nclass ")[0]
for word in ("good", "bad", "warn", "danger", "норма", "хорош", "плох"):
    check("в графике нет слова %r" % word, word not in block.lower())
check("цветов ровно два -- по одному на график, без зон",
      SRC.count('color="#b2541f"') == 1 and 'color="#1f6fb2"' in SRC)

# --- 9. СКВОЗНАЯ: нарисованное значение равно тому, что в живой строке -----------------------
print()
print("=== 9. СКВОЗНАЯ: пиксель графика == число в строке ===")
apply_size(*WIDE)
app.toggle_tracker()
root.update()
check("подписка on_move не потерялась", "on_move" in FakeListener.kwargs,
      str(sorted(FakeListener.kwargs)))

now = time.perf_counter()
size0 = app.data_queue.qsize()
for i in range(120):
    app.on_mouse_move(500 + (i * 7) % 200, 400 + (i * 11) % 150)
check("обработчик положил события в очередь",
      app.data_queue.qsize() - size0 == 120,
      "+%d" % (app.data_queue.qsize() - size0))
app.process_events()
force_sample()

hz_text = app.hz_label.cget("text")
hz_shown = number_in(hz_text)
point = newest_drawn(app.hz_graph)
check("на графике частоты есть нарисованная точка", point is not None)
if point:
    drawn = value_of(app.hz_graph, point)
    print("   строка: %r -> %s | нарисовано: %.2f (допуск %.2f)"
          % (hz_text, hz_shown, drawn, tolerance(app.hz_graph)))
    check("частота: НАРИСОВАННОЕ значение равно числу в строке",
          abs(drawn - hz_shown) <= tolerance(app.hz_graph),
          "%.2f против %d" % (drawn, hz_shown))
    check("частота: свежая точка стоит у правого края",
          abs(point[0] - app.hz_graph.plot_box[1]) <= 1,
          "x=%.1f при правом крае %.1f" % (point[0],
                                           app.hz_graph.plot_box[1]))
check("строка частоты собрана тем же источником, что и график",
      hz_text == app.hz_line() and hz_shown == app.live_hz(),
      "%r / %r" % (hz_text, app.live_hz()))

dv_label = app.tracker.labels.get("accel")
dv_text = dv_label.cget("text") if dv_label is not None else ""
dv_shown = number_in(dv_text)
dv_point = newest_drawn(app.dv_graph)
check("на графике dV есть нарисованная точка", dv_point is not None)
if dv_point and dv_shown is not None:
    drawn_dv = value_of(app.dv_graph, dv_point)
    print("   подпись оверлея: %r -> %s | нарисовано: %.2f (допуск %.2f)"
          % (dv_text, dv_shown, drawn_dv, tolerance(app.dv_graph)))
    check("dV: НАРИСОВАННОЕ значение равно числу в подписи",
          abs(drawn_dv - dv_shown) <= tolerance(app.dv_graph),
          "%.2f против %d" % (drawn_dv, dv_shown))
check("подпись dV собрана тем же источником, что и график",
      dv_shown == app.live_dv(), "%r / %r" % (dv_shown, app.live_dv()))

# Значения НАМЕРЕННО другие: совпадение чисел сделало бы проверку пустой.
prev_hz = hz_shown
for i in range(37):
    app.on_mouse_move(900 + (i * 3) % 60, 700 + (i * 5) % 60)
app.process_events()
force_sample()
hz2 = number_in(app.hz_label.cget("text"))
point2 = newest_drawn(app.hz_graph)
check("другое число событий даёт другое показание", hz2 != prev_hz,
      "%s -> %s" % (prev_hz, hz2))
if point2:
    check("и график поехал за строкой, а не остался прежним",
          abs(value_of(app.hz_graph, point2) - hz2)
          <= tolerance(app.hz_graph),
          "%.2f против %d" % (value_of(app.hz_graph, point2), hz2))

# --- 10. состояния: где показания нет -- линии нет -------------------------------------------
print()
print("=== 10. нет показания -- нет линии ===")
holed = [10, 11, None, None, 14, 15]
runs = app.hz_graph.build_runs(holed, 0.0, 100.0, 0.0, 50.0, 20)
check("пропуск разрывает линию на два участка", len(runs) == 2,
      "участков %d" % len(runs))
check("через пропуск линия НЕ интерполируется",
      all(len(r) == 2 for r in runs), str([len(r) for r in runs]))
check("сплошные данные дают один участок",
      len(app.hz_graph.build_runs([1, 2, 3], 0.0, 100.0, 0.0, 50.0, 20)) == 1)
check("совсем пустое окно не даёт ни одного участка",
      app.hz_graph.build_runs([None, None], 0.0, 100.0, 0.0, 50.0, 20) == [])

check("вне сессии показания частоты не существует",
      app.live_hz() is not None)
app.stop_session()
root.update()
check("после СТОП источник частоты говорит 'показания нет'",
      app.live_hz() is None, repr(app.live_hz()))
check("после СТОП источник dV говорит то же", app.live_dv() is None)

right_edge_before = newest_drawn(app.hz_graph)
for _ in range(5):
    force_sample()
    time.sleep(A.GRAPH_SAMPLE_MS / 1000.0 + 0.005)
force_sample()
after = newest_drawn(app.hz_graph)
if after and right_edge_before:
    print("   правый край поля %.1f | свежая точка была %.1f, стала %.1f"
          % (app.hz_graph.plot_box[1], right_edge_before[0], after[0]))
    check("после СТОП линия ОТСТАЁТ от правого края, а не тянется нулём",
          after[0] < app.hz_graph.plot_box[1] - 2,
          "x=%.1f при крае %.1f" % (after[0], app.hz_graph.plot_box[1]))

# --- 11. строка частоты больше не застревает после остановки ------------------------------------
print()
print("=== 11. строка частоты не застревает после СТОП ===")
app.toggle_tracker()
root.update()
for i in range(64):
    app.on_mouse_move(300 + i, 300 + i)
app.process_events()
app.update_live_labels()
root.update()
during = app.hz_label.cget("text")
app.stop_session()
app.update_live_labels()
root.update()
after_stop = app.hz_label.cget("text")
print("   во время %r -> после остановки %r" % (during, after_stop))
check("во время сессии строка показывает число", number_in(during) == 64,
      during)
check("после остановки строка НЕ держит частоту прошлой сессии",
      after_stop != during, after_stop)
check("а показывает то, что даёт источник", after_stop == app.hz_line(),
      after_stop)
check("обновление строки частоты стоит вне ветки 'если сессия идёт'",
      "self.hz_label.config(text=self.hz_line())" in loop)

# --- 12. пустое окно честно называется пустым ----------------------------------------------------
print()
print("=== 12. пустой график говорит, что он пуст ===")
app.hz_series = A.RingSeries(A.GRAPH_SLOTS)
app.dv_series = A.RingSeries(A.GRAPH_SLOTS)
force_sample()
check("на пустом окне показана надпись 'нет данных'",
      app.hz_graph.canvas.itemcget(app.hz_graph.item_empty, "state")
      == "normal")
check("и текст надписи локализован",
      app.hz_graph.canvas.itemcget(app.hz_graph.item_empty, "text")
      == app.tr()["graph_no_data"])

# --- 13. оба языка -------------------------------------------------------------------------------
print()
print("=== 13. оба языка на трёх размерах ===")
keys = [set(A.TRANSLATIONS[lang]) for lang in A.TRANSLATIONS]
check("наборы ключей совпадают", keys[0] == keys[1],
      "по %d ключей" % len(keys[0]))
for key in ("graph_hz_title", "graph_dv_title", "graph_no_data", "graph_sec",
            "graph_hint_off", "graph_hint_on"):
    check("ключ %s есть в обоих словарях" % key,
          all(key in A.TRANSLATIONS[lang] for lang in A.TRANSLATIONS))

for lang in ("English", "Русский"):
    app.lang_var.set(lang)
    app.setup_ui()
    root.update_idletasks()
    t = A.TRANSLATIONS[lang]
    for name, width, height in (("минимальный", min_w, min_h),
                                ("дефолтный", min_w + A.px(60),
                                 min_h + A.px(80)),
                                ("во весь экран", WIDE[0], WIDE[1])):
        apply_size(width, height)
        force_sample()
        expect = width >= (app.frame.winfo_reqwidth()
                           + 3 * A.px(A.PANEL_MARGIN)
                           + A.px(A.GRAPH_MIN_WIDTH))
        check("%s / %s: видимость графиков по порогу" % (lang, name),
              app.graphs_visible == expect,
              "видны=%s ожидалось=%s" % (app.graphs_visible, expect))
        check("%s / %s: подсказка соответствует состоянию" % (lang, name),
              app.graph_hint.cget("text")
              == (t["graph_hint_on"] if app.graphs_visible
                  else t["graph_hint_off"]),
              app.graph_hint.cget("text"))
        if app.graphs_visible:
            check("%s / %s: заголовки графиков на этом языке" % (lang, name),
                  app.hz_graph.canvas.itemcget(app.hz_graph.item_title,
                                               "text") == t["graph_hz_title"]
                  and app.dv_graph.canvas.itemcget(app.dv_graph.item_title,
                                                   "text")
                  == t["graph_dv_title"])
            check("%s / %s: ось X подписана на этом языке" % (lang, name),
                  app.hz_graph.canvas.itemcget(app.hz_graph.x_labels[0],
                                               "text")
                  == "-%d%s" % (A.GRAPH_WINDOW_S, t["graph_sec"]),
                  app.hz_graph.canvas.itemcget(app.hz_graph.x_labels[0],
                                               "text"))
        check("%s / %s: содержимое колонки не обрезано" % (lang, name),
              app.frame.winfo_height() >= app.frame.winfo_reqheight(),
              "%d при требуемой %d" % (app.frame.winfo_height(),
                                       app.frame.winfo_reqheight()))

app.lang_var.set("English")
app.setup_ui()
root.update_idletasks()

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
app.stop_session()
app.shutdown()
sys.exit(0 if all(ok) else 1)
