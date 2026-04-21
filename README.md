# Micky — Telefonunu PC Mikrofonuna Çevir

WO Mic'e modern alternatif. Telefonunun mikrofonunu PC'de kullan — Discord,
Zoom, OBS, oyun — hepsinde "Micky" adında bir mikrofon görünür.

## Final paket

`release/` klasöründe her şey hazır:

| Dosya | Açıklama | Boyut |
|-------|----------|-------|
| **`Micky-Kurulum.exe`** | Tam kurulum — Python, sürücü, APK hepsi dahil | 59 MB |
| `Micky.exe` | Taşınabilir ana uygulama (kurulumsuz) | 32 MB |
| `Micky-Kaldir.exe` | Bağımsız kaldırma aracı | 11 MB |
| `Micky.apk` | Android uygulaması | 7 MB |

### Kurulum (önerilen)

**`Micky-Kurulum.exe`** çift tıkla → *Kur*:

1. `%LOCALAPPDATA%\Programs\Micky` altına yüklenir (yönetici gerekmez)
2. Başlat Menüsü + Masaüstü kısayolu eklenir
3. *Uygulamalar ve özellikler* listesine kayıt edilir
4. Android APK kurulum klasörüne kopyalanır
5. Seçeneklidir: sanal mikrofon sürücüsü (VB-Cable) de kurulur — gerçek
   mikrofon gibi görünmesi için gerekli (UAC ister)

**Kaldırmak için**: Windows *Apps & features* listesinden, ya da Başlat
Menüsü'nden "Micky Kaldır".

### Taşınabilir kullanım

Kurulum istemezsen doğrudan **`Micky.exe`**'yi çalıştır. Aynı klasörde
`vbcable/` varsa otomatik bulunur, yoksa yüklenmiş VB-Cable kullanılır.

## Özellikler

- Modern koyu tema, Material 3 Android UI
- **QR kod ile eşleşme** — IP yazmaya gerek yok
- **4 bağlantı modu**: Wi-Fi / USB / Wi-Fi Direct / Bluetooth
- **Konuşma filtresi** (VAD) — klavye tıkırtısı, fan uğultusu geçmez, sadece
  insan sesi açar
- **Ses efektleri**: Normal / Robot / Eko / Derin / Uzay / Yüksek —
  PC ve telefondan seçilebilir, anında senkron
- **Mute senkronu** — telefondan aldığında PC'de de, tersi de
- **Hoparlörden dinle** — yayını kesmeden monitör sesi aç/kapa
- **Mic orb** — telefon ekranında nabız atan büyük düğme, dokununca mute
- **Mod uyumsuzluğu uyarısı** — PC USB telefon Wi-Fi ise kırmızı banner
- **"Micky" olarak adlandır** — Windows'taki `CABLE Output (VB-Audio)` kaydını
  `Micky` yapar, üç ayrı registry konumuna yazar; diğer uygulamalarda
  mikrofon listesinde **Micky** görünür

## Telefon tarafı

1. `Micky.apk`'yı telefona kopyala, yükle
2. Mikrofon + bildirim izinlerini ver
3. **Ayarlar → QR tara** → PC ekranındaki karekodu oku
4. Ana ekranda büyük mic orb'a dokun → yayın başlar
5. Konuştukça daire büyür. Dokun → mute.

## Kullanım akışı (ilk sefer)

1. `Micky-Kurulum.exe` → Kur
2. Sanal mikrofon kurulum penceresinde *Install Driver* → PC'yi yeniden başlat
3. Micky'yi aç → Micky Sanal Mikrofon panelinde **"'Micky' olarak adlandır"**
   → UAC onayla (bekle, Micky kapanmaz) → popup'ta "Başarılı" görünce
   Discord/Zoom'u kapatıp tekrar aç
4. Discord mikrofon ayarından **Micky**'yi seç
5. Telefonda Micky uygulamasını aç, QR kodu tara → *Yayını başlat*

## Protokol (teknik)

- TCP, 12-byte handshake (`MIKY` + sample_rate + channels + bits)
- Sonrası çerçeveli mesajlar: `[1 byte type][4 byte LE length][payload]`
- Tip 1 AUDIO (PCM 16-bit LE), 2 MUTE, 3 PING, 4 MODE, 5 NOTE, 6 FX
- 48 kHz · 16 bit · Mono, `VOICE_COMMUNICATION` kaynağı (eko + AGC)
- Sinyal zinciri: Konuşma filtresi → Noise gate → Kazanç → Efekt → Çıkış

## Geliştirici notları

Kaynak kod:
- `pc/` — Python sunucu + UI (customtkinter + sounddevice)
- `android/` — Kotlin Android app (Material 3, ViewBinding, Fragments)
- `installer/` — Python kurulum + kaldırma

Yeniden derlemek için:
```powershell
python build_release.py
```
Release artifact'ları `release/` altına düşer.
