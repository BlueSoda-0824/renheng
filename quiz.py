import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QWidget, QFrame
)

BASE_W, BASE_H = 420, 260
UI_SCALE = 0.7
DIALOG_W, DIALOG_H = int(BASE_W * UI_SCALE), int(BASE_H * UI_SCALE)

@dataclass
class Question:
    id: str
    type: str  # "mcq" or "tf"
    stem: str
    choices: Optional[Dict[str, str]] = None
    answer: str = ""
    explanation: str = ""
    tag: str = ""


class QuizEngine:
    """
    刷题引擎
    - 进度：quiz_progress_<bank_id>.json
    """
    def __init__(self, pet_asset_dir: Path, bank_path: Optional[Path] = None, save_dir: Optional[Path] = None):
        self.pet_asset_dir = pet_asset_dir
        self.save_dir = save_dir if save_dir else pet_asset_dir
        Path(self.save_dir).mkdir(parents=True, exist_ok=True)

        if bank_path:
            self.bank_path = Path(bank_path)
        else:
            banks = self.list_banks()
            self.bank_path = banks[0] if banks else None

        self.bank_id = self.bank_path.stem if self.bank_path else "none"
        
        self.progress_path = self.save_dir / f"quiz_progress_{self.bank_id}.json"

        self.questions = []
        self.progress = {
            "total_answered": 0, "correct": 0, "wrong_ids": [], "history": []
        }
        self._reload()

    def set_bank(self, bank_path: Path):
        bank_path = Path(bank_path)
        self.bank_path = bank_path
        self.bank_id = self._bank_id_from_path(bank_path)
        self.progress_path = self.save_dir / f"quiz_progress_{self.bank_id}.json"
        self._reload()

    def list_banks(self) -> List[Path]:
        files = sorted(self.pet_asset_dir.glob("*.json"))
        out: List[Path] = []
        for p in files:
            name = p.name.lower()
            if ("question_bank" in name) and ("progress" not in name):
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

    def _bank_id_from_path(self, bank_path: Path) -> str:
        p = Path(bank_path) if bank_path else None
        return p.stem if p else "none"

    def _reload(self):
        self.load_bank()
        self.load_progress()

    def load_bank(self):
        if not self.bank_path or not self.bank_path.exists():
            self.questions = []
            return

        data = json.loads(self.bank_path.read_text(encoding="utf-8"))
        qs = []
        for x in data.get("questions", []):
            qid = str(x.get("id", "")).strip()
            qtype = str(x.get("type", "mcq")).strip().lower()
            stem = str(x.get("stem", "")).strip()
            choices = x.get("choices", None)
            ans = str(x.get("answer", "")).strip().upper()
            exp = str(x.get("explanation", "")).strip()
            tag = str(x.get("tag", "")).strip()

            if not qid or not stem or not ans:
                continue

            if qtype not in ("mcq", "tf"):
                qtype = "mcq"

            if qtype == "mcq":
                if not isinstance(choices, dict) or not any(k in choices for k in ["A", "B", "C", "D"]):
                    continue
                if ans not in ["A", "B", "C", "D"]:
                    continue

            if qtype == "tf":
                if ans in ["T", "TRUE", "对", "√", "A"]: ans = "A"
                elif ans in ["F", "FALSE", "错", "×", "B"]: ans = "B"
                if not isinstance(choices, dict) or not ("A" in choices and "B" in choices):
                    choices = {"A": "正确", "B": "错误"}
            
            qs.append(Question(
                id=qid, type=qtype, stem=stem,
                choices=choices, answer=ans,
                explanation=exp, tag=tag
            ))
        self.questions = qs

    def load_progress(self):
        if self.progress_path.exists():
            try:
                self.progress = json.loads(self.progress_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        self.progress.setdefault("total_answered", 0)
        self.progress.setdefault("correct", 0)
        self.progress.setdefault("wrong_ids", [])
        self.progress.setdefault("history", [])

    def save_progress(self):
        try:
            self.progress_path.write_text(
                json.dumps(self.progress, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def pick_random(self) -> Optional[Question]:
        if not self.questions:
            return None
        return random.choice(self.questions)

    def pick_wrong(self) -> Optional[Question]:
        """只从错题 ID 列表中选题"""
        wrong_set = set(self.progress.get("wrong_ids", []))
        if not wrong_set:
            return None
        candidates = [q for q in self.questions if q.id in wrong_set]
        if not candidates:
            return None
        return random.choice(candidates)

    def _normalize_answer(self, q: Question, value: str) -> str:
        v = (value or "").strip()
        vu = v.upper()
        if q.type == "tf":
            if vu in ["A", "B"]: return vu
            if vu in ["T", "TRUE", "√", "对", "正确", "1", "Y", "YES"]: return "A"
            if vu in ["F", "FALSE", "×", "错", "错误", "0", "N", "NO"]: return "B"
            return vu
        if vu in ["A", "B", "C", "D"]:
            return vu
        return vu

    def record(self, q: Question, user_answer: str) -> bool:
        ua = self._normalize_answer(q, user_answer)
        ans = self._normalize_answer(q, q.answer)
        ok = (ua == ans)

        self.progress["total_answered"] += 1
        if ok:
            self.progress["correct"] += 1
            if q.id in self.progress["wrong_ids"]:
                self.progress["wrong_ids"].remove(q.id)
        else:
            if q.id not in self.progress["wrong_ids"]:
                self.progress["wrong_ids"].append(q.id)

        self.progress["history"].append({
            "id": q.id, "ua": ua, "ans": ans, "correct": ok
        })
        self.progress["history"] = self.progress["history"][-200:]
        self.save_progress()
        return ok


class QuizDialog(QDialog):
    """
    刷题弹窗
    only_wrong: 是否仅错题模式
    """
    def __init__(self, parent: QWidget, engine: QuizEngine, question: Question, title: str = "刷题", only_wrong: bool = False):
        super().__init__(parent)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self.engine = engine
        self.q = question
        self.only_wrong = only_wrong  

        self.setWindowTitle(title)
        
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        self.panel = QFrame(self)
        self.panel.setObjectName("panel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(10)
        root.addWidget(self.panel)

        self.label = QLabel(self.panel)
        self.label.setWordWrap(True)
        self.label.setText(self._render_stem())
        panel_layout.addWidget(self.label)

        self.result = QLabel(self.panel)
        self.result.setWordWrap(True)
        self.result.setText("")
        panel_layout.addWidget(self.result)

        self.buttons: List[QPushButton] = []
        self._setup_buttons(panel_layout)

        self.next_btn = QPushButton("下一题", self.panel)
        self.next_btn.setEnabled(False)
        self.next_btn.setVisible(False)
        self.next_btn.clicked.connect(self._go_next)
        panel_layout.addWidget(self.next_btn)

        close_btn = QPushButton("关闭", self.panel)
        close_btn.clicked.connect(self.accept)
        panel_layout.addWidget(close_btn)

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
        QPushButton:disabled {
            background-color: rgba(60, 60, 60, 120);
            color: rgba(220, 220, 220, 160);
        }
        """)
        self.resize(DIALOG_W, DIALOG_H)

    def _setup_buttons(self, layout):
        if self.q.type == "tf":
            for k, text in [("A", "正确"), ("B", "错误")]:
                b = QPushButton(text, self.panel)
                b.clicked.connect(lambda _, kk=k: self.answer(kk))
                layout.addWidget(b)
                self.buttons.append(b)
        else:
            ch = self.q.choices or {}
            for key in ["A", "B", "C", "D"]:
                if key in ch:
                    b = QPushButton(f"{key}. {ch[key]}", self.panel)
                    b.clicked.connect(lambda _, kk=key: self.answer(kk))
                    layout.addWidget(b)
                    self.buttons.append(b)

    def _render_stem(self) -> str:
        prefix = "【判断】" if self.q.type == "tf" else "【选择】"
        return f"{prefix}{self.q.stem}"

    def _load_question(self, q: Question):
        self.q = q
        self.label.setText(self._render_stem())
        self.result.setText("")
        self.next_btn.setEnabled(False)
        self.next_btn.setVisible(False)

        for b in self.buttons:
            b.setParent(None)
            b.deleteLater()
        self.buttons = []

        layout = self.panel.layout()
        idx = layout.indexOf(self.result)
        insert_at = idx + 1

        if self.q.type == "tf":
            items = [("A", "正确"), ("B", "错误")]
        else:
            ch = self.q.choices or {}
            items = []
            for key in ["A", "B", "C", "D"]:
                if key in ch:
                    items.append((key, f"{key}. {ch[key]}"))

        for k, text in items:
            b = QPushButton(text, self.panel)
            b.clicked.connect(lambda _, kk=k: self.answer(kk))
            layout.insertWidget(insert_at, b)
            insert_at += 1
            self.buttons.append(b)

    def _go_next(self):
        if self.only_wrong:
            q = self.engine.pick_wrong()
        else:
            q = self.engine.pick_random()

        if q is None:
            self.accept()
            return
        
        self._load_question(q)

    def answer(self, user_answer: str):
        ok = self.engine.record(self.q, user_answer)
        ans = (self.q.answer or "").strip().upper()

        self.result.setText(
            ("正确！" if ok else "错了！")
            + f"\n你的答案：{user_answer}\n正确答案：{ans}"
        )
        for b in self.buttons:
            b.setEnabled(False)
        self.next_btn.setEnabled(True)
        self.next_btn.setVisible(True)