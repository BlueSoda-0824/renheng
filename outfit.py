from pathlib import Path

class OutfitManager:
    def __init__(self, pet_asset_dir: Path):
        self.pet_asset_dir = pet_asset_dir
        self.current_outfit = "base"

    def set_outfit(self, outfit_name: str):
        outfit_dir = self.pet_asset_dir / outfit_name
        if outfit_dir.exists() and outfit_dir.is_dir():
            self.current_outfit = outfit_name

    def get_current_dir(self) -> Path:
        return self.pet_asset_dir / self.current_outfit

    def list_outfits(self):
     if not self.pet_asset_dir.exists():
         return []

     # 不作为换装的目录
     EXCLUDE = {"dialogues", "__pycache__", "special", "special_a"}

     return sorted([
         p.name
         for p in self.pet_asset_dir.iterdir()
         if p.is_dir() and p.name not in EXCLUDE
     ])
