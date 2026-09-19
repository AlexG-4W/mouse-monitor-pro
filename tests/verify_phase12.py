"""Проверка критериев приёмки Фазы 12."""
import io
import os
import sys
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
A.apply_ui_scaling(root)
app = A.MainControlPanel(root)
root.update_idletasks()
root.update()

COLUMN = A.px(A.PANEL_WIDTH)


def sizes():
    """Три размера: минимальный, дефолтный и во весь экран."""
    min_w, min_h = root.minsize()
    return (("минимальный", min_w, min_h),
            ("дефолтный", min_w + A.px(60), min_h + A.px(80)),
            ("во весь экран", root.winfo_screenwidth(),
             root.winfo_screenheight() - A.px(60)))


def apply_size(width, height):
    root.geometry("%dx%d+20+20" % (width, height))
    root.update_idletasks()
    root.update()


# --- 1. колонка фиксированной ширины, у левого края -----------------------------
# Отступ слева обязан быть ПОСТОЯННЫМ и равным полю: это и есть
# выравнивание влево. Проверка «поля симметричны» стояла здесь до того,
# как центрирование было отменено командой.
print("=== 1. колонка держит ширину и стоит у левого края ===")
MARGIN = A.px(A.PANEL_MARGIN)
for lang in ("English", "Русский"):
    app.lang_var.set(lang)
    app.setup_ui()
    root.update_idletasks()
    offsets = []
    for name, width, height in sizes():
        apply_size(width, height)
        column = app.frame.winfo_width()
        left = app.frame.winfo_rootx() - root.winfo_rootx()
        right = root.winfo_width() - left - column
        offsets.append(left)
        check("%s / %s: ширина колонки постоянна" % (lang, name),
              column == COLUMN, "%d при ожидаемых %d" % (column, COLUMN))
        check("%s / %s: колонка прижата влево" % (lang, name),
              left == MARGIN, "отступ слева %d при поле %d" % (left, MARGIN))
        check("%s / %s: свободное место ушло вправо" % (lang, name),
              right >= left, "слева %d справа %d" % (left, right))
        check("%s / %s: содержимое не обрезано" % (lang, name),
              app.frame.winfo_height() >= app.frame.winfo_reqheight(),
              "высота %d при требуемой %d"
              % (app.frame.winfo_height(), app.frame.winfo_reqheight()))
    # Главное утверждение задачи: при растяжении окна колонка НЕ едет.
    check("%s: отступ слева не зависит от ширины окна" % lang,
          len(set(offsets)) == 1, "по трём размерам: %s" % offsets)

# --- 2. минимальный размер ------------------------------------------------------
print()
print("=== 2. окно не сжимается ниже содержимого ===")
app.lang_var.set("English")
app.setup_ui()
root.update_idletasks()
min_w, min_h = root.minsize()
check("minsize задан", min_w > 0 and min_h > 0, "%dx%d" % (min_w, min_h))
check("minsize вмещает колонку по ширине",
      min_w >= app.frame.winfo_reqwidth(),
      "%d >= %d" % (min_w, app.frame.winfo_reqwidth()))
check("minsize вмещает содержимое по высоте",
      min_h >= app.frame.winfo_reqheight(),
      "%d >= %d" % (min_h, app.frame.winfo_reqheight()))
apply_size(100, 100)
check("попытка сжать окно ниже минимума не проходит",
      root.winfo_width() >= min_w and root.winfo_height() >= min_h,
      "получилось %dx%d" % (root.winfo_width(), root.winfo_height()))

# --- 3. единое выравнивание ------------------------------------------------------
print()
print("=== 3. выравнивание внутри колонки единое ===")
apply_size(min_w, min_h)
children = [w for w in app.frame.winfo_children() if w.winfo_manager() == "pack"]
fills = {}
for widget in children:
    info = widget.pack_info()
    fills[info.get("fill", "none")] = fills.get(info.get("fill", "none"), 0) + 1
print("   заливка у потомков колонки: %s" % fills)
# Единственное исключение -- распорка нулевой высоты, задающая ширину колонки.
check("все видимые элементы тянутся по ширине колонки",
      fills.get("x", 0) == len(children) - fills.get("none", 0)
      and fills.get("none", 0) <= 1,
      "fill=x у %d из %d" % (fills.get("x", 0), len(children)))
