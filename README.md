# TOROS — Trafik Odaklı Rota Optimizasyon Sistemi

İstanbul ili sınırlarında teslimat filosunu yöneten ve rotaları optimize eden bir sistem.

Sistem iki ayrı ekrandan oluşur:

| Ekran | Amaç | Algoritma | Google API |
|-------|------|-----------|------------|
| **Harita** (`/`) | Tek aracın durak sırasını optimize eder | Budamalı arama / hibrit arama | Evet — **ücretli** |
| **Filo** (`/filo`) | 150+ teslimatı araçlara dağıtır | Clarke-Wright + 2-opt | Hayır |

## Özellikler

### Filo yönetimi (`/filo`)
- Clarke-Wright tasarruf algoritması ile otomatik teslimat dağıtımı
- Kapasite (kg + m³) ve vardiya süresi **sert kısıt** — ihlalli plan üretilemez
- Best-fit araç ataması: her rotaya sığdıran en küçük araç
- Boğaz geçişi cezası ile yaka bazlı rota kümelenmesi
- Kalıcı rota sırası (`sira` kolonu), sürükle-bırak ile manuel atama
- İlçeye göre gruplanmış teslimat havuzu, araç listesi + detay paneli
- Doluluk / vardiya kullanımı özeti ve filo boyutlandırma uyarıları

### Harita (`/`)
- Google Directions API ile gerçek zamanlı trafik verisi
- Distance Matrix API ile çoklu teslimat noktası optimizasyonu
- Zaman penceresi desteği (belirli saatlerde teslimat zorunluluğu)
- Depoya dönüş rotası (açılıp kapatılabilir, haritada mor kesikli çizgi)
- Adres tabanlı konum arama (Geocoding API)
- Optimize edilmiş rotayı Google Maps'te açma ve link paylaşma
- İstanbul sınır kontrolü (il dışındaki koordinatlar reddedilir)
- Leaflet harita görselleştirmesi (CARTO dark tema)

## Kurulum

```bash
pip install flask requests polyline python-dotenv sqlalchemy psycopg2-binary
```

`.env` dosyası oluşturun:

```
GOOGLE_DIRECTIONS_API_KEY=your_api_key_here
DATABASE_URL=postgresql://kullanici:sifre@localhost:5432/toros
```

> `.env` `.gitignore` içindedir ve **asla commit edilmemelidir.**

Google Cloud Console'da şu API'leri aktif edin:
- Directions API
- Distance Matrix API
- Geocoding API

## Çalıştırma

```bash
python3 app.py
```

Tarayıcıda `http://localhost:5002` adresine gidin.

## Veritabanı

PostgreSQL, dört tablo:

| Tablo | Açıklama |
|-------|----------|
| `araclar` | Filo — kapasite (`max_agirlik`, `max_hacim`), plaka, son rota metrikleri |
| `teslimatlar` | Teslimatlar — yük, termin, randevu penceresi, atanan araç, rota sırası (`sira`) |
| `adresler` | Ayrıştırılmış adres bileşenleri (il, ilçe, mahalle, sokak, bina no, kat, daire) + geocode puanı |
| `depolar` | Çıkış deposu koordinatları |

`teslimatlar.durum` CHECK kısıtı: `beklemede`, `atandi`, `yolda`, `teslim_edildi`.

**Geocoding aynı adres için asla iki kez çalıştırılmaz** — sonuçlar `adresler` tablosunda saklanır. Bir teslimat silindiğinde, adres başka teslimat tarafından kullanılmıyorsa adres kaydı da silinir.

## Dosya Yapısı

| Dosya | Açıklama |
|-------|----------|
| `app.py` | Flask sunucusu, REST API, Clarke-Wright dağıtım algoritması, İstanbul sınır kontrolü |
| `coklu_teslimat.py` | Harita rota optimizasyonu (budamalı arama, hibrit arama, 2-opt, Distance Matrix) |
| `rota.py` | Tek rota hesaplama (Google Directions API) |
| `harita.py` | HTML harita oluşturma |
| `templates/index.html` | Harita arayüzü (form + Leaflet) |
| `templates/filo.html` | Filo yönetimi arayüzü (araç listesi + detay paneli + teslimat havuzu) |

