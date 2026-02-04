import tkinter as tk
from tkinter import ttk
import time
import math
import threading
import wmi
import pystray
from PIL import Image, ImageDraw, ImageFont
from pynput import mouse
import win32api
import win32con

SKINS = {
    "Dark (Стандарт)": {"bg": "#1e1e1e", "pos_fg": "#ecf0f1", "accel_fg": "#2ecc71", "vect_fg": "#3498db", "alpha": 0.8},
    "Cyberpunk": {"bg": "#000000", "pos_fg": "#f1c40f", "accel_fg": "#ff00ff", "vect_fg": "#00ffff", "alpha": 0.85},
    "Matrix": {"bg": "#000000", "pos_fg": "#00ff00", "accel_fg": "#008f11", "vect_fg": "#003b00", "alpha": 0.7}
}

class MouseHardware:
    @staticmethod
    def get_mouse_info():
        try:
            c = wmi.WMI()
            mice = c.Win32_PointingDevice()
            info = []
            for m in mice:
                info.append(f"{m.Manufacturer} {m.Name}")
            return ", ".join(info) if info else "Generic Mouse"
        except: return "Generic Mouse"

    @staticmethod
    def get_system_dpi_setting():
        try: return win32api.SystemParametersInfo(win32con.SPI_GETMOUSESPEED)
        except: return "N/A"

class FloatingTracker(tk.Toplevel):
    def __init__(self, parent, skin_config, show_config):
        super().__init__(parent)
        self.config_data = skin_config
        self.show_config = show_config # Словарь с флагами видимости
        
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", self.config_data["alpha"])
        self.configure(bg=self.config_data["bg"])
        
        font_style = ("Consolas", 9, "bold")
        
        # Создаем только те элементы, которые выбрал пользователь
        if self.show_config['pos']:
            self.label_pos = tk.Label(self, text="XY: 0, 0", fg=self.config_data["pos_fg"], bg=self.config_data["bg"], font=font_style)
            self.label_pos.pack(fill="x")
        
        if self.show_config['accel']:
            self.label_accel = tk.Label(self, text="A: 0", fg=self.config_data["accel_fg"], bg=self.config_data["bg"], font=font_style)
            self.label_accel.pack(fill="x")
        
        if self.show_config['hz']:
            self.label_hz = tk.Label(self, text="Rate: 0Hz", fg="#e74c3c", bg=self.config_data["bg"], font=font_style)
            self.label_hz.pack(fill="x")

        # Автоматический расчет высоты в зависимости от количества элементов
        active_count = sum(1 for v in self.show_config.values() if v)
        height = max(20, active_count * 20)
        self.geometry(f"105x{height}")
        
        self.last_x, self.last_y = 0, 0
        self.last_time = time.time()
        self.last_velocity = 0
        self.event_times = []
        self.hz = 0
        self.current_accel = 0
        
        # Уменьшенный отступ от курсора
        self.offset = 10 

    def update_data(self, x, y):
        now = time.time()
        dt = now - self.last_time
        self.event_times.append(now)
        self.event_times = [t for t in self.event_times if now - t < 1.0]
        self.hz = len(self.event_times)
        
        if dt > 0.005:
            dx, dy = x - self.last_x, y - self.last_y
            dist = math.sqrt(dx**2 + dy**2)
            vel = dist / dt
            new_accel = (vel - self.last_velocity) / dt
            self.current_accel = self.current_accel * 0.7 + new_accel * 0.3
            
            try:
                if self.show_config['pos']: self.label_pos.config(text=f"XY: {int(x)}, {int(y)}")
                if self.show_config['accel']: self.label_accel.config(text=f"A: {abs(int(self.current_accel)):>5}")
                if self.show_config['hz']: self.label_hz.config(text=f"Rate: {self.hz}Hz")
                
                # Позиционирование ближе к курсору
                self.geometry(f"+{int(x) + self.offset}+{int(y) + self.offset}")
            except: pass
            
            self.last_x, self.last_y = x, y
            self.last_time, self.last_velocity = now, vel

class MainControlPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("Mouse Monitor Pro")
        self.root.geometry("380x520")
        
        self.tracker = None
        self.current_hz = 0
        
        # Переменные настроек отображения
        self.show_pos = tk.BooleanVar(value=True)
        self.show_accel = tk.BooleanVar(value=True)
        self.show_hz = tk.BooleanVar(value=True)
        
        # Интерфейс
        frame = ttk.Frame(root, padding="15")
        frame.pack(expand=True, fill="both")
        
        ttk.Label(frame, text="ИНФОРМАЦИЯ О ЖЕЛЕЗЕ", font=("Segoe UI", 10, "bold")).pack(pady=5)
        self.hw_info = MouseHardware.get_mouse_info()
        self.sys_speed = MouseHardware.get_system_dpi_setting()
        
        self.info_text = tk.Text(frame, height=4, font=("Consolas", 9), bg="#f0f0f0")
        self.update_info_display()
        self.info_text.pack(fill="x", pady=5)
        
        # Секция настроек отображения
        ttk.Label(frame, text="НАСТРОЙКИ ОТОБРАЖЕНИЯ", font=("Segoe UI", 10, "bold")).pack(pady=(15, 5))
        ttk.Checkbutton(frame, text="Показывать координаты (XY)", variable=self.show_pos).pack(anchor="w")
        ttk.Checkbutton(frame, text="Показывать ускорение (A)", variable=self.show_accel).pack(anchor="w")
        ttk.Checkbutton(frame, text="Показывать частоту (Hz)", variable=self.show_hz).pack(anchor="w")
        
        ttk.Label(frame, text="ВЫБОР СКИНА:", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(15, 5))
        self.skin_var = tk.StringVar(value="Dark (Стандарт)")
        self.skin_menu = ttk.OptionMenu(frame, self.skin_var, "Dark (Стандарт)", *SKINS.keys())
        self.skin_menu.pack(fill="x")
        
        self.btn_toggle = ttk.Button(frame, text="ЗАПУСТИТЬ МОНИТОРИНГ", command=self.toggle_tracker)
        self.btn_toggle.pack(fill="x", pady=20)

        self.hz_label = ttk.Label(frame, text="Частота USB: 0 Hz", font=("Segoe UI", 10))
        self.hz_label.pack()

        # Трей и слушатель
        self.icon = None
        threading.Thread(target=self.setup_tray, daemon=True).start()
        self.listener = mouse.Listener(on_move=self.on_mouse_move)
        self.listener.start()
        self.update_tray_loop()

    def update_info_display(self):
        self.info_text.config(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("1.0", f"Устройство: {self.hw_info}\n")
        self.info_text.insert("end", f"Win Speed: {self.sys_speed}/20")
        self.info_text.config(state="disabled")

    def on_mouse_move(self, x, y):
        if self.tracker:
            self.tracker.update_data(x, y)
            self.current_hz = self.tracker.hz
            self.root.after(0, lambda: self.hz_label.config(text=f"Частота USB: {self.current_hz} Hz"))

    def toggle_tracker(self):
        if self.tracker is None:
            skin = SKINS.get(self.skin_var.get(), SKINS["Dark (Стандарт)"])
            # Формируем конфиг видимости
            show_config = {
                'pos': self.show_pos.get(),
                'accel': self.show_accel.get(),
                'hz': self.show_hz.get()
            }
            if not any(show_config.values()): # Если ничего не выбрано, не запускаем
                return
                
            self.tracker = FloatingTracker(self.root, skin, show_config)
            self.btn_toggle.config(text="ОСТАНОВИТЬ")
        else:
            self.tracker.destroy()
            self.tracker = None
            self.btn_toggle.config(text="ЗАПУСТИТЬ МОНИТОРИНГ")

    def create_dynamic_icon(self, text):
        img = Image.new('RGB', (64, 64), color=(20, 20, 20))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], outline=(46, 204, 113), width=4)
        try: font = ImageFont.truetype("arial.ttf", 28)
        except: font = ImageFont.load_default()
        text_str = str(text)
        w = len(text_str) * 14
        d.text(((64-w)//2 + 4, 15), text_str, fill=(255, 255, 255), font=font)
        return img

    def setup_tray(self):
        self.icon = pystray.Icon("mouse_pro", self.create_dynamic_icon(0), "Mouse Monitor")
        self.icon.menu = pystray.Menu(
            pystray.MenuItem("Развернуть", lambda: self.root.after(0, self.root.deiconify)),
            pystray.MenuItem("Выход", self.exit_app)
        )
        self.icon.run()

    def update_tray_loop(self):
        if self.icon and self.icon.visible:
            self.icon.icon = self.create_dynamic_icon(self.current_hz)
        self.root.after(500, self.update_tray_loop)

    def exit_app(self, icon):
        icon.stop()
        self.root.after(0, self.root.destroy)

if __name__ == "__main__":
    root = tk.Tk()
    app = MainControlPanel(root)
    root.mainloop()
