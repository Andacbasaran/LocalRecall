# LocalRecall

%100 offline, gizlilik odaklı, **0 MB VRAM** akıllı ekran hafızası — açık kaynaklı Windows Recall alternatifi.

## Öne Çıkan Özellikler
- **Frame Diff Lock & Boşta Uyku Modu:** Ekran gerçekten değişmediğinde veya kullanıcı hareketsizken (`GetLastInputInfo`) yakalama yapmaz (<1% CPU).
- **RapidOCR (ONNX CPU) + Görsel Vurgulama:** 0 MB VRAM kullanarak ekrandaki metinleri ve konumlarını çıkarır; arama yaptığınızda **aranan kelimeleri doğrudan ekran görüntüsü üzerinde kutuyla vurgular**. Metin kutularına tıklayarak tek tıkla kopyalayabilirsiniz.
- **Hibrit Arama Motoru (`SQLite FTS5` + Bulanık N-Gram RRF):** Hem anında tam metin araması yapar hem de OCR ve Türkçe karakter farklarına (`ı/i`, `ş/s`, küçük yazım hataları) dayanıklı akıllı sıralama sunar.
- **Gizlilik Öncelikli Tasarım:**
  - Şifre yöneticileri (1Password, Bitwarden, KeePass vb.) ve gizli tarayıcı sekmelerini (`Incognito`, `InPrivate`, `Gizli`) otomatik hariç tutar.
  - Sistem tepsisinden ve İstatistik penceresinden tek tıkla **"Son 15 Dakikayı Sil"** özelliği.
  - Yapılandırılabilir saklama süresi (otomatik eski kayıt temizliği) ve tamamen lokal depolama (`%LOCALAPPDATA%\LocalRecall`).
- **Zengin PyQt6 Arayüzü & System Tray:**
  - Küçük resimli (thumbnail) sonuç listesi, yakınlaştırılabilir (`Ctrl + Tekerlek`) önizleme, zaman çizelgesi (timeline) kaydırıcısı, çoklu monitör seçimi, görsel dışa aktarma (PNG/WebP), istatistik & depolama yönetimi ve Windows başlangıçta otomatik başlatma.
- **Global Kısayol Tuşu:** Herhangi bir uygulamadayken `Ctrl+Shift+Space` ile LocalRecall'ı anında öne getirip aramaya odaklanın.

## Kurulum ve Çalıştırma

Python 3.10+ gerektirir (Windows).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Sistem tepsisinde gizli başlatmak için:
```powershell
.\.venv\Scripts\python.exe main.py --minimized
```

## Klavye Kısayolları
| Kısayol | İşlev |
| --- | --- |
| `Ctrl+Shift+Space` | Sistem genelinde LocalRecall'ı aç ve aramaya odaklan (özelleştirilebilir) |
| `Ctrl+F` | Arama kutusuna odaklan |
| `Alt+Sol` / `Alt+Sağ` | Zaman çizelgesinde önceki / sonraki kayda geç |
| `Ctrl + Fare Tekerleği` | Ekran görüntüsünü yakınlaştır / uzaklaştır (çift tıkla sıfırla) |
| `Delete` | Seçili kaydı sil |

## Testler ve Portable Paketleme

```powershell
# Birim testlerini çalıştır
.\.venv\Scripts\pytest -v

# Portable Windows ZIP paketi oluştur (PyInstaller gerekir)
.\.venv\Scripts\python.exe build.py
```

## Teknoloji Yığını
- **Dil:** Python 3.10+
- **Arayüz:** PyQt6 (Zaman Çizelgesi + İnteraktif OCR Önizleme + İstatistikler + System Tray)
- **Yakalama & AI:** `mss`, `RapidOCR` (ONNX Runtime CPU), `SQLite FTS5` + Hibrit N-Gram RRF
- **Dağıtım:** PyInstaller + Portable ZIP
