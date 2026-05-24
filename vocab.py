import json
import random
from pathlib import Path
from typing import List, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QFrame, QHBoxLayout


class VocabEngine:
    """
    词汇背诵引擎
    - 错题本：wrongbook_<book_id>.json
    """
    def __init__(self, pet_asset_dir: Path, vocab_path: Optional[Path] = None, save_dir: Optional[Path] = None):
        self.pet_asset_dir = pet_asset_dir
        self.save_dir = save_dir if save_dir else pet_asset_dir

        if vocab_path:
            self.vocab_path = Path(vocab_path)
        else:
            books = self.list_books()
            self.vocab_path = books[0] if books else None

        self.book_id = self.vocab_path.stem if self.vocab_path else "none"
        
        self.wrong_path = self.save_dir / f"wrongbook_{self.book_id}.json"

        self.items = []
        self._reload()

    def set_book(self, vocab_path: Path):
        vocab_path = Path(vocab_path)
        self.vocab_path = vocab_path
        self.book_id = self._book_id_from_path(vocab_path)
        self.wrong_path = self.save_dir / f"wrongbook_{self.book_id}.json"
        self._reload()

    def list_books(self) -> List[Path]:
        files = sorted(self.pet_asset_dir.glob("*.json"))
        out: List[Path] = []
        for p in files:
            name = p.name.lower()
            if ("vocab" in name) and ("wrongbook" not in name) and ("progress" not in name):
                out.append(p)
        return out

    def get_display_name(self, path: Path) -> str:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            name = data.get("display_name", "").strip()
            if name:
                return name
        except Exception:
            pass
        return path.stem
    def _book_id_from_path(self, vocab_path: Path) -> str:
        p = Path(vocab_path) if vocab_path else None
        return p.stem if p else "none"

    def _reload(self):
        Path(self.save_dir).mkdir(parents=True, exist_ok=True)

        self.items = self._load_items(self.vocab_path) if self.vocab_path else []

        if not self.wrong_path.exists():
            self._save_json(self.wrong_path, {"items": []})

    def _load_items(self, path: Path) -> List[Dict]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return list(data.get("items", []))
        except Exception:
            return []

    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _save_json(self, path: Path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def pick_random(self) -> Optional[Dict]:
        if not self.items:
            return None
        return random.choice(self.items)

    def pick_wrong(self) -> Optional[Dict]:
        """从错题本中随机抽取一个单词"""
        wb = self._load_json(self.wrong_path, {"items": []})
        wrong_items = wb.get("items", [])
        if not wrong_items:
            return None
        return random.choice(wrong_items)

    def add_wrong(self, item: Dict):
        """将单词加入错题本（查重）"""
        wb = self._load_json(self.wrong_path, {"items": []})
        items = wb.get("items", [])
        
        # 简单查重：通过 front 字段判断
        front = item.get("front")
        if not any(x.get("front") == front for x in items):
            items.append(item)
            wb["items"] = items
            self._save_json(self.wrong_path, wb)

    def remove_wrong(self, item: Dict):
        """将单词从错题本移除"""
        wb = self._load_json(self.wrong_path, {"items": []})
        items = wb.get("items", [])
        
        front = item.get("front")
        new_items = [x for x in items if x.get("front") != front]
        
        if len(new_items) != len(items):
            wb["items"] = new_items
            self._save_json(self.wrong_path, wb)


class VocabDialog(QDialog):
    """
    背单词弹窗
    only_wrong: 是否仅错题模式
    """
    def __init__(self, parent, engine: VocabEngine, item: Dict, title: str = "背单词", only_wrong: bool = False):
        super().__init__(parent)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self.engine = engine
        self.item = item
        self.title = title
        self.only_wrong = only_wrong  
        self.revealed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        self.panel = QFrame(self)
        self.panel.setObjectName("panel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(10)
        root.addWidget(self.panel)

        self.card = QLabel(self.panel)
        self.card.setWordWrap(True)
        self.card.setText(self._render_front())
        self.card.setCursor(Qt.PointingHandCursor)
        self.card.mousePressEvent = self._on_click_card
        panel_layout.addWidget(self.card)

        # buttons (hidden until revealed)
        self.btn_row = QHBoxLayout()

        self.btn_remember = QPushButton("记住", self.panel)
        self.btn_forget = QPushButton("没记住", self.panel)
        self.btn_close = QPushButton("关闭", self.panel)

        self.btn_remember.hide()
        self.btn_forget.hide()

        self.btn_remember.clicked.connect(self._remember_and_next)
        self.btn_forget.clicked.connect(self._forget_and_next)
        self.btn_close.clicked.connect(self.accept)

        panel_layout.addLayout(self.btn_row)
        self.btn_row.addWidget(self.btn_close)  
        self.setWindowTitle(title)

        self.setStyleSheet("""
        QFrame#panel {
            background-color: rgba(20, 30, 60, 190);
            border-radius: 14px;
        }
        QLabel {
            color: #E6ECFF;
            font-size: 13px;
        }
        QPushButton {
            background-color: rgba(40, 60, 120, 200);
            color: #FFFFFF;
            border: none;
            border-radius: 8px;
            padding: 6px 10px;
        }
        QPushButton:hover {
            background-color: rgba(70, 100, 180, 220);
        }
        """)
        self.resize(294, 182)

    def _render_front(self) -> str:
        en = str(self.item.get("front", "")).strip()
        pos = str(self.item.get("pos", "")).strip()
        return f"{en}   {pos}".strip()

    def _render_both(self) -> str:
        en = str(self.item.get("front", "")).strip()
        pos = str(self.item.get("pos", "")).strip()
        cn = str(self.item.get("back", "")).strip()
        line1 = f"{en}   {pos}".strip()
        return f"{line1}\n\n{cn}"

    def _on_click_card(self, _evt):
        if self.revealed:
            return
        self.revealed = True
        self.card.setText(self._render_both())

        self.btn_remember.show()
        self.btn_forget.show()

        while self.btn_row.count():
            item = self.btn_row.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        self.btn_row.addWidget(self.btn_remember)
        self.btn_row.addWidget(self.btn_forget)
        self.btn_row.addWidget(self.btn_close)

    def _forget_and_next(self):
        self.engine.add_wrong(self.item)
        self._open_next()

    def _remember_and_next(self):
        self.engine.remove_wrong(self.item)
        self._open_next()

    def _open_next(self):
        self.accept()

        if self.only_wrong:
            next_item = self.engine.pick_wrong()
        else:
            next_item = self.engine.pick_random()

        if not next_item:
            return

        dlg = VocabDialog(self.parent(), self.engine, next_item, title=self.title, only_wrong=self.only_wrong)
        dlg.exec()