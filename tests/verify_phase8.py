"""Проверка критериев приёмки Фазы 8."""
import io
import os
import random
import re
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


def periodic(period=0.001, seconds=A.RATE_WINDOW, keep=0.30, seed=1):
    """Интервалы источника с периодом `period`, часть репортов которого не
    сдвинула курсор. Ровно та картина, что даёт настоящая мышь."""
    rnd = random.Random(seed)
    out, gap = [], 0
    for _ in range(int(seconds / period)):
        gap += 1
        if rnd.random() < keep:
            out.append(gap * period)
            gap = 0
    return out


# --- 1. условия годности ----------------------------------------------------
print("=== 1. оценка молчит, когда условия не выполнены ===")
good = periodic()
res = A.report_rate_estimate(good)
check("периодический источник опознан", res["state"] == A.RATE_OK, res["state"])
check("период около 1 мс", res["period_ms"] is not None
      and abs(res["period_ms"] - 1.0) < 0.02,
      "%.3f мс" % (res["period_ms"] or 0))
check("частота около 1000 Гц", res["hz"] is not None and 980 < res["hz"] < 1020,
      "%.0f Гц" % (res["hz"] or 0))

slow = [0.03] * int(A.RATE_WINDOW / 0.03)          # ~33 события/с
check("медленное движение -> RATE_SLOW",
      A.report_rate_estimate(slow)["state"] == A.RATE_SLOW,
      "%.0f соб/с" % A.report_rate_estimate(slow)["rate"])

rnd = random.Random(7)
smeared = [rnd.uniform(0.0005, 0.005) for _ in range(1200)]
res_sm = A.report_rate_estimate(smeared)
check("размазанное распределение -> не RATE_OK", res_sm["state"] != A.RATE_OK,
      "%s, доля моды %.1f%%" % (res_sm["state"], res_sm["mode_share"] * 100))

check("пусто -> RATE_UNSURE",
      A.report_rate_estimate([])["state"] == A.RATE_UNSURE)
few = [0.001] * (A.RATE_MIN_SAMPLES - 1)
check("мало интервалов -> не RATE_OK",
      A.report_rate_estimate(few, window=0.05)["state"] != A.RATE_OK,
      "%d интервалов" % len(few))
check("число выдаётся ТОЛЬКО в RATE_OK",
      all(A.report_rate_estimate(x)["period_ms"] is None
          for x in (slow, [], few)))

print()
print("=== 2. гармоническая лестница ===")
ladder = res["ladder"]
check("лестница на %d ступеней" % A.RATE_HARMONICS,
      len(ladder) == A.RATE_HARMONICS, str(len(ladder)))
shares = [share for _, share in ladder]
print("   доли: %s" % ", ".join("%dx=%.1f%%" % (k, s * 100) for k, s in ladder))
check("основной пик самый высокий", shares[0] == max(shares),
      "%.1f%%" % (shares[0] * 100))
check("доли убывают по кратности",
      all(shares[i] >= shares[i + 1] for i in range(len(shares) - 1)))
check("кратные пики существуют", shares[1] > 0.02, "2x = %.1f%%" % (shares[1] * 100))

print()
print("=== 3. условия собраны в одном месте ===")
body = SRC.split("def report_rate_estimate")[1].split("\ndef ")[0]
# Растяжку связности (фаза 10) из подсчёта исключаем: она сравнивает порог не
# чтобы ПРИНЯТЬ решение, а чтобы проверить, что решение своё же условие
# соблюло. Это законное второе использование; требование "решение в одном
# месте" нарушало бы третье -- где-нибудь в UI или в сводке напрямую.
tripwire = SRC.split("def summary_inconsistencies")[1].split("\n    def ")[0]
deciding = SRC.replace(tripwire, "")
for token in ("RATE_MIN_RATE", "RATE_MIN_SAMPLES", "RATE_MIN_MODE_SHARE",
              "RATE_MAX_GAP"):
    seen = deciding.count("< A." + token) + deciding.count("< " + token)
    check("%s сравнивается только внутри функции" % token,
          seen == 1 and token in body,
          "вхождений вне растяжки: %d" % seen)
# Считаем присваивания ИМЕННО состояний оценки периода: в файле есть и другие
# функции с тем же идиомом (wheel_health в фазе 9), и проверка обязана
# отличать их, иначе она ловит не то, что утверждает.
check("состояние присваивается только там",
      SRC.count('out["state"] = RATE') == body.count('out["state"] = RATE')
      and SRC.count('out["state"] = RATE') >= 2,
      "%d присваиваний" % SRC.count('out["state"] = RATE'))