anchors = {w.pack_info().get("anchor", "center") for w in children}
check("якорь один на всех", len(anchors) == 1, str(anchors))
labels = [w for w in children if isinstance(w, A.ttk.Label)]
bad = [w.cget("text")[:20] for w in labels if str(w.cget("anchor")) != "w"]
check("текст меток прижат влево", not bad, str(bad))
check("подпись выпадающих списков тоже влево",
      "Left.TMenubutton" in SRC and "_stick_label_west" in SRC)

# --- 4. кнопка не во всю ширину экрана -------------------------------------------
print()
print("=== 4. кнопка STOP живёт в колонке ===")
apply_size(root.winfo_screenwidth(), min_h)
btn = app.btn_toggle.winfo_width()
check("ширина кнопки равна колонке минус поля", btn <= COLUMN,
      "кнопка %d, колонка %d, окно %d" % (btn, COLUMN, root.winfo_width()))
check("кнопка много уже окна", btn < root.winfo_width() / 2,
      "%d против %d" % (btn, root.winfo_width()))
check("и стоит в левой четверти экрана",
      app.btn_toggle.winfo_rootx() - root.winfo_rootx() < root.winfo_width() / 4,
      "левый край кнопки %d при ширине окна %d"
      % (app.btn_toggle.winfo_rootx() - root.winfo_rootx(), root.winfo_width()))

# --- 5. блок статуса -- часть колонки ---------------------------------------------
print()
print("=== 5. блок статуса не отдельный хвост ===")
for name in ("hz_label", "rate_label", "wheel_label", "faults_label",
             "suspect_label", "dc_note", "log_status"):
    widget = getattr(app, name)
    check("%s -- потомок колонки" % name,
          widget.winfo_parent() == app.frame.winfo_pathname(app.frame.winfo_id()),
          widget.winfo_parent())
check("строки статуса выровнены как остальное",
      all(str(getattr(app, n).cget("anchor")) == "w"
          for n in ("hz_label", "rate_label", "wheel_label", "log_status")))

# --- 6. что вернулось в панель ------------------------------------------------------
print()
print("=== 6. потолок снят: показания вернулись в панель ===")
check("строка периода в панели постоянна",
      app.rate_label.winfo_manager() == "pack")
check("строка колеса вернулась в панель",
      app.wheel_label.winfo_manager() == "pack")
check("счётчик потерь остался условным",
      app.dropped_label.winfo_manager() == "" and app.slot_shows is None,
      "%r / %s" % (app.dropped_label.winfo_manager(), app.slot_shows))
app.dropped_events = 5
app.update_live_labels()
root.update_idletasks()
check("при потерях строка появляется", app.slot_shows == "dropped")
check("и содержимое по-прежнему помещается",
      root.minsize()[1] >= app.frame.winfo_reqheight(),
      "minsize %d при требуемых %d"
      % (root.minsize()[1], app.frame.winfo_reqheight()))
app.dropped_events = 0
app.update_live_labels()
check("потери ушли -- строка убралась", app.slot_shows is None)

# --- 7. зашитого потолка больше нет --------------------------------------------------
print()
print("=== 7. фиксированной высоты в коде не осталось ===")
check("geometry не задаёт зашитый размер", 'geometry(f"{px(380)}x{px(850)}")' not in SRC)
check("размер окна берётся из содержимого",
      "winfo_reqheight()" in SRC.split("def fit_window")[1].split("\n    def ")[0])
check("PANEL_WIDTH объявлен константой", isinstance(A.PANEL_WIDTH, int))
# Столбец 0 держит ширину, столбец 1 забирает избыток.
check("колонка с контентом в столбце 0",
      "self.frame.grid(row=0, column=0" in SRC)
check("избыток ширины уходит в столбец справа",
      "root.grid_columnconfigure(0, weight=0)" in SRC
      and "root.grid_columnconfigure(1, weight=1)" in SRC)
check("третьего столбца больше нет",
      "grid_columnconfigure(2" not in SRC)

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
app.shutdown()
sys.exit(0 if all(ok) else 1)
