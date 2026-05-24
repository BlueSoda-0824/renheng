import random
import json
import os
import pyautogui
import pygetwindow as gw
import time
import psutil
import ctypes
from pathlib import Path
from PySide6.QtCore import QThread, Signal

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QTime, QDateTime, QUrl, QSize
from PySide6.QtGui import QPixmap, QGuiApplication, QIntValidator
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import QToolButton, QStyle, QCheckBox
from PySide6.QtWidgets import (
    QWidget,  QListWidgetItem, QListWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout,
    QPushButton, QDialog, QLineEdit, QSizePolicy, QGraphicsOpacityEffect, QMenu
)

from PySide6.QtGui import (
    QPixmap, QGuiApplication, QIntValidator,
    QPainter, QColor, QFont, QPen, QPainterPath, QFontMetrics # <--- 补全这些组件
)
from PySide6.QtWidgets import QMenu
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtCore import QUrl

from outfit import OutfitManager

#参数
SCALE = 0.5               
EDGE_MARGIN = 6           
DRAG_THRESHOLD = 18       
TICK_MS = 175             
FLOWER_COUNT = 0
NEXT_DROPPER = "刃"
BUBBLE_OFFSET_Y = 20      
AUTO_TALK_MIN_MS = 8000   
AUTO_TALK_MAX_MS = 20000  

SPECIAL_CD_MS = 9000      
SPECIAL_DELAY_MS = 450    

COLLISION_COUNT_CD_MS = 20000 

OUTFIT_DISPLAY_NAMES = {
    "刃": {
        "base": "西装",
        "outfit_a": "常服",
        "outfit_b": "不穿衣服",
        "outfit_c": "身体链",
    },
    "丹恒": {
        "base": "丹恒",
        "outfit_a": "丹恒·饮月",
        "outfit_b": "不穿衣服",
        "outfit_c": "情趣内衣",
    }
}

try:
    from quiz import QuizEngine, QuizDialog
except Exception:
    QuizEngine = None
    QuizDialog = None

try:
    from vocab import VocabEngine, VocabDialog
except Exception:
    VocabEngine = None
    VocabDialog = None

class SupervisorThread(QThread):
    moyu_signal = Signal(str, bool) 
    
    def __init__(self, keywords, process_names):
        super().__init__()
        self.keywords = [k.lower() for k in keywords]
        self.process_names = [p.lower() for p in process_names]
        self.running = True
        self.is_active = False 
        self.paused_by_alarm = False
        self.moyu_count = 0
        self.total_moyu_seconds = 0
        self.last_move_time = time.time()
        self.slacking_start_time = None

    def _get_active_process_name(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return psutil.Process(pid.value).name().lower()
        except: return ""

    def run(self):
        last_pos = pyautogui.position()
        while self.running:
            if not self.is_active or self.paused_by_alarm:
                self.msleep(500)
                continue

            active_win = gw.getActiveWindow()
            is_working = False
            
            if active_win:
                title = active_win.title.lower()
                current_process = self._get_active_process_name()
                
                is_working = any(k in title for k in self.keywords) or \
                            any(p in current_process for p in self.process_names)

            curr_pos = pyautogui.position()
            curr_time = time.time()
            idle_sec = self._get_idle_seconds()
            should_count = (not is_working) or (idle_sec >= 3)
            
            if should_count:
                if self.slacking_start_time is None: self.slacking_start_time = curr_time
                if curr_time - self.slacking_start_time >= 60:
                    self.moyu_count += 1
                    self.total_moyu_seconds += 60
                    self.moyu_signal.emit("监测到摸鱼", True)
                    self.slacking_start_time = curr_time
            else:
                if curr_pos != last_pos:
                    last_pos = curr_pos
                    self.last_move_time = curr_time
                self.slacking_start_time = None
            
            self.msleep(500)

    def reset_stats(self):
        self.moyu_count = 0
        self.total_moyu_seconds = 0
        self.slacking_start_time = None
        self.last_move_time = time.time()

    def _get_idle_seconds(self) -> float:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)

        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)) == 0:
            return 0.0

        # GetTickCount: 系统启动以来的毫秒数
        tick = ctypes.windll.kernel32.GetTickCount()
        idle_ms = tick - lii.dwTime
        return idle_ms / 1000.0

def _load_frames(folder: Path, pattern: str, scale: float):
    files = sorted(folder.glob(pattern))
    frames = []
    for p in files:
        pm = QPixmap(str(p))
        if pm.isNull(): continue
        if scale != 1.0:
            w = max(1, int(pm.width() * scale))
            h = max(1, int(pm.height() * scale))
            pm = pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        frames.append(pm)
    return frames

def _load_dialogs(pet_asset_dir: Path):
    dialog_file = pet_asset_dir / "dialog.txt"
    dialogs = {"idle": [], "walk": [], "sleep": []}
    if not dialog_file.exists(): return dialogs
    current = None
    for raw in dialog_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"): continue
        low = line.lower()
        if low in ("[idle]", "[walk]", "[sleep]"):
            current = low[1:-1]
            continue
        if current in dialogs: dialogs[current].append(line)
    return dialogs

def _load_lines_txt(path: Path):
    if not path.exists(): return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"): continue
        lines.append(s)
    return lines

def _load_affection_dialogues(path: Path) -> dict:
    tiers = ["1-20", "21-40", "41-60", "61-80", "81-100"]
    data = {t: [] for t in tiers}
    if not path.exists(): return data
    import re
    header = re.compile(r"^\[(1-20|21-40|41-60|61-80|81-100)\]$")
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"): continue
        m = header.match(line)
        if m:
            current = m.group(1)
            continue
        if current: data[current].append(line)
    return data

class MoyuImageWindow(QWidget):
    def __init__(self, image_path, pet_instance):
        super().__init__()
        self.pet_instance = pet_instance
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.label = QLabel(self)
        pix = QPixmap(image_path)
        if not pix.isNull():
            self.label.setPixmap(pix)
            self.resize(pix.size())

        screen_rect = pet_instance.current_screen_rect()
        center_pos = screen_rect.center() - self.rect().center()
        self.move(center_pos)
        self.show()

    def mousePressEvent(self, event):
        self.pet_instance.stop_moyu_alarm() 
        self.close()

class SpeechBubble(QWidget):
    def __init__(self, pet_ref):
        super().__init__(None)  
        self.pet_ref = pet_ref
        
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.panel = QFrame(self)
        self.panel.setObjectName("panel")
        root.addWidget(self.panel)

        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(10, 8, 10, 8)

        self.label = QLabel(self.panel)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.PlainText)
        lay.addWidget(self.label)

        self.setStyleSheet("""
        QFrame#panel {
            background: rgba(20, 20, 20, 210);
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 30);
        }
        QLabel {
            color: white;
            font-size: 14px;
        }
        """)

        self.label.ensurePolished()
        fm = self.label.fontMetrics()
        char_w = fm.horizontalAdvance("中")
        FIXED_CHARS = 6                     
        label_w = char_w * FIXED_CHARS
        self.label.setFixedWidth(label_w)
        self.panel.setFixedWidth(label_w + 20)

        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.opacity.setOpacity(0.0)

        self.fade_timer = QTimer(self)
        self.fade_timer.timeout.connect(self._fade_step)
        self._target = 1.0
        self._step = 0.12

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out)

    def show_text(self, text: str, ms: int = 1800):
        self.label.setText(text)
        self.panel.adjustSize()
        self.adjustSize()

        self.update_pos()  

        self._target = 1.0
        self._step = 0.18
        self.opacity.setOpacity(0.0)

        self.show()
        self.raise_()
        
        self.fade_timer.start(16)
        
        if ms > 0:
            self.hide_timer.start(ms)
        else:
            self.hide_timer.stop()

    def update_pos(self):
        if not self.pet_ref or not self.isVisible():
            return
        
        pet_geo = self.pet_ref.geometry()
        
        target_x = pet_geo.center().x() - self.width() // 2

        target_y = pet_geo.top() - self.height() - BUBBLE_OFFSET_Y

        self.move(target_x, target_y)

    def fade_out(self):
        self._target = 0.0
        self._step = -0.12
        self.fade_timer.start(16)

    def _fade_step(self):
        v = self.opacity.opacity() + self._step
        if (self._step > 0 and v >= self._target) or (self._step < 0 and v <= self._target):
            v = self._target
            self.fade_timer.stop()
            if v <= 0.0:
                self.hide()
        self.opacity.setOpacity(max(0.0, min(1.0, v)))