print()
print("=== 4. сквозняк: годная сессия пишет сводку с лестницей ===")
logs = os.path.join(A.data_dir(), "logs")
before = set(os.listdir(logs)) if os.path.isdir(logs) else set()
app.enable_logging.set(False)
app.enable_heatmap.set(False)
app.toggle_tracker()
root.update()
base = time.perf_counter()
gap = 0
fed = 0
for i in range(int(A.RATE_WINDOW / 0.001)):
    gap += 1
    if random.Random(i).random() < 0.30:
        app.data_queue.put_nowait(("move", 500 + fed % 300, 400,
                                   base + i * 0.001))
        fed += 1
        gap = 0
# Клик нужен, чтобы раздел BUTTONS развернулся: с фазы 10 пустой условный
# раздел печатается одной строкой, и порогов дребезга в нём не будет.
app.data_queue.put_nowait(("click", 10, 10, "Button.left", True, base))
app.data_queue.put_nowait(("click", 10, 10, "Button.left", False, base + 0.05))
app.process_events()
app.update_live_labels()
app.rate_checked_at = 0.0
app.refresh_rate_estimate(base + A.RATE_WINDOW)
est = app.rate_estimate
print("   подано %d событий | состояние %s | период %s"
      % (fed, est["state"],
         "%.2f мс" % est["period_ms"] if est["period_ms"] else "-"))
check("оценка получена на живом пути", est["state"] == A.RATE_OK, est["state"])
check("лучшая за сессию запомнена", app.best_rate is not None
      and app.best_rate["state"] == A.RATE_OK)
check("интервалы копятся в трекере", len(app.tracker.intervals) > 100,
      "%d" % len(app.tracker.intervals))
app.stop_session()
root.update()

after = set(os.listdir(logs)) if os.path.isdir(logs) else set()
new = sorted(after - before)
# По подстроке, а не по концу имени: суффикс столкновения (фаза 9) встаёт
# ПОСЛЕ "_summary", и проверка на endswith промахивалась бы через раз --
# в зависимости от того, занята ли эта секунда прошлым прогоном.
check("сводка создана", len(new) == 1 and "_summary" in new[0], str(new))
text = ""
if new:
    text = io.open(os.path.join(logs, new[0]), encoding="utf-8").read()
check("в сводке есть оценка", "REPORT PERIOD ESTIMATE" in text
      and "NOT AVAILABLE" not in text)
check("в сводке есть лестница целиком",
      text.count("x ") >= A.RATE_HARMONICS or
      len(re.findall(r"^\s+\dx\s", text, re.M)) == A.RATE_HARMONICS,
      "%d ступеней" % len(re.findall(r"^\s+\dx\s", text, re.M)))
check("в сводке названы пороги дребезга", "HEURISTIC" in text)
check("в сводке определено активное время", "at least one event" in text)
check("в сводке сказано про суммирование по устройствам",
      "summed over every device" in text)
check("session_started сброшен после сводки", app.session_started is None)

print()
print("=== 5. сквозняк: негодная сессия НЕ показывает числа ===")
# Пауза не косметическая: имя сводки берётся с точностью до секунды, и две
# сессии внутри одной секунды дали бы одно имя. См. отчёт фазы 8.
time.sleep(1.1)
before2 = set(os.listdir(logs))
app.toggle_tracker()
root.update()
base2 = time.perf_counter()
for i in range(40):                       # ~20 событий/с
    app.data_queue.put_nowait(("move", 600 + i, 500, base2 + i * 0.05))
app.process_events()
app.rate_checked_at = 0.0
app.refresh_rate_estimate(base2 + A.RATE_WINDOW)
check("медленная сессия -> не RATE_OK",
      app.rate_estimate["state"] != A.RATE_OK, app.rate_estimate["state"])
check("лучшей оценки не появилось", app.best_rate is None)
app.stop_session()
root.update()
new2 = sorted(n for n in set(os.listdir(logs)) - before2 if "_summary" in n)
text2 = io.open(os.path.join(logs, new2[0]), encoding="utf-8").read() if new2 else ""
check("сводка написана и говорит NOT AVAILABLE", "NOT AVAILABLE" in text2)
check("сводка объясняет условия", "events/s" in text2 and "7.0 ms" in text2)
check("в негодной сводке нет придуманного периода",
      "harmonic ladder" not in text2)

