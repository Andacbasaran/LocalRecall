# LocalRecall

%100 offline, gizlilik odaklı, 0 MB VRAM akıllı ekran hafızası — açık kaynaklı Windows Recall alternatifi.

## Hedef Özellikler (MVP)
- **Frame Diff Lock** ile yalnızca ekran gerçekten değiştiğinde yakalama (boşta <1% CPU)
- `RapidOCR` (ONNX CPU) ile hızlı metin çıkarımı ve `SQLite FTS5` ile anında tam metin arama
- Gizlilik filtresi: Şifre yöneticileri, gizli tarayıcı sekmeleri ve kullanıcı tanımlı kara liste uygulamalarını otomatik hariç tutma
- Görsel zaman çizelgesi (timeline) ve anahtar kelimeye göre ekran görüntüsü + metin bulma
- Opsiyonel lokal embedding (ONNX) ile anlamsal arama

## Planlanan Teknoloji Yığını
- **Dil:** Python 3.10+
- **Arayüz:** PyQt6 (Zaman Çizelgesi + Arama Penceresi + System Tray)
- **Yakalama & AI:** `mss`, RapidOCR ONNX, SQLite FTS5
- **Dağıtım:** PyInstaller / Inno Setup + Portable ZIP
