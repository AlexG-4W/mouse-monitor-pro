"""Прогоняет все регрессионные стенды и печатает сводку.

    python tests/run_all.py

Стенды создают окна Tk и на короткое время ставят настоящий хук мыши
(verify_phase3 и verify_phase4), поэтому прогон не бесшумный: на секунду
появится оверлей, а в verify_phase4 курсор сместится на несколько пикселей
и вернётся на место. Это ожидаемо.

Известное ограничение: verify_phase4 генерирует синтетические ДВИЖЕНИЯ через
mouse_event, но не клики -- синтетический клик попал бы в реальное окно.

В конце прогона сверяются ЧИСЛА В ДОКУМЕНТАЦИИ. Строка "146 проверок" в README
пережила несколько фаз и обнаружилась случайно; чтобы это не повторилось, число
наборов и число проверок теперь считаются здесь и сравниваются с тем, что
написано в README.md и docs/HANDOFF.md. Расхождение -- отказ прогона, а не
примечание мелким шрифтом.

README обязателен. HANDOFF -- НЕТ: это рабочий документ передачи сессии, и в
публичный комплект он не входит. Если его нет, сверка по нему пропускается с
явной отметкой в выводе; отсутствие файла -- не отказ.
"""
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SUITES = [
    ("Фаза 1  -- DPI, масштаб, шкала времени", "verify_phase1.py"),
    ("Фаза 2  -- except, offset, параметры указателя", "verify_phase2.py"),
    ("Фаза 3  -- жизненный цикл, потоки, очередь", "verify_phase3.py"),
    ("Фаза 3.5 -- закреплённый оверлей", "verify_phase35.py"),
    ("Фаза 4  -- дребезг, injected, сглаживание", "verify_phase4.py"),
    ("Фаза 6  -- счёт эпизодов, масштаб dV, локализация", "verify_phase6.py"),
    ("Фаза 8  -- оценка периода репортов, сводка сессии", "verify_phase8.py"),
    ("Фаза 9  -- имена артефактов, колесо и износ энкодера", "verify_phase9.py"),
    ("Фаза 10 -- сводка: порядок, шапка, самопроверка", "verify_phase10.py"),
    ("Фаза 11 -- шкала частоты, dV, системные эталоны", "verify_phase11.py"),
    ("Фаза 12 -- вёрстка, устойчивая к размеру окна", "verify_phase12.py"),
    ("Фаза 13 -- сквозная проверка живых строк панели", "verify_phase13.py"),
    ("Фаза 14 -- графики в реальном времени", "verify_phase14.py"),
    ("Фаза 15 -- живые строки в обоих состояниях", "verify_phase15.py"),
]

env = dict(os.environ, PYTHONIOENCODING="utf-8")
results = []
total_checks = 0

for title, script in SUITES:
    print("=" * 72)
    print(title)
    print("=" * 72)
    # Вывод перехватывается, чтобы посчитать проверки, и тут же печатается:
    # без этого число в документации сверять не с чем.
    proc = subprocess.run([sys.executable, os.path.join(HERE, script)],
                          cwd=ROOT, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    text = proc.stdout.decode("utf-8", "replace")
    sys.stdout.write(text)
    found = re.findall(r"ИТОГО:\s*(\d+)\s+из\s+(\d+)", text)
    if found:
        total_checks += int(found[-1][1])
    results.append((title, proc.returncode))
    print()

print("=" * 72)
print("СВОДКА")
print("=" * 72)
for title, code in results:
    print("  [%s] %s" % ("OK  " if code == 0 else "ОТКАЗ", title))
print()
print("  наборов: %d | проверок: %d" % (len(SUITES), total_checks))

# --- сверка чисел в документации ------------------------------------------------
doc_problems = []
DOCS = (
    ("README.md", r"(\d+)\s+suites,\s*(\d+)\s+checks", True),
    (os.path.join("docs", "HANDOFF.md"),
     r"(\d+)\s+наборов,\s*(\d+)\s+проверок", False),
)
for relative, pattern, required in DOCS:
    path = os.path.join(ROOT, relative)
    if not os.path.exists(path):
        if required:
            doc_problems.append("%s: обязательный файл отсутствует" % relative)
        else:
            print("  %s: файла нет -- сверка по нему пропущена (это штатно "
                  "для публичного комплекта)" % relative)
        continue
    try:
        text = io.open(path, encoding="utf-8").read()
    except OSError as error:
        doc_problems.append("%s: не прочитан (%s)" % (relative, error))
        continue
    match = re.search(pattern, text)
    if not match:
        doc_problems.append(
            "%s: не найдена строка с числом наборов и проверок "
            "(шаблон %r)" % (relative, pattern))
        continue
    suites, checks = int(match.group(1)), int(match.group(2))
    if suites != len(SUITES) or checks != total_checks:
        doc_problems.append(
            "%s: написано %d наборов и %d проверок, на деле %d и %d"
            % (relative, suites, checks, len(SUITES), total_checks))

print()
if doc_problems:
    print("  ДОКУМЕНТАЦИЯ РАЗОШЛАСЬ С КОДОМ:")
    for problem in doc_problems:
        print("    - %s" % problem)
else:
    print("  документация: числа совпадают с прогоном")

failed = [t for t, c in results if c != 0]
sys.exit(1 if failed or doc_problems else 0)