class AffectionDialog(QDialog):
    def __init__(self, parent=None, current: int = 1):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(self)
        panel.setObjectName("panel")
        root.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        
        title = QLabel("调节好感度", panel)
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        hint = QLabel("输入 1–100", panel)
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)

        self.edit = QLineEdit(panel)
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.setText(str(int(current)))
        self.edit.setValidator(QIntValidator(1, 100, self))
        lay.addWidget(self.edit)

        btns = QHBoxLayout()
        ok = QPushButton("OK", panel)
        cancel = QPushButton("Cancel", panel)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        self.setStyleSheet("""
        QFrame#panel { background: rgba(10, 20, 40, 180); border-radius: 12px; }
        QLabel { color: white; font-size: 14px; }
        QLineEdit { background: rgba(255,255,255,35); color: white; border: 1px solid rgba(255,255,255,80); border-radius: 6px; padding: 4px; }
        QPushButton { background: rgba(255,255,255,45); color: white; border-radius: 6px; padding: 4px 14px; }
        QPushButton:hover { background: rgba(255,255,255,70); }
        """)
        self.adjustSize()

    def value(self) -> int:
        text = self.edit.text().strip()
        return max(1, min(100, int(text))) if text else 1

class AlarmDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(self)
        panel.setObjectName("panel")
        root.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        title = QLabel("设置闹钟", panel)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight: bold; font-size: 15px;")
        lay.addWidget(title)

        time_lay = QHBoxLayout()
        self.hour_edit = QLineEdit(panel)
        self.hour_edit.setPlaceholderText("时(0-23)")
        self.hour_edit.setValidator(QIntValidator(0, 23, self))
        self.hour_edit.setAlignment(Qt.AlignCenter)
        self.hour_edit.setFixedWidth(70)
        
        colon = QLabel(":", panel)
        
        self.min_edit = QLineEdit(panel)
        self.min_edit.setPlaceholderText("分(0-59)")
        self.min_edit.setValidator(QIntValidator(0, 59, self))
        self.min_edit.setAlignment(Qt.AlignCenter)
        self.min_edit.setFixedWidth(70)

        time_lay.addWidget(self.hour_edit)
        time_lay.addWidget(colon)
        time_lay.addWidget(self.min_edit)
        lay.addLayout(time_lay)

        curr = QTime.currentTime()
        self.hour_edit.setText(str(curr.hour()))
        self.min_edit.setText(str(curr.minute()))

        lay.addWidget(QLabel("提醒内容:", panel))
        self.content_edit = QLineEdit(panel)
        self.content_edit.setPlaceholderText("例如: 该吃刃恒饭了。")
        lay.addWidget(self.content_edit)

        btns = QHBoxLayout()
        ok = QPushButton("确定", panel)
        cancel = QPushButton("取消", panel)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        self.setStyleSheet("""
        QFrame#panel { background: rgba(10, 20, 40, 190); border-radius: 12px; border: 1px solid rgba(255, 255, 255, 30); }
        QLabel { color: white; font-size: 14px; }
        QLineEdit { background: rgba(255,255,255,30); color: white; border: 1px solid rgba(255,255,255,60); border-radius: 6px; padding: 4px; font-size: 14px; }
        QPushButton { background: rgba(255,255,255,45); color: white; border-radius: 6px; padding: 6px 14px; }
        QPushButton:hover { background: rgba(255,255,255,70); }
        """)
        self.adjustSize()

    def get_data(self):
        h = self.hour_edit.text().strip() or "0"
        m = self.min_edit.text().strip() or "0"
        text = self.content_edit.text().strip() or "闹钟响了！"
        return int(h), int(m), text

