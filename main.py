import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QAction, QIcon
from pet import DesktopPet  


local_pets = {"刃": None, "丹恒": None}

def spawn_local_pet(name, assets_dir, save_root):
    if local_pets.get(name): return
    folder = "pet1" if name == "刃" else "pet2"
    p = DesktopPet(name, assets_dir / folder, save_root / folder)
    
    screen = QApplication.primaryScreen().availableGeometry()
    center_x = screen.center().x()
    bottom_y = screen.bottom() - p.height() - 20 

    if name == "刃": p.move(center_x - 320, bottom_y)
    else: p.move(center_x + 120, bottom_y)
    
    p.show()
    local_pets[name] = p

def resource_path(rel_path: str) -> str:
    base = getattr(sys, "_MEIPASS", Path(__file__).parent)
    return str(Path(base) / rel_path)

def get_exe_dir() -> Path:
    if getattr(sys, 'frozen', False): return Path(sys.executable).parent
    return Path(__file__).parent

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    assets_dir = Path(resource_path("assets"))
    save_root = get_exe_dir() / "userdata"
    save_root.mkdir(parents=True, exist_ok=True)
    
    spawn_local_pet("刃", assets_dir, save_root)
    spawn_local_pet("丹恒", assets_dir, save_root)

    tray = QSystemTrayIcon(QIcon(resource_path("tray.png")), app)
    menu = QMenu()

    act_blade = QAction("召回 刃", app, triggered=lambda: spawn_local_pet("刃", assets_dir, save_root))
    act_danheng = QAction("召回 丹恒", app, triggered=lambda: spawn_local_pet("丹恒", assets_dir, save_root))
    act_quit = QAction("退出程序", app, triggered=app.quit)

    menu.addAction(act_blade)
    menu.addAction(act_danheng)
    menu.addSeparator()
    menu.addAction(act_quit)

    tray.setContextMenu(menu)
    tray.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()