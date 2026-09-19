"""Снимок окна приложения. ТОЛЬКО PrintWindow -- BitBlt с экрана запрещён.
Закрытие ТОЛЬКО через WM_CLOSE с ожиданием процесса-владельца окна."""
import subprocess, sys, time, os, ctypes
import win32gui, win32ui, win32con, win32process
from PIL import Image

_u = ctypes.windll.user32
_u.SetProcessDpiAwarenessContext.restype = ctypes.c_int
_u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
_u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

WINDOW_PREFIX = "Mouse Monitor Pro"


def find_window():
    """Окно приложения по ПРЕФИКСУ заголовка.

    Точное совпадение не годится: с версии 3.1 заголовок несёт номер сборки
    ("Mouse Monitor Pro v3.1"), и FindWindow по старой строке возвращал 0.
    Префикс переживает подъём версии.
    """
    found = []

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title.startswith(WINDOW_PREFIX):
                found.append(hwnd)

    win32gui.EnumWindows(visit, None)
    return found[0] if found else 0


target, out = sys.argv[1], sys.argv[2]
cwd = sys.argv[3] if len(sys.argv) > 3 else None
cmd = [target] if target.lower().endswith(".exe") else [sys.executable, target]
proc = subprocess.Popen(cmd, cwd=cwd or os.path.dirname(target))

hwnd = 0
for _ in range(400):
    time.sleep(0.1)
    h = find_window()
    if h:
        hwnd = h
        break
assert hwnd, "окно не появилось"
print("заголовок окна: %r" % win32gui.GetWindowText(hwnd))
_, win_pid = win32process.GetWindowThreadProcessId(hwnd)
print("PID запущенного=%d | PID владельца окна=%d" % (proc.pid, win_pid))
time.sleep(2.5)

l, t, r, b = win32gui.GetWindowRect(hwnd)
w, h = r - l, b - t
src = win32ui.CreateDCFromHandle(win32gui.GetWindowDC(hwnd))
dst = src.CreateCompatibleDC()
bmp = win32ui.CreateBitmap(); bmp.CreateCompatibleBitmap(src, w, h)
dst.SelectObject(bmp)
res = ctypes.windll.user32.PrintWindow(hwnd, dst.GetSafeHdc(), 2)  # PW_RENDERFULLCONTENT
info = bmp.GetInfo(); bits = bmp.GetBitmapBits(True)
Image.frombuffer('RGB', (info['bmWidth'], info['bmHeight']), bits, 'raw', 'BGRX', 0, 1).save(out)
print("PrintWindow=%d | размер %dx%d | %s" % (res, w, h, out))
dst.DeleteDC(); src.DeleteDC(); win32gui.DeleteObject(bmp.GetHandle())

win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
hp = ctypes.windll.kernel32.OpenProcess(0x1000, False, win_pid)
code = ctypes.c_ulong(259)
for _ in range(150):
    time.sleep(0.1)
    ctypes.windll.kernel32.GetExitCodeProcess(hp, ctypes.byref(code))
    if code.value != 259:
        break
ctypes.windll.kernel32.CloseHandle(hp)
print("процесс-владелец окна завершился по WM_CLOSE: %s | код=%s"
      % (code.value != 259, code.value))
try:
    proc.wait(timeout=15)
except Exception:
    pass
