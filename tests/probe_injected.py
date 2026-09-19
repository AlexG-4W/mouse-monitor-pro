import threading, time
import win32api, win32con
from pynput import mouse

start = win32api.GetCursorPos()
errs = []
threading.excepthook = lambda a: errs.append(repr(a.exc_value))

def run(label, callback, collector):
    lst = mouse.Listener(on_move=callback)
    lst.start(); lst.wait(); time.sleep(0.25)
    for i in range(6):
        win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, 1 if i % 2 == 0 else -1, 0, 0, 0)
        time.sleep(0.04)
    time.sleep(0.3)
    lst.stop()
    print("  %-42s событий=%d  %s" % (label, len(collector),
          ("injected=" + str(sorted({e[-1] for e in collector}))) if collector and len(collector[0])==3 else ""))
    collector.clear()

a = []
run("def on_move(x, y, injected)          ", lambda x, y, injected: a.append((x, y, injected)), a)
b = []
run("def on_move(x, y)                    ", lambda x, y: b.append((x, y)), b)
c = []
def with_default(x, y, injected=False): c.append((x, y, injected))
run("def on_move(x, y, injected=False)    ", with_default, c)

win32api.SetCursorPos(start)
print()
print("исключений в потоке хука:", errs or "нет")
print("прямой вызов with_default(10, 20) в обход хука ->", (with_default(10, 20), c[-1])[1])