## Algoritmalar

### Clarke-Wright tasarruf algoritması — filo dağıtımı

`POST /api/dagit`. Hangi teslimatın hangi araca gideceğini ve araç içi durak sırasını birlikte çözer.

1. Her teslimat tek başına bir rota olarak başlar (depo → teslimat → depo)
2. Her (i, j) çifti için tasarruf hesaplanır: `depo→i + depo→j − i→j`
3. Tasarruflar büyükten küçüğe işlenir; iki rota **ancak** kapasite ve vardiya süresi aşılmıyorsa ve birleşme noktaları rota uçlarındaysa birleştirilir
4. Her rota 2-opt ile iç sıralaması iyileştirilir
5. Rotalar hacme göre sıralanır, her birine sığdıran en küçük araç atanır (best-fit)

Mesafe modeli Google API kullanmaz: haversine × 1.35 yol sapma katsayısı, farklı yakalar arasında +12 km Boğaz köprüsü cezası. Bu ceza tasarruf hesabına girdiği için algoritma doğal olarak aynı yakadaki teslimatları kümeler.

Parametreler `app.py` başında tanımlıdır:

| Parametre | Değer | Açıklama |
|-----------|-------|----------|
| `SERVIS_DK` | 20 dk | Teslimat + montaj taban süresi |
| `KAT_DK` | 2 dk | Her kat için ek süre |
| `VARDIYA_DK` | 540 dk | 9 saatlik vardiya |
| `HIZ_KMH` | 25 km/s | İstanbul içi ortalama hız |
| `YOL_SAPMA` | 1.35 | Kuş uçuşu → gerçek yol çarpanı |
| `KOPRU_KM` | 12 km | Boğaz geçişi cezası |
| `HEDEF_DOLULUK` | %70–82 | Filo boyutlandırma uyarı bandı |

> Kat süresi sonucu en çok değiştiren varsayımdır; sahadan gerçek veri geldiğinde önce burası güncellenmelidir.

**Bilinen sınır:** Clarke-Wright randevu pencerelerini dikkate almaz. Pencere mantığı şu an yalnızca `coklu_teslimat.py` içinde (tek araç yolunda) mevcuttur.

### Budamalı arama (branch and bound) — harita, ≤14 teslimat

Optimal çözümü bulur. En yakın komşu ile başlangıç eşiği belirler, alt sınır hesabıyla umutsuz dallanmaları budar.

### Hibrit arama — harita, 15+ teslimat

En yakın komşu + 2-opt iyileştirme + 20 rastgele başlangıç ile yakın-optimal çözüm bulur. Deterministiktir (`random.seed(42)`).

## API Maliyeti

**Filo sayfasındaki dağıtım (`/api/dagit`) hiçbir Google API çağrısı yapmaz — maliyeti sıfırdır.**

Ücret yalnızca harita sayfasının `/optimize` ucunda oluşur ve **teslimat sayısının karesiyle** büyür. Distance Matrix n×n süre matrisi çeker (10×10'luk parçalar halinde), üstüne polyline için bir Directions isteği gelir:

| Teslimat | Matris elemanı |
|----------|----------------|
| 11 | 144 |
| 30 | 961 |
| 150 | 22.801 |

`departure_time` + `traffic_model` parametreleri kullanıldığı için daha pahalı tarifeye girer. Filo dağıtımının haversine ile yapılmasının sebebi budur.

## Örnek Sorgular

Tüm teslimatları açığa alma (atamaları temizleme):

```bash
psql -U toros_user -d toros -c "UPDATE teslimatlar SET arac_id = NULL, sira = NULL, durum = 'beklemede'"
```