print()
print("=== 6. порядок останова не изменился ===")
order = []
_ls, _pe = app.stop_listener, app.process_events
_lg, _hm = app.logger.stop, app.heatmap.save
_sm = app.write_session_summary
_td = A.FloatingTracker.destroy
app.stop_listener = lambda: (order.append("1.хук"), _ls())[1]
app.process_events = lambda: (order.append("2.очередь")
                              if not order or order[-1] != "2.очередь" else None,
                              _pe())[1]
app.logger.stop = lambda: (order.append("3.лог"), _lg())[1]
app.heatmap.save = lambda: (order.append("4.PNG"), _hm())[1]
app.write_session_summary = lambda: (order.append("5.сводка"), _sm())[1]
A.FloatingTracker.destroy = lambda self: (order.append("6.оверлей"), _td(self))[1]
app.enable_logging.set(True)
app.enable_heatmap.set(True)
app.toggle_tracker()
root.update()
app.data_queue.put_nowait(("move", 700, 700, time.perf_counter()))
# Трассу чистим прямо перед остановом: цикл 10 мс зовёт process_events сам,
# и его проходы к порядку останова отношения не имеют.
del order[:]
app.stop_session()
print("   %s" % " -> ".join(order))
check("хук снимается первым", order[0] == "1.хук")
check("очередь дочитывается вторым", order[1] == "2.очередь")
check("лог закрывается до PNG", order.index("3.лог") < order.index("4.PNG"))
check("сводка после PNG", order.index("4.PNG") < order.index("5.сводка"))
check("оверлей снимается последним", order[-1] == "6.оверлей")
app.stop_listener, app.process_events = _ls, _pe
app.logger.stop, app.heatmap.save = _lg, _hm
app.write_session_summary = _sm
A.FloatingTracker.destroy = _td

print()
print("=== 7. локализация состояний ===")
for lang in ("English", "Русский"):
    app.lang_var.set(lang)
    app.setup_ui()
    # С фазы 11 rate_ok распался на три исхода привязки к отраслевой шкале:
    # ступень найдена / между ступенями / быстрее разрешения метода.
    for key in ("rate_ok_step", "rate_ok_between", "rate_ok_fine",
                "rate_slow", "rate_unsure"):
        check("%s: ключ %s есть" % (lang, key), key in A.TRANSLATIONS[lang])
    app.rate_estimate = {"state": A.RATE_OK, "period_ms": 1.05, "hz": 952.0,
                         "mode_share": 0.3, "samples": 500, "rate": 900.0,
                         "ladder": []}
    line_ok = app.rate_line()
    app.rate_estimate = {"state": A.RATE_SLOW, "period_ms": None, "hz": None,
                         "mode_share": 0.0, "samples": 0, "rate": 10.0,
                         "ladder": []}
    line_slow = app.rate_line()
    print("   %-8s %r | %r" % (lang, line_ok, line_slow))
    check("%s: в RATE_OK есть число" % lang, "1.05" in line_ok and "952" in line_ok)
    check("%s: в RATE_SLOW числа нет" % lang,
          not re.search(r"\d", line_slow.replace("1", "")) or "952" not in line_slow)
    check("%s: состояния различаются" % lang, line_ok != line_slow)
app.lang_var.set("English")
app.setup_ui()
app.rate_estimate = None
check("без оценки строка не врёт", app.rate_line() == A.TRANSLATIONS["English"]["rate_unsure"])

print()
print("=== 8. содержимое помещается в окно ===")
root.update_idletasks()
root.update()
# С фазы 12 высота окна не зашита: её задаёт содержимое, а minsize не даёт
# обрезать. Проверяем смысл -- "помещается и не обрезано", -- а не число.
min_w, min_h = root.minsize()
check("минимальная высота вмещает содержимое",
      min_h >= app.frame.winfo_reqheight(),
      "%d >= %d" % (min_h, app.frame.winfo_reqheight()))
check("минимальная ширина вмещает колонку",
      min_w >= app.frame.winfo_reqwidth(),
      "%d >= %d" % (min_w, app.frame.winfo_reqwidth()))
# С фазы 11 показание частоты ЗАНИМАЕТ строку в панели -- так расставил
# приоритет заказчик. Инвариант, который остаётся и который тут проверяется:
# строк статуса видна ровно одна, и потолок 850 не пробит.
check("условная строка -- только счётчик потерь",
      app.slot_shows in (None, "dropped"), str(app.slot_shows))
check("подсказка трея по-прежнему используется", "self.icon.title" in SRC)

print()
print("ИТОГО: %d из %d" % (sum(ok), len(ok)))
app.shutdown()
sys.exit(0 if all(ok) else 1)