#todolist
class TodoItemWidget(QWidget):
    def __init__(self, text, is_done, on_changed, on_delete, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        self.check_btn = QToolButton()
        self.check_btn.setFixedSize(20, 20)
        self.check_btn.setCheckable(True)
        self.check_btn.setChecked(is_done)
        self.check_btn.setCursor(Qt.PointingHandCursor)
        self._update_check_style()
        
        self.check_btn.clicked.connect(lambda: self._toggle_check(on_changed))
        layout.addWidget(self.check_btn)

        self.edit = QLineEdit(text)
        self.edit.setStyleSheet("background: transparent; border: none; color: white; font-size: 11pt;")
        self.edit.editingFinished.connect(lambda: on_changed())
        layout.addWidget(self.edit, 1)

        self.del_btn = QToolButton()
        self.del_btn.setText("×")
        self.del_btn.setFixedSize(22, 22)
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.setStyleSheet("""
            QToolButton { 
                color: rgba(255, 255, 255, 120); 
                background: transparent; 
                font-size: 20px; 
                border: none; 
            }
            QToolButton:hover { 
                color: white; 
            }
        """)
        self.del_btn.clicked.connect(on_delete)
        layout.addWidget(self.del_btn)

    def _toggle_check(self, callback):
        self._update_check_style()
        callback()

    def _update_check_style(self):
        if self.check_btn.isChecked():
            self.check_btn.setText("✓") 
            self.check_btn.setStyleSheet("""
                QToolButton { 
                    background: transparent; 
                    border: 1px solid rgba(255, 255, 255, 200); 
                    border-radius: 4px; 
                    color: white; 
                    font-weight: bold; 
                    font-size: 14px;
                }
            """)
        else:
            self.check_btn.setText("")
            self.check_btn.setStyleSheet("""
                QToolButton { 
                    background: transparent; 
                    border: 1px solid rgba(255, 255, 255, 80); 
                    border-radius: 4px; 
                }
            """)

    def get_data(self):
        return {"text": self.edit.text(), "done": self.check_btn.isChecked()}

class TodoDialog(QDialog):
    def __init__(self, parent=None, save_path=None):
        super().__init__(parent)
        self.save_path = save_path
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        panel = QFrame(self)
        panel.setObjectName("panel")
        root.addWidget(panel)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(10)

        title = QLabel("任务清单", panel)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight: bold; font-size: 16px; color: white; margin-top: 2px; margin-bottom: 5px;")
        lay.addWidget(title)

        self.list = QListWidget(panel)
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setStyleSheet("""
            QListWidget { background: transparent; border: none; outline: none; }
            QListWidget::item { background: transparent; border: none; }
            QListWidget::indicator { width: 0px; height: 0px; } 
            
            /* 滚动条美化 */
            QScrollBar:vertical { border: none; background: transparent; width: 4px; margin: 0px; }
            QScrollBar::handle:vertical { background: rgba(255, 255, 255, 40); border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)
        lay.addWidget(self.list)

        btns = QHBoxLayout()
        add_btn = QPushButton("新增任务", panel)
        cancel_btn = QPushButton("关闭", panel)
        add_btn.clicked.connect(lambda: self.add_item())
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(add_btn)
        btns.addWidget(cancel_btn)
        lay.addLayout(btns)

        self.setStyleSheet("""
            QFrame#panel { 
                background: rgba(20, 20, 30, 220); 
                border-radius: 15px; border: 1px solid rgba(255, 255, 255, 40); 
            }
            QPushButton { 
                background: rgba(255,255,255,30); color: white; 
                border-radius: 8px; padding: 8px; font-size: 13px;
                border: 1px solid rgba(255,255,255,20);
            }
            QPushButton:hover { background: rgba(255,255,255,50); }
        """)
        self.setFixedWidth(280)
        self.load()

    def add_item(self, text="新任务", done=False):
        if not isinstance(text, str): text = "新任务"
        item = QListWidgetItem(self.list)
        widget = TodoItemWidget(text, done, self.save, lambda: self.remove_item(item), self.list)
        item.setSizeHint(widget.sizeHint())
        self.list.addItem(item)
        self.list.setItemWidget(item, widget)
        self.save()

    def remove_item(self, item):
        row = self.list.row(item)
        if row >= 0:
            self.list.takeItem(row)
            self.save()

    def save(self):
        data = [self.list.itemWidget(self.list.item(i)).get_data() for i in range(self.list.count()) if self.list.itemWidget(self.list.item(i))]
        import json
        try:
            self.save_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except: pass

    def load(self):
        if not self.save_path or not self.save_path.exists(): return
        import json
        try:
            data = json.loads(self.save_path.read_text(encoding="utf-8"))
            for d in data: self.add_item(d.get("text", ""), d.get("done", False))
        except: pass

class FlowerDrop(QWidget):
    clicked_signal = Signal()

    def __init__(self, asset_dir, pattern="flower_*.png", parent=None):
        super().__init__(None) 
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.label = QLabel(self)

        self.frames = _load_frames(asset_dir, pattern, 0.5)
        self.frame_i = 0
        
        if self.frames:
            self.label.setPixmap(self.frames[0])
            self.label.adjustSize()
            self.resize(self.label.size())

            self.anim_timer = QTimer(self)
            self.anim_timer.timeout.connect(self._next_flower_frame)
            self.anim_timer.start(150) 
        else:
            pix = QPixmap(str(asset_dir / "flower.png"))
            if not pix.isNull():
                pix = pix.scaled(pix.size() * 0.5, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.label.setPixmap(pix)
                self.label.adjustSize()
                self.resize(self.label.size())

        screen = QGuiApplication.primaryScreen().availableGeometry()
        rx = random.randint(screen.left(), screen.right() - self.width())
        ry = random.randint(screen.top(), screen.bottom() - self.height())
        self.move(rx, ry)
        self.show()

    def _next_flower_frame(self):
        if not self.frames: return
        self.frame_i = (self.frame_i + 1) % len(self.frames)
        self.label.setPixmap(self.frames[self.frame_i])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if hasattr(self, 'anim_timer'):
                self.anim_timer.stop()
            self.clicked_signal.emit()
            self.close()

class FinalSpecialAnimation(QWidget):
    def __init__(self, asset_dir):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.label = QLabel(self)
        self.frames = _load_frames(asset_dir, "final_*.png", 1.0)
        self.current_frame = 0
        
        if self.frames:
            self.label.setPixmap(self.frames[0])
            self.resize(self.frames[0].size())
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self.move(screen.center() - self.rect().center())
            
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.next_frame)
            self.timer.start(150)
            self.show()

    def next_frame(self):
        if not self.frames: return
        self.current_frame = (self.current_frame + 1) % len(self.frames)
        self.label.setPixmap(self.frames[self.current_frame])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.close()
            for inst in DesktopPet.instances:
                inst.show()
                inst.tick_timer.start(TICK_MS)
                inst._schedule_next_state()
                if not inst.is_silent:
                    inst._start_flower_timer()

class FloatingNumber(QWidget):
    def __init__(self, text, pos, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents) 
        
        layout = QVBoxLayout(self)
        self.label = QLabel(text)
        self.label.setStyleSheet("""
            color: #ffffff; 
            font-size: 24px; 
            font-weight: bold; 
            font-family: 'Segoe UI', Arial;
        """)
        layout.addWidget(self.label)
        
        self.move(pos.x() - 20, pos.y() - 40)
        self.opacity = 1.0
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(30) 
        self.show()

    def _animate(self):
        self.opacity -= 0.04
        if self.opacity <= 0:
            self.close()
        else:
            self.setWindowOpacity(self.opacity)
            self.move(self.x(), self.y() - 2) 

class DesktopPet(QWidget):
    instances = []
    WALK = "walk"
    IDLE = "idle"
    SLEEP = "sleep"
    _affection_cache = None

    def __init__(self, pet_name, pet_asset_dir, save_dir, is_silent=False):
        super().__init__()
        self.pet_name = pet_name
        self.pet_asset_dir = pet_asset_dir
        self.save_dir = save_dir
        self.is_silent = is_silent 
        self.save_dir.mkdir(parents=True, exist_ok=True)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.label = QLabel(self)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.idle_min, self.idle_max = 2000, 6000
        self.walk_min, self.walk_max = 2500, 9000
        self.sleep_min, self.sleep_max = 5000, 12000

        self.bubble = SpeechBubble(self) if not self.is_silent else None
        self._active_dialog = None
        self._shutting_down = False

        self.outfit_manager = OutfitManager(pet_asset_dir)
        self.frames = {}
        self.anim_key = "idle"
        self.frame_i = 0
        self._desired_outfit = self.outfit_manager.current_outfit

        self.state = random.choice([self.WALK, self.IDLE])
        self.direction = random.choice([-1, 1])
        self.speed = 3 if self.pet_name == "刃" else 2
        self.vy = random.choice([-2, -1, 1, 2])
        self.bottom_mode = False

        self.dragging = False
        self._press_pos_global = QPoint(0, 0)
        self._press_pos_local = QPoint(0, 0)
        self._moved = False
        
        self._last_collision_count_time = 0


        self.flower_timer = QTimer(self)
        self.flower_timer.setSingleShot(True)
        self.flower_timer.timeout.connect(self._drop_flower_trigger)
        if not self.is_silent:
            self.petal_drop_enabled = True
            self.final_anim_enabled = True
            self._load_ui_settings()

            self._load_flower_stats()
            if self.petal_drop_enabled and self.pet_name == NEXT_DROPPER:
                self._start_flower_timer()
        if self.pet_name == "刃":
            self.supervisor_keywords = ["优动漫", "sai", "sai2", "clipstudio", "adobe", "blender", "mikumikudance", "koikatu", "charastudio"]
            self.process_list = ["优动漫PAINT4.0 个人版.exe", "CLIPStudioPaint.exe", "sai.exe", "sai2.exe", "Photoshop.exe", "Blender.exe", "MikuMikuDance.exe", "Koikatu.exe", "CharaStudio.exe"]
            self.supervisor_asset = "assets/pet1"
        else:
            self.supervisor_keywords = ["石墨文档", "word", "百灵创作", "wps", "wonderpen", "口袋写作"]
            self.process_list = ["石墨文档.exe", "WINWORD.EXE", "WPS Office.exe", "百灵创作.exe", "WonderPen.exe", "kdwrite.exe"]
            self.supervisor_asset = "assets/pet2"

        self.monitor = SupervisorThread(self.supervisor_keywords, self.process_list)
        self.monitor.moyu_signal.connect(self.handle_moyu_event)
        self.monitor.start()
        
        self.is_concentration_mode = False
        self.collision_special_enabled = True

        if not self.is_silent:
            d = _load_dialogs(pet_asset_dir)
            self.talk_idle = d["idle"] 
            self.talk_walk = d["walk"] 
            self.talk_special = _load_lines_txt(pet_asset_dir / "special.txt")
            self.affection_dialogues = _load_affection_dialogues(pet_asset_dir / "dialogues" / "affection.txt")
            self.quiz = QuizEngine(pet_asset_dir, save_dir=self.save_dir) if QuizEngine else None
            self.vocab = VocabEngine(pet_asset_dir, save_dir=self.save_dir) if VocabEngine else None
        else:
            self.talk_idle = self.talk_walk = self.talk_special = []
            self.quiz = self.vocab = None

        self._special_last = 0
        self._special_index = 0
        self._special_timer = QTimer(self)
        self._special_timer.setSingleShot(True)
        self._special_timer.timeout.connect(self._restore_outfit_after_special)
        self._in_special_outfit = False

        self.affection = 1
        self.affection_unlocked = False
        self._load_affection_state()

        self.auto_talk = not self.is_silent
        self.auto_talk_timer = QTimer(self)
        self.auto_talk_timer.setSingleShot(True)
        self.auto_talk_timer.timeout.connect(self._auto_say)

        self.mute_all = self.is_silent
        
        self.alarm_timer = QTimer(self)
        self.alarm_timer.setSingleShot(True)
        self.alarm_timer.timeout.connect(self._on_alarm_timeout)
        self._alarm_content = ""
        self.is_alarm_ringing = False
        
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        self.state_timer = QTimer(self)
        self.state_timer.setSingleShot(True)
        self.state_timer.timeout.connect(self._pick_next_state)

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self._tick)
        self.tick_timer.start(TICK_MS)

        self._modal_paused = False
        self._modal_anim_timer = QTimer(self)
        self._modal_anim_timer.setSingleShot(True)
        self._modal_anim_timer.timeout.connect(self._modal_flip_idle_sleep)
        self._modal_anim_state = "idle"
        
        self.study_mode = "quiz"

        self._reload_all_frames()
        self._apply_anim_for_state()
        self.show()
        self.recall_to_bottom()
        self._schedule_next_state(initial=True)
        if self.auto_talk: self._schedule_auto_talk()

        if not self.is_silent:
            QTimer.singleShot(500, self._restore_extra_pets)

        DesktopPet.instances.append(self)

        if not self.is_silent:
            self._load_flower_stats()

            self._start_flower_timer()


    def _start_flower_timer(self):
        #30分钟=30*60*1000=1800000
        self.flower_timer.start(900000) 

    def _drop_flower_trigger(self):
        global NEXT_DROPPER

        self.flower_timer.stop() 

        if not getattr(self, 'petal_drop_enabled', True):
            return

        if self.pet_name == NEXT_DROPPER:
            has_seq = any(self.pet_asset_dir.glob("flower_*.png"))
            has_single = (self.pet_asset_dir / "flower.png").exists()
            if has_seq or has_single:
                self.active_flower = FlowerDrop(self.pet_asset_dir, "flower_*.png")
                self.active_flower.clicked_signal.connect(self._on_flower_clicked)
            else:
                self.flower_timer.start(5000)

    def _on_flower_clicked(self):
        self._load_flower_stats() 

        global FLOWER_COUNT, NEXT_DROPPER
        FLOWER_COUNT += 1

        if hasattr(self, 'active_flower') and self.active_flower:
            flower_pos = self.active_flower.geometry().center()
            self.floating_count = FloatingNumber(str(FLOWER_COUNT), flower_pos)
        
        NEXT_DROPPER = "丹恒" if NEXT_DROPPER == "刃" else "刃"
        self._save_flower_stats()

        

        if FLOWER_COUNT >= 53:
            try: self._flower_stats_path().unlink(missing_ok=True)
            except: pass
            self._trigger_final_event()
        else:
            found_next = False
            for inst in DesktopPet.instances:
                inst.flower_timer.stop()
                if inst.pet_name == NEXT_DROPPER and getattr(inst, 'petal_drop_enabled', True):
                    inst._start_flower_timer()
                    found_next = True
            if not found_next and getattr(self, 'petal_drop_enabled', True):
                self._start_flower_timer()

    def _trigger_final_event(self):
        global FLOWER_COUNT, NEXT_DROPPER
        FLOWER_COUNT = 0
        NEXT_DROPPER = "刃"
        self._save_flower_stats()

        if not getattr(self, 'final_anim_enabled', True):
            return
        for inst in list(DesktopPet.instances):
            inst.hide()
            inst.tick_timer.stop() 

        final_asset = self.pet_asset_dir.parent / "final_event"
        if final_asset.exists():
            self.final_win = FinalSpecialAnimation(final_asset)

    def _flower_stats_path(self) -> Path:
        global_save_path = Path(__file__).parent / "userdata"
        global_save_path.mkdir(exist_ok=True) 
        return global_save_path / "flower_stats.json"

    def _save_flower_stats(self):
        global FLOWER_COUNT, NEXT_DROPPER
        try:
            data = {
                "flower_count": FLOWER_COUNT,
                "next_dropper": NEXT_DROPPER
            }
            self._flower_stats_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"保存花朵统计失败: {e}")

    def _load_flower_stats(self):
        global FLOWER_COUNT, NEXT_DROPPER
        p = self._flower_stats_path()
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            FLOWER_COUNT = int(data.get("flower_count", 0))
            NEXT_DROPPER = data.get("next_dropper", "刃")
        except Exception as e:
            print(f"加载花朵统计失败: {e}")

    def _ui_settings_path(self) -> Path:
        base = Path(__file__).parent / "userdata"
        base.mkdir(parents=True, exist_ok=True)
        return base / "ui_settings.json"

    def _load_ui_settings(self):
        path = self._ui_settings_path()
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self.petal_drop_enabled = bool(data.get("petal_drop_enabled", True))
                self.final_anim_enabled = bool(data.get("final_anim_enabled", True))
        except Exception as e:
            print(f"加载 UI 设置失败: {e}")

    def _save_ui_settings(self):
        path = self._ui_settings_path()
        try:
            data = {
                "petal_drop_enabled": bool(getattr(self, "petal_drop_enabled", True)),
                "final_anim_enabled": bool(getattr(self, "final_anim_enabled", True)),
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"保存 UI 设置失败: {e}")

    def toggle_petal_drop(self):
        self.petal_drop_enabled = not getattr(self, "petal_drop_enabled", True)
        self._save_ui_settings()
        status = "已开启" if self.petal_drop_enabled else "已关闭"
        self.say_status(f"花瓣掉落：{status}")

        if not self.petal_drop_enabled:
            for inst in DesktopPet.instances:
                inst.flower_timer.stop()
                if hasattr(inst, "active_flower") and inst.active_flower:
                    inst.active_flower.close()
                    inst.active_flower = None
        else:
            if not self.is_silent and self.pet_name == NEXT_DROPPER:
                self._start_flower_timer()
    def toggle_final_anim(self):
        self.final_anim_enabled = not getattr(self, "final_anim_enabled", True)
        self._save_ui_settings()
        status = "已开启" if self.final_anim_enabled else "已关闭"
        self.say_status(f"最终动画：{status}")

    def _reload_all_frames(self):
        folder = self.outfit_manager.get_current_dir()
        self.frames = {
            "idle":       _load_frames(folder, "idle_*.png", SCALE),
            "sleep":      _load_frames(folder, "sleep_*.png", SCALE),
            "walk_right": _load_frames(folder, "walk_right_*.png", SCALE),
            "walk_left":  _load_frames(folder, "walk_left_*.png", SCALE),
            "drag":       _load_frames(folder, "drag_*.png", SCALE),
        }
        if not self.frames["walk_right"]: self.frames["walk_right"] = self.frames["idle"].copy()
        if not self.frames["walk_left"]: self.frames["walk_left"] = self.frames["walk_right"].copy()
        if not self.frames["drag"]: self.frames["drag"] = self.frames["idle"].copy()

    def change_outfit(self, outfit_name: str):
        self._desired_outfit = outfit_name
        if (outfit_name or "").lower() in {"outfitc", "outfit_c"}:
            try: self._special_timer.stop()
            except: pass
            self._in_special_outfit = False
            self._apply_outfit_folder(outfit_name)
            return

        if getattr(self, "_in_special_outfit", False):
            special_folder = "special_a" if (self.pet_name == "丹恒" and outfit_name == "outfit_a" and (self.pet_asset_dir / "special_a").exists()) else "special"
            self._apply_outfit_folder(special_folder)
            return
        self._apply_outfit_folder(outfit_name)

    def _apply_outfit_folder(self, folder_name: str):
        old_pos = self.pos()
        self.outfit_manager.set_outfit(folder_name)
        self._reload_all_frames()
        self._apply_anim_for_state()
        self.move(old_pos)
        self.clamp_to_screen()

    def trigger_special_outfit(self, special_name="special", duration_ms=10000):
        if not (self.pet_asset_dir / special_name).exists(): return
        if getattr(self, "_in_special_outfit", False) and self._special_timer.isActive(): return
        if not getattr(self, "_desired_outfit", None):
            self._desired_outfit = self.outfit_manager.current_outfit
        folder = "special_a" if (self.pet_name == "丹恒" and self._desired_outfit == "outfit_a" and (self.pet_asset_dir / "special_a").exists()) else "special"
        self._apply_outfit_folder(folder)
        self._in_special_outfit = True
        self._special_timer.stop()
        self._special_timer.start(duration_ms)

    def _restore_outfit_after_special(self):
        target = getattr(self, "_desired_outfit", None)
        if target:
            self._apply_outfit_folder(target)
        self._in_special_outfit = False

    def _apply_anim(self, key: str):
        if key not in self.frames or not self.frames[key]: return
        old_center_x = self.x() + self.width() // 2
        old_bottom = self.y() + self.height()
        self.anim_key = key
        self.frame_i = 0
        pm = self.frames[key][0]
        self.label.setPixmap(pm)
        self.label.resize(pm.size())
        self.resize(pm.width(), pm.height())
        self.move(old_center_x - self.width() // 2, old_bottom - self.height())
        if hasattr(self, "bubble") and self.bubble: self.bubble.update_pos()

    def _next_frame(self):
        if self.anim_key not in self.frames or not self.frames[self.anim_key]: return
        frames = self.frames[self.anim_key]
        self.frame_i = (self.frame_i + 1) % len(frames)
        pm = frames[self.frame_i]
        current_center_x = self.x() + self.width() // 2
        current_bottom_y = self.y() + self.height()
        self.label.setPixmap(pm)
        self.label.resize(pm.size())
        self.resize(pm.width(), pm.height())
        self.move(current_center_x - self.width() // 2, current_bottom_y - self.height())
        if hasattr(self, "bubble") and self.bubble: self.bubble.update_pos()

    def _apply_anim_for_state(self):
        if getattr(self, "dragging", False): return
        if self.state == self.SLEEP: self._apply_anim("sleep")
        elif self.state == self.WALK: self._apply_anim("walk_right" if self.direction == 1 else "walk_left")
        else: self._apply_anim("idle")
    
    def _apply_drag_anim(self):
        self._apply_anim("drag")

    def _update_collision_config(self, count=None, active_pets_list=None):
        stat_path = self.save_dir.parent / "collision_stats.json"
        data = {"count": 0, "active_pets": []}
        
        if stat_path.exists():
            try:
                data = json.loads(stat_path.read_text(encoding="utf-8"))
            except: pass
            
        if count is not None:
            data["count"] = count
        if active_pets_list is not None:
            data["active_pets"] = active_pets_list
            
        try:
            stat_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except: pass
        return data

    def _increment_collision_stat(self):
        current_count = self._get_collision_count()
        if current_count >= 213:
            return current_count
            
        new_count = current_count + 1
        self._update_collision_config(count=new_count)
        return new_count

    def _get_collision_count(self):
        stat_path = self.save_dir.parent / "collision_stats.json"
        
        if not stat_path.exists(): return 0
        try: return json.loads(stat_path.read_text(encoding="utf-8")).get("count", 0)
        except: return 0

    def _toggle_extra_pet(self, name, folder_name):
        data = self._update_collision_config()
        active_list = data.get("active_pets", [])
        for inst in list(DesktopPet.instances):
            if inst.pet_name == name:
                inst.shutdown() 
                return

        asset_path = self.pet_asset_dir.parent / folder_name
        if asset_path.exists():
            new_pet = DesktopPet(name, asset_path, self.save_dir, is_silent=True)
            new_pet.move(self.x() + 60, self.y())
            new_pet.clamp_to_screen()
            if self.bottom_mode: new_pet.set_bottom_mode(True)
            
            if name not in active_list:
                active_list.append(name)
                self._update_collision_config(active_pets_list=active_list)

    def _check_instant_spawn(self, count):
        trigger_map = {
            53: ("芝麻酥", "pet3"),
            106: ("糯米团", "pet4"),
            159: ("绷带海豹", "pet5"),
            212: ("饱饱龙", "pet6")
        }
        
        if count in trigger_map:
            name, folder = trigger_map[count]
            for inst in DesktopPet.instances:
                if inst.pet_name == name: return
            
            asset_path = self.pet_asset_dir.parent / folder
            if asset_path.exists():
                new_pet = DesktopPet(name, asset_path, self.save_dir, is_silent=True)
                new_pet.move(self.x() + 60, self.y())
                new_pet.clamp_to_screen()
                if self.bottom_mode: new_pet.set_bottom_mode(True)
                
                data = self._update_collision_config()
                active_list = data.get("active_pets", [])
                if name not in active_list:
                    active_list.append(name)
                    self._update_collision_config(active_pets_list=active_list)

    def _restore_extra_pets(self):
        if self.is_silent or self._shutting_down: return 
        
        data = self._update_collision_config()
        active_list = data.get("active_pets", [])

        pet_map = {"芝麻酥": "pet3", "糯米团": "pet4", "绷带海豹": "pet5", "饱饱龙": "pet6"}
        
        for name in active_list:
            if any(inst.pet_name == name for inst in DesktopPet.instances):
                continue
                
            folder = pet_map.get(name)
            if not folder: continue
            
            asset_path = self.pet_asset_dir.parent / folder
            if asset_path.exists():
                new_pet = DesktopPet(name, asset_path, self.save_dir, is_silent=True)
                new_pet.move(self.x() + 50, self.y())
                new_pet.clamp_to_screen()
                if self.bottom_mode:
                    new_pet.set_bottom_mode(True)

    def _resolve_collisions(self):
        if self._shutting_down: return
        my = self.geometry()
        for other in list(DesktopPet.instances):
            if other is self or getattr(other, "_shutting_down", False) or not other.isVisible(): continue
            
            if self.dragging or other.dragging: continue
            
            og = other.geometry()
            if not my.intersects(og): continue
 
            if {self.pet_name, other.pet_name} == {"刃", "丹恒"}:
                now = QDateTime.currentMSecsSinceEpoch()

                if (now - self._last_collision_count_time > COLLISION_COUNT_CD_MS) and \
                   (now - other._last_collision_count_time > COLLISION_COUNT_CD_MS):

                    self._last_collision_count_time = now
                    other._last_collision_count_time = now

                    new_count = self._increment_collision_stat()

                    self._check_instant_spawn(new_count)

                    if self.collision_special_enabled and other.collision_special_enabled:
                        self._try_special_pair_dialog(other)

                    if self.collision_special_enabled:
                        if not self.is_silent and not self._block_special_on_collision():
                            self.trigger_special_outfit("special", 10000)

                    if other.collision_special_enabled:
                        if not other.is_silent and not other._block_special_on_collision():
                            other.trigger_special_outfit("special", 10000)

            overlap_x = min(my.right(), og.right()) - max(my.left(), og.left())
            overlap_y = min(my.bottom(), og.bottom()) - max(my.top(), og.top())
            if overlap_x <= 0 or overlap_y <= 0: continue
            
            if overlap_x < overlap_y:
                dx = (overlap_x // 2 + 1) * (-1 if my.center().x() < og.center().x() else 1)
                self.move(self.x() + dx, self.y())
                other.move(other.x() - dx, other.y())
            else:
                dy = (overlap_y // 2 + 1) * (-1 if my.center().y() < og.center().y() else 1)
                self.move(self.x(), self.y() + dy)
                other.move(other.x(), other.y() - dy)

            self.clamp_to_screen()
            other.clamp_to_screen()
            my = self.geometry()

    def contextMenuEvent(self, event):
        menu = QMenu()
        
        if not self.is_silent:
            outfits = self.outfit_manager.list_outfits()
            outfit_menu = menu.addMenu("换装")
            name_map = OUTFIT_DISPLAY_NAMES.get(self.pet_name, {})

            if not outfits:
                outfit_menu.addAction("（没有换装文件夹）")
            else:
                for folder_name in outfits:
                    display = name_map.get(folder_name, folder_name)
                    act = outfit_menu.addAction(display)
                    act.triggered.connect(lambda _, n=folder_name: self.change_outfit(n))

            menu.addSeparator()
            special_toggle_act = menu.addAction("碰撞特殊互动") 
            special_toggle_act.setCheckable(True)
            special_toggle_act.setChecked(self.collision_special_enabled)
            special_toggle_act.triggered.connect(self.toggle_collision_special)

            petal_act = menu.addAction("花瓣掉落")
            petal_act.setCheckable(True)
            petal_act.setChecked(getattr(self, "petal_drop_enabled", True))
            petal_act.triggered.connect(self.toggle_petal_drop)

            final_act = menu.addAction("53次最终动画")
            final_act.setCheckable(True)
            final_act.setChecked(getattr(self, "final_anim_enabled", True))
            final_act.triggered.connect(self.toggle_final_anim)

            menu.addSeparator()
            mute_act = menu.addAction("关闭对话")
            mute_act.setCheckable(True)
            mute_act.setChecked(getattr(self, "mute_all", False))
            mute_act.triggered.connect(self.toggle_mute_all)

            menu.addAction("切换好感度对话", self.toggle_auto_talk)

            menu.addSeparator()
            if not self.is_silent:
                mode_label = "关闭专注模式" if self.is_concentration_mode else "开启专注模式"
                toggle_act = menu.addAction(mode_label)
                toggle_act.triggered.connect(self.toggle_mode)
                menu.addSeparator()

            #题
            menu.addSeparator()
            switch_menu = menu.addMenu("切换题库")
            menu.addAction("随机题目", lambda: self.quiz_once(False))
            menu.addAction("错题本", lambda: self.quiz_once(True))

            from pathlib import Path
            items = []  
            if self.quiz and hasattr(self.quiz, "list_banks"):
                for p in self.quiz.list_banks():
                    items.append(("quiz", p, self.quiz.get_display_name(p) if hasattr(self.quiz, "get_display_name") else p.stem))
            if self.vocab and hasattr(self.vocab, "list_books"):
                for p in self.vocab.list_books():
                    items.append(("vocab", p, self.vocab.get_display_name(p) if hasattr(self.vocab, "get_display_name") else p.stem))

            if not items:
                switch_menu.addAction("未找到可用的内容。")
            else:
                cur_quiz = getattr(self.quiz, "bank_path", None) if self.quiz else None
                cur_vocab = getattr(self.vocab, "vocab_path", None) if self.vocab else None
                cur_mode = getattr(self, "study_mode", "quiz")
                for kind, p, display in items:
                    act = switch_menu.addAction(display)
                    act.setCheckable(True)
                    if kind == "quiz":
                        act.setChecked(cur_mode == "quiz" and cur_quiz is not None and Path(cur_quiz).name == p.name)
                    else:
                        act.setChecked(cur_mode == "vocab" and cur_vocab is not None and Path(cur_vocab).name == p.name)
                    def _do_switch(_, kk=kind, pp=p, name=display):
                        try:
                            if kk == "quiz":
                                self.study_mode = "quiz"
                                self.quiz.set_bank(pp)
                                self.say(f"已切换：{name}")
                            else:
                                self.study_mode = "vocab"
                                self.vocab.set_book(pp)
                                self.say(f"已切换：{name}")
                        except Exception as e:
                            self.say(f"切换失败：{e}")
                    act.triggered.connect(_do_switch)

            #Todolist
            menu.addSeparator()
            menu.addAction("任务清单", self.open_todo)

            #闹钟
            menu.addSeparator()
            alarm_act = menu.addAction("设置闹钟")
            alarm_act.triggered.connect(self.set_alarm)
            if self.alarm_timer.isActive():
                rem_sec = self.alarm_timer.remainingTime() // 1000
                rem_min = rem_sec // 60
                rem_h = rem_min // 60
                display_rem = f"{rem_h}小时{rem_min%60}分" if rem_h > 0 else f"{rem_min}分钟"
                menu.addAction(f"（下个闹钟：约 {display_rem} 后）").setEnabled(False)
                cancel_act = menu.addAction("取消当前闹钟")
                def _cancel():
                    self.alarm_timer.stop()
                    self.say("闹钟已取消。")
                cancel_act.triggered.connect(_cancel)    

            #好感度
            menu.addSeparator()
            aff_menu = menu.addMenu(f"好感度")
            aff_menu.addAction(f"当前进度：{self.affection}/100").setEnabled(False)
            aff_menu.addSeparator()
            ITEMS_BY_PET = {
                "刃": [("咖啡", 3), ("乱斩牛杂", -20), ("讲丹恒的故事", 20), ("苏打豆汁", -1), ("糯米团", 5), ("芝麻酥", 1)],
                "丹恒": [("苏打豆汁", 5), ("小说", 5), ("洗澡", 5), ("讲刃的故事", 10), ("糯米团", 10), ("芝麻酥", 5)],
            }
            items = ITEMS_BY_PET.get(self.pet_name, [])
            for title, add in items:
                act = aff_menu.addAction(f"{title}")
                act.triggered.connect(lambda _, a=add: self.use_item(a))
            aff_menu.addSeparator()
            if self.affection_unlocked:
                adj_act = aff_menu.addAction("手动修改数值...")
                adj_act.triggered.connect(lambda: self._adjust_affection_dialog())
            else:
                aff_menu.addAction("（满100后解锁自由调节）").setEnabled(False)
            
            count = self._get_collision_count()
            if self.pet_name in ["刃", "丹恒"]:
                menu.addSeparator()
                controls = {
                    "刃": [(53, "芝麻酥", "pet3"), (159, "绷带海豹", "pet5")],
                    "丹恒": [(106, "糯米团", "pet4"), (212, "饱饱龙", "pet6")]
                }
                for threshold, name, folder in controls[self.pet_name]:
                    if count >= threshold:
                        is_active = any(inst.pet_name == name for inst in DesktopPet.instances)
                        txt = f"收回 {name}" if is_active else f"召唤 {name}"
                        menu.addAction(txt, lambda n=name, f=folder: self._toggle_extra_pet(n, f))

        menu.addSeparator()
        if not self.is_silent:
            bottom_act = menu.addAction("切换底部模式")
            bottom_act.setCheckable(True)
            bottom_act.setChecked(self.bottom_mode)
            bottom_act.triggered.connect(lambda c: self.set_bottom_mode(c))

        menu.addSeparator()
        menu.addAction("退出该桌宠", self.shutdown)
        try:
            pos = event.globalPos()
        except Exception:
            pos = event.globalPosition().toPoint()
        menu.exec(pos)

    def toggle_mode(self):
            self.is_concentration_mode = not self.is_concentration_mode
            self.monitor.is_active = self.is_concentration_mode
            
            if self.is_concentration_mode:
                self.say("专注模式已开启。")
                for pet in DesktopPet.instances:
                    pet.auto_talk_timer.stop()
            else:
                count = self.monitor.moyu_count
                minutes = self.monitor.total_moyu_seconds // 60
                self.say(f"结算：摸鱼{count}次，共计{minutes}分钟。")
                self.monitor.reset_stats()

                if all(not p.is_concentration_mode for p in DesktopPet.instances):
                    for pet in DesktopPet.instances:
                        pet._schedule_auto_talk()

    def toggle_collision_special(self):
        self.collision_special_enabled = not self.collision_special_enabled
        status = "已开启" if self.collision_special_enabled else "已关闭"
        self.say_status(f"碰撞效果：{status}")

    def handle_moyu_event(self, msg, is_alarm):
        if not self.is_concentration_mode: return
        
        if is_alarm:
            self.is_alarm_ringing = True 
            self.monitor.paused_by_alarm = True
            audio_path = os.path.join(self.supervisor_asset, "moyu.mp3")
            self.player.setSource(QUrl.fromLocalFile(audio_path))
            self.player.setLoops(QMediaPlayer.Infinite)
            self.player.play()
            
            img_path = os.path.join(self.supervisor_asset, "moyu.png")
            if os.path.exists(img_path):
                self.extra_win = MoyuImageWindow(img_path, self)
            
            msg_txt = "赶紧工作。" if self.pet_name == "刃" else "别发呆了，快专心工作吧。"
            self.say(msg_txt, duration=0)

    def stop_moyu_alarm(self):
        if not self.is_alarm_ringing: return
        
        self.is_alarm_ringing = False
        self.player.stop() 
        if self.bubble: self.bubble.hide()
        
        if hasattr(self, 'extra_win'):
            try: self.extra_win.close()
            except: pass
            
        self.monitor.paused_by_alarm = False
        self.monitor.last_move_time = time.time()
        self.monitor.slacking_start_time = None

    def _block_special_on_collision(self) -> bool:
        if self.is_silent: return True 
        o = (getattr(self, "_desired_outfit", "") or "").lower()
        return o in {"outfitc", "outfit_c", "outfit_c".lower()}

    def say(self, text: str, duration: int = 1800):
        if self.is_silent: return 
        if getattr(self, "mute_all", False) and duration != 0: return
        if self.is_alarm_ringing and duration != 0: return
        if self.bubble: self.bubble.show_text(text, ms=duration)
          
    def say_status(self, text: str, duration: int = 1800):
        if hasattr(self, "bubble") and self.bubble:
            self.bubble.show_text(text, ms=duration)

    def get_time_greeting(self):
        hour = QTime.currentTime().hour()
        if 5 <= hour < 11: period = "morning"  
        elif 11 <= hour < 14: period = "noon"     
        elif 14 <= hour < 19: period = "afternoon"
        elif 19 <= hour < 24: period = "evening"  
        else: period = "night"    

        lines = {}

        if self.pet_name == "刃":
            lines = {
                "morning": "又到早上了……",
                "noon": "不吃东西也不会怎么样，而且我现在没有胃口。",
                "afternoon": "没有任务的时候我偶尔也会把那护腕拿出来。只是偶尔。",
                "evening": "这次的剧本里没有我，而外出的事卡芙卡也知情。",
                "night": "无论是睡着还是清醒的时候，我都在想你……丹恒。"
            }
        elif self.pet_name == "丹恒":
            lines = {
                "morning": "早安。",
                "noon": "正午了。要注意饮食规律。",
                "afternoon": "下午要整理智库，晚上……没什么特殊的事。",
                "evening": "在他来之前要先洗个澡……",
                "night": "熬夜会让次日的精神变差。但……偶尔也有不得不晚睡的时候。"
            }
        return lines.get(period, "…………")

    def set_alarm(self):
        self._pause_for_modal()
        dlg = AlarmDialog(self)
        self._active_dialog = dlg
        try:
            if dlg.exec() == QDialog.Accepted:
                h, m, text = dlg.get_data()
                now = QDateTime.currentDateTime()
                target = QDateTime(now.date(), QTime(h, m))
                if target <= now:
                    target = target.addDays(1)
                    day_str = "明天"
                else:
                    day_str = "今天"
                diff_ms = now.msecsTo(target)
                self._alarm_content = text
                self.alarm_timer.stop()
                self.alarm_timer.start(diff_ms)
                
                time_str = f"{h:02d}:{m:02d}"
                if self.pet_name == "刃":
                    self.say(f"{day_str} {time_str}，记得“{text}”。")
                elif self.pet_name == "丹恒":
                    self.say(f"已记录：{day_str} {time_str} 我会提醒你“{text}”。")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            self._active_dialog = None
            self._resume_from_modal()

    def open_todo(self):
        self._pause_for_modal()
        dlg = TodoDialog(self, self.save_dir / "todo.json")
        self._active_dialog = dlg
        try: dlg.exec()
        finally:
            self._active_dialog = None
            self._resume_from_modal()

    def _on_alarm_timeout(self):
        if self._alarm_content:
            if self.state == self.SLEEP:
                self.state = self.IDLE
                self._apply_anim_for_state()
            
            bgm_wav = self.pet_asset_dir / "alarm.wav"
            if bgm_wav.exists():
                self.player.stop()
                self.player.setSource(QUrl.fromLocalFile(str(bgm_wav)))
                self.player.setLoops(QMediaPlayer.Infinite) 
                self.player.play()
            
            self.is_alarm_ringing = True
            if self.pet_name == "刃":
                self.say(f"时间到了。去做“{self._alarm_content}”。", duration=0)
            elif self.pet_name == "丹恒":
                self.say(f"依照计划，该去“{self._alarm_content}了”。", duration=0)
            else:
                self.say(f"时间到了！\n{self._alarm_content}", duration=0)
            self._alarm_content = ""

    def _tick(self):
        self._next_frame()
        if self.dragging: return

        if self.is_silent:
            flower = self._find_my_target_flower()
            
            if flower and self.state != self.SLEEP:
                if self.geometry().intersects(flower.geometry()):
                    self._on_flower_intercepted()
                    return

                if random.random() < 0.5: 
                    f_pos = flower.geometry().center()
                    m_pos = self.geometry().center()
                    
                    self.direction = 1 if f_pos.x() > m_pos.x() else -1
                    if not self.bottom_mode:
                        self.vy = 1 if f_pos.y() > m_pos.y() else -1
                    
                    if self.state == self.IDLE:
                        self.state = self.WALK
                    self._apply_anim_for_state()

        r = self.current_screen_rect()
        if self.bottom_mode:
            bottom_y = r.bottom() - self.height() - EDGE_MARGIN
            if self.state == self.WALK:
                new_x = self.x() + self.direction * self.speed
                if new_x <= r.left() or new_x >= r.right() - self.width():
                    self.direction *= -1
                    self._apply_anim_for_state()
                self.move(new_x, bottom_y)
            else:
                self.move(self.x(), bottom_y)
            self._resolve_collisions()
            return

        if self.state == self.WALK:
            move_speed = self.speed if not self.is_silent else 1 
            new_x = self.x() + self.direction * move_speed
            new_y = self.y() + self.vy
            
            if new_x <= r.left() or new_x >= r.right() - self.width():
                self.direction *= -1
                self._apply_anim_for_state()
            if new_y <= r.top() or new_y >= r.bottom() - self.height():
                self.vy *= -1
            self.move(new_x, new_y)
        else:
            self.clamp_to_screen()
        
        self._resolve_collisions()

    def _find_my_target_flower(self):
        target_owner = ""
        if self.pet_name in ["芝麻酥", "绷带海豹"]: 
            target_owner = "刃"
        elif self.pet_name in ["糯米团", "饱饱龙"]:
            target_owner = "丹恒"
        
        if not target_owner:
            return None

        for inst in DesktopPet.instances:
            if inst.pet_name == target_owner:
                if hasattr(inst, "active_flower") and inst.active_flower and inst.active_flower.isVisible():
                    return inst.active_flower
        return None


    def _on_flower_intercepted(self):
        global NEXT_DROPPER
        
        for inst in DesktopPet.instances:
            if hasattr(inst, "active_flower") and inst.active_flower:
                inst.active_flower.close()
                inst.active_flower = None
        
        NEXT_DROPPER = "丹恒" if NEXT_DROPPER == "刃" else "刃"
        self._save_flower_stats()

        for inst in DesktopPet.instances:
            inst.flower_timer.stop()
            if inst.pet_name == NEXT_DROPPER and getattr(inst, 'petal_drop_enabled', True):
                inst._start_flower_timer()

    def _pick_next_state(self):
        if self._modal_paused: return
        if self.state == self.SLEEP: self.state = self.IDLE
        else:
            r = random.random()
            if r < 0.6: self.state = self.WALK
            elif r < 0.85: self.state = self.IDLE
            else: self.state = self.SLEEP
        
        if self.state == self.WALK:
            self.direction = random.choice([-1, 1])
            self.vy = 0 if self.bottom_mode else random.choice([-2, -1, 1, 2])
        
        self._apply_anim_for_state()
        self._schedule_next_state()

    def _schedule_next_state(self, initial=False):
        if initial:
            t = random.randint(800, 1600)
        elif self.state == self.WALK:
            t = random.randint(self.walk_min, self.walk_max)
        elif self.state == self.SLEEP:
            t = random.randint(self.sleep_min, self.sleep_max)
        else:
            t = random.randint(self.idle_min, self.idle_max)
        self.state_timer.start(t)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos_global = event.globalPosition().toPoint()
            self._press_pos_local = event.position().toPoint()
            self._moved = False
            self.grabMouse()
            event.accept()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton): return
        cur = event.globalPosition().toPoint()
        if (cur - self._press_pos_global).manhattanLength() > DRAG_THRESHOLD:
            if not self.dragging:
                self.dragging = True
                self._drag_lock = True
                self.state_timer.stop()
                self._apply_drag_anim()
            self._moved = True
            self.move(cur - self._press_pos_local)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton: return
        try: self.releaseMouse()
        except: pass

        if self._moved:
            self.dragging = False
            self._drag_lock = False
            self._apply_anim_for_state()
            self.clamp_to_screen()
            self._schedule_next_state()
            if any(p.is_concentration_mode for p in DesktopPet.instances):
                return
            return

        if any(p.is_concentration_mode for p in DesktopPet.instances):
            if self.is_alarm_ringing:
                self.stop_moyu_alarm() 
            return

        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.stop()

        if self.state == self.SLEEP:
            self.state = self.IDLE
            self._apply_anim_for_state()
            self._schedule_next_state()
        else:
            self.say_by_state()

    def _try_special_pair_dialog(self, other):
        if getattr(self, "_shutting_down", False) or getattr(other, "_shutting_down", False): return
        if {self.pet_name, other.pet_name} != {"刃", "丹恒"}: return
        
        now = QDateTime.currentMSecsSinceEpoch()
        if (now - self._special_last) < SPECIAL_CD_MS or (now - other._special_last) < SPECIAL_CD_MS: return
        
        max_len = min(len(self.talk_special), len(other.talk_special))
        if max_len <= 0: return

        p1, p2 = (self, other) if self.pet_name == "刃" else (other, self)
        idx = p1._special_index % max_len
        p1._special_index += 1
        p2._special_index = p1._special_index
        p1._special_last = p2._special_last = now
        
        p1.say(p1.talk_special[idx])
        QTimer.singleShot(SPECIAL_DELAY_MS, lambda: p2.say(p2.talk_special[idx]))

    def current_screen_rect(self):
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def clamp_to_screen(self):
        r = self.current_screen_rect()
        x = max(r.left(), min(self.x(), r.right() - self.width()))
        y = max(r.top(), min(self.y(), r.bottom() - self.height()))
        self.move(x, y)

    def recall_to_bottom(self):
        r = self.current_screen_rect()
        self.move(self.x(), r.bottom() - self.height() - EDGE_MARGIN)

    def set_bottom_mode(self, on: bool):
        self.bottom_mode = on
        if on:
            if self.state == self.SLEEP:
                self.state = self.IDLE
                self._apply_anim_for_state()
            self.vy = 0
            self.recall_to_bottom()
        else:
            if self.state == self.WALK: self.vy = random.choice([-2, -1, 1, 2])
        self._apply_anim_for_state()
        if not self.is_silent:
            targets = []
            if self.pet_name == "刃":
                targets = ["芝麻酥", "绷带海豹"] 
            elif self.pet_name == "丹恒":
                targets = ["糯米团", "饱饱龙"]   
            
            if targets:
                for inst in DesktopPet.instances:
                    if inst.pet_name in targets and inst.bottom_mode != on:
                        inst.set_bottom_mode(on)

    def shutdown(self):
        if self._shutting_down: return
        self._shutting_down = True


        if self.is_silent:
            try:
                data = self._update_collision_config()
                active_list = data.get("active_pets", [])
                if self.pet_name in active_list:
                    active_list.remove(self.pet_name)
                    self._update_collision_config(active_pets_list=active_list)
            except: pass
        try: DesktopPet.instances.remove(self)
        except: pass
        self.tick_timer.stop()
        self.state_timer.stop()
        self.auto_talk_timer.stop()
        if self.bubble: self.bubble.hide()
        if self._active_dialog: self._active_dialog.close()
        self.close()

    def toggle_mute_all(self):
        self.mute_all = not self.mute_all
        if self.mute_all:
            self.auto_talk_timer.stop()
            self.say_status("已关闭对话。")
        else:
            self.say_status("已开启对话。")
            self._schedule_auto_talk()

    def toggle_auto_talk(self):
        self.auto_talk = not self.auto_talk
        if self.auto_talk:
            self.say_status("好感度对话：开")
            self._schedule_auto_talk()
        else:
            self.say_status("好感度对话：关")
            self.auto_talk_timer.stop()

    def quiz_once(self, wrong_only):
        if self.study_mode == "vocab":
            target = self.vocab
            DialogClass = VocabDialog
        else:
            target = self.quiz
            DialogClass = QuizDialog

        if not target or not DialogClass:
            return self.say("没有安装题库模块")

        self._pause_for_modal()

        q = target.pick_wrong() if wrong_only else target.pick_random()
        if not q:
            self._resume_from_modal()
            return self.say("题库为空")

        dlg = DialogClass(self, target, q, only_wrong=wrong_only)
        self._active_dialog = dlg
        dlg.exec()
        self._active_dialog = None
        self._resume_from_modal()

    def say_by_state(self):
        if self.is_silent: return
        if self.state == self.SLEEP:
            return
        elif self.state == self.WALK: 
            if self.talk_walk:
                self.say(random.choice(self.talk_walk))
            else:
                self.say("...")
        else: 
            if random.random() < 0.5:
                self.say(self.get_time_greeting())
            else:
                if self.talk_idle:
                    self.say(random.choice(self.talk_idle))
                else:
                    self.say(self.get_time_greeting())

    def _schedule_auto_talk(self):
        if not self.auto_talk:
            return
        
        self.auto_talk_timer.start(random.randint(AUTO_TALK_MIN_MS, AUTO_TALK_MAX_MS))

    def _auto_say(self):
        anyone_monitoring = any(p.is_concentration_mode for p in DesktopPet.instances)
        
        if self.is_silent or anyone_monitoring: 
            return
        if self._modal_paused: 
            if random.random() < 0.5:
                self.say_by_state()
            else:
                self.say_by_affection()
            self._schedule_auto_talk()
            return

        if self.state != self.SLEEP:
            if random.random() < 0.5: 
                self.say_by_state()
            else: 
                self.say(self.say_by_affection() if hasattr(self, 'say_by_affection') else self._pick_affection_line())
        
        self._schedule_auto_talk()

    def _pick_affection_line(self) -> str:
        tier = self._affection_tier(self.affection)
        pool = self.affection_dialogues.get(tier, [])
        if not pool:
            return "……"
        return random.choice(pool)
    def _clamp(self, v: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, v))

    def _affection_tier(self, aff: int) -> str:
        if aff <= 20:
            return "1-20"
        if aff <= 40:
            return "21-40"
        if aff <= 60:
            return "41-60"
        if aff <= 80:
            return "61-80"
        return "81-100"


    def say_by_affection(self) -> str:
        return self._pick_affection_line()

    def use_item(self, add: int):
        before = self.affection
        self.affection = self._clamp(self.affection + int(add), 1, 100)
        if self.affection == 100 and not self.affection_unlocked:
            self.affection_unlocked = True
            self.say("好感度已满，解锁自由调节。")
        else:
            if add > 0: self.say(f"好感度 +{add}")
            else: self.say(f"好感度 {add}")
        self._save_affection_state()

    def set_affection(self, val: int):
        self.affection = self._clamp(int(val), 1, 100)
        self._save_affection_state()

    def _affection_state_path(self) -> Path:
        return self.save_dir / "affection_state.json"

    def _load_affection_state(self):
        if DesktopPet._affection_cache is not None:
            self.affection = DesktopPet._affection_cache.get("affection", 1)
            self.affection_unlocked = DesktopPet._affection_cache.get("affection_unlocked", False)
            return

        p = self._affection_state_path()
        if not p.exists():
            return
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            self.affection = self._clamp(int(obj.get("affection", 1)), 1, 100)
            self.affection_unlocked = bool(obj.get("affection_unlocked", False))
            DesktopPet._affection_cache = obj
        except Exception:
            pass

    def _save_affection_state(self):
        cache_data = {
            "affection": self.affection,
            "affection_unlocked": self.affection_unlocked,
        }
        DesktopPet._affection_cache = cache_data

        try:
            self._affection_state_path().write_text(
                json.dumps(cache_data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _adjust_affection_dialog(self):
        dlg = AffectionDialog(self, current=int(self.affection))
        self._active_dialog = dlg
        try:
            result = dlg.exec()
            if result == QDialog.Accepted:
                self.set_affection(dlg.value())
        finally:
            self._resume_from_modal()

    def _pause_for_modal(self):
        if self._modal_paused:
            return
        self._modal_paused = True
        self.state_timer.stop()
        self._modal_prev_state = (self.state, self.direction, self.vy, self.anim_key)
        self.state = self.IDLE
        self._modal_anim_state = "idle"
        self._apply_anim("idle")
        self._modal_anim_timer.stop()
        self._modal_anim_timer.start(random.randint(2500, 7000))
        
    def _resume_from_modal(self):
        if not self._modal_paused:
            return
        self._modal_paused = False
        try:
            self._modal_anim_timer.stop()
        except Exception:
            pass

        if self._modal_prev_state:
            self.state, self.direction, self.vy, _anim = self._modal_prev_state
            self._modal_prev_state = None
            self._apply_anim_for_state()

        self._schedule_next_state()

    def _modal_flip_idle_sleep(self):
        if not self._modal_paused:
            return
        cur = getattr(self, "_modal_anim_state", "idle")    
        self._modal_anim_state = "sleep" if cur == "idle" else "idle"
        self._apply_anim(self._modal_anim_state)
        self._modal_anim_timer.start(random.randint(2500, 7000))