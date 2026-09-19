"""Проверка критериев приёмки Фазы 10."""
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


def run_session(feed=None, logging_on=False, heatmap_on=False, tweak=None):
    """Прогоняет сессию и возвращает текст её сводки."""
    app.enable_logging.set(logging_on)
    app.enable_heatmap.set(heatmap_on)
    app.toggle_tracker()
    root.update()
    if feed:
        feed()
        app.process_events()
        # Цикл 10 мс тоже прокручиваем: без него не обновятся пики, и сводка
        # честно доложит о противоречии "события есть, пик ноль". Проверка
        # связности поймала это на самом стенде -- пусть стенд ведёт себя как
        # боевой цикл, а не как его половина.
        app.update_live_labels()
    if tweak:
        tweak()
    before = set(os.listdir(LOGS)) if os.path.isdir(LOGS) else set()
    app.stop_session()
    root.update()
    fresh = [n for n in set(os.listdir(LOGS)) - before if "_summary" in n]
    if not fresh:
        return ""
    return io.open(os.path.join(LOGS, fresh[0]), encoding="utf-8").read()


# --- 1. шапка опознания -------------------------------------------------------
print("=== 1. шапка: от какой сборки этот файл ===")
text = run_session()
header = text.split("\n")[1] if text else ""
print("   %s" % header)
check("версия формата сводки", "summary format v%d" % A.SUMMARY_FORMAT_VERSION
      in header, header)
check("версия приложения", "app v%s" % A.APP_VERSION in header)
check("версия формата CSV", "CSV format v%d" % A.CSV_FORMAT_VERSION in header)
check("сборка: EXE или из исходника",
      "frozen EXE" in header or "from source" in header)
check("версия Python", "Python %d.%d" % sys.version_info[:2] in header)
check("шапка -- вторая строка, до разделителя",
      text.split("\n")[0].startswith("MouseMonitorPro"))

# --- 2. порядок разделов ------------------------------------------------------
print()
print("=== 2. порядок: сперва то, что есть почти всегда ===")
order = ["SESSION", "REPORT PERIOD ESTIMATE", "BUTTONS", "SCROLL WHEEL",
         "QUEUE AND FILTERING", "POINTER SETTINGS", "FILES"]
positions = [text.find(name) for name in order]
print("   %s" % " -> ".join(order))
check("все разделы на месте", all(pos >= 0 for pos in positions),
      str([name for name, pos in zip(order, positions) if pos < 0]))
check("порядок возрастающий",
      positions == sorted(positions), str(positions))
check("оценка периода выше кликов",
      text.find("REPORT PERIOD") < text.find("BUTTONS"))
check("колесо ниже оценки периода",
      text.find("REPORT PERIOD") < text.find("SCROLL WHEEL"))

# --- 3. пустые условные разделы -- одной строкой -------------------------------
print()
print("=== 3. пустой условный раздел -- одна строка, а не блок ===")


def block(body, name):
    start = body.find(name)
    if start < 0:
        return []
    rest = body[start:].split("\n")[2:]
    out = []
    for line in rest:
        if not line.strip():
            break
        out.append(line)
    return out


check("пустой BUTTONS -- одна строка", len(block(text, "BUTTONS")) == 1,
      str(block(text, "BUTTONS")))
check("пустой SCROLL WHEEL -- одна строка",
      len(block(text, "SCROLL WHEEL")) == 1, str(block(text, "SCROLL WHEEL")))
check("пустой QUEUE -- одна строка",
      len(block(text, "QUEUE AND FILTERING")) == 1,
      str(block(text, "QUEUE AND FILTERING")))
check("раздел не выброшен, а назван", "no clicks in this session" in text
      and "no scrolling in this session" in text)

# --- 4. чистая сводка молчит ---------------------------------------------------
print()
print("=== 4. без противоречий -- ни строчки об этом ===")
check("нет раздела INCONSISTENCIES", "INCONSISTENCIES" not in text)
check("нет строк inconsistency:", "inconsistency:" not in text)
check("нет самопохвалы 'all consistent'",
      "all consistent" not in text.lower())

# --- 5. каждое противоречие ловится --------------------------------------------
print()
print("=== 5. противоречия ловятся поимённо ===")
app.toggle_tracker()
root.update()
health_none = A.wheel_health(0, 0, 0)


def only(found, needle):
    return [f for f in found if needle in f]


app.total_moves = 500
app.peak_hz = 0
found = app.summary_inconsistencies(health_none, None)
check("пик 0 при ненулевых событиях", only(found, "peak event rate is 0"),
      str(only(found, "peak event rate is 0")))
app.total_moves = 0

app.logger.filename = os.path.join(LOGS, "probe_exists.csv")
io.open(app.logger.filename, "w", encoding="utf-8").write("x")
app.session_csv = None
found = app.summary_inconsistencies(health_none, None)
check("csv 'not enabled' при существующем файле",
      only(found, "csv reported as not enabled"),
      str(only(found, "csv reported as not enabled")))
os.remove(app.logger.filename)
app.logger.filename = ""

app.heatmap.data = {(1, 1): 5}
app.session_png = None
found = app.summary_inconsistencies(health_none, None)
check("heatmap 'not enabled' при собранных ячейках",
      only(found, "heatmap reported as not enabled"))
app.heatmap.data = {}

thin = {"state": A.RATE_OK, "period_ms": 1.0, "hz": 1000.0, "mode_share": 0.9,
        "samples": A.RATE_MIN_SAMPLES - 1, "rate": 900.0, "ladder": []}
found = app.summary_inconsistencies(health_none, thin)
check("оценка периода ниже порога интервалов",
      only(found, "below the"), str(only(found, "below the")))

app.tracker.fault_counts["left"] = 3
app.total_clicks = 0
found = app.summary_inconsistencies(health_none, None)
check("дребезг при нуле кликов", only(found, "with no clicks recorded"),
      str(only(found, "with no clicks recorded")))
app.tracker.fault_counts["left"] = 0

found = app.summary_inconsistencies(A.wheel_health(0, 0, 2), None)
check("реверсы колеса при нуле тиков",
      only(found, "wheel reversals counted with no wheel ticks"))

app.active_seconds = set(range(400))
found = app.summary_inconsistencies(health_none, None)
check("активное время больше длительности", only(found, "exceeds session"),
      str(only(found, "exceeds session")))
app.active_seconds = set()

found = app.summary_inconsistencies(health_none, None)
check("на согласованном состоянии -- пусто", found == [], str(found))
app.stop_session()
root.update()

# --- 6. противоречие доезжает до файла ------------------------------------------
print()
print("=== 6. противоречие печатается в самом файле ===")


def make_contradiction():
    app.total_moves = 777
    app.peak_hz = 0


bad = run_session(tweak=make_contradiction)
check("раздел INCONSISTENCIES появился", "INCONSISTENCIES" in bad)
check("строка вида 'inconsistency: ...'", "inconsistency: peak event rate is 0"
      in bad, [l for l in bad.split("\n") if l.startswith("inconsistency")])
check("файл предупреждает, что числам верить нельзя",
      "not trustworthy" in bad or "contradicts itself" in bad)
check("раздел стоит в конце",
      bad.find("INCONSISTENCIES") > bad.find("FILES"))

# --- 7. проверка связности -- в одном месте --------------------------------------
print()
print("=== 7. связность проверяется в одном месте ===")
body = SRC.split("def summary_inconsistencies")[1].split("\n    def ")[0]
check("все проверки внутри функции",
      SRC.count('found.append(') == body.count('found.append('),
      "%d добавлений" % SRC.count("found.append("))
check("функция зовётся из сводки один раз",
      SRC.count("self.summary_inconsistencies(") == 1)
check("проверок не меньше шести", body.count("found.append(") >= 6,
      "%d" % body.count("found.append("))

# --- 8. счётчик кликов ------------------------------------------------------------
print()
print("=== 8. клики считаются, и только нажатия ===")


def feed_clicks():
    now = time.perf_counter()
    for i in range(4):
        app.data_queue.put_nowait(("click", 10, 10, "Button.left", True,
                                   now + i * 0.2))
        app.data_queue.put_nowait(("click", 10, 10, "Button.left", False,
                                   now + i * 0.2 + 0.05))


clicked = run_session(feed=feed_clicks)
check("нажатия посчитаны, отпускания нет", "clicks         : 4" in clicked,
      [l for l in clicked.split("\n") if l.startswith("clicks")])
check("раздел BUTTONS развернулся", len(block(clicked, "BUTTONS")) > 1,
      "%d строк" % len(block(clicked, "BUTTONS")))
check("и в нём нет противоречий", "inconsistency:" not in clicked)

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
app.shutdown()
sys.exit(0 if all(ok) else 1)
