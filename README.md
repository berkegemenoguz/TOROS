# TOROS — Trafik Odaklı Rota Optimizasyon Sistemi

İstanbul ili sınırlarında teslimat filosunu yöneten ve rotaları optimize eden bir sistem.

Sistem iki ayrı ekrandan oluşur:

| Ekran | Amaç | Algoritma | Google API |
|-------|------|-----------|------------|
| **Harita** (`/`) | Tek aracın durak sırasını optimize eder | Budamalı arama / hibrit arama | Evet — **ücretli** |
| **Filo** (`/filo`) | 150+ teslimatı bölge araçlarına dağıtır | Doluluk-eşikli bölge dağıtımı + 2-opt | Hayır |

## Özellikler

### Filo yönetimi (`/filo`)
- Doluluk-eşikli bölge dağıtımı: her araç bir bölgeye hizmet eder, yükler bölgesinde birikir, araç ekonomik doluluğa ulaşınca (ya da termin/bekleme tavanı zorlayınca) çıkar
- Kapasite (kg + m³) **sert kısıt**; vardiya süresi aşılırsa **uyarı** verir
- Araç ataması bölgeye göre: bölgenin yükü kendi aracına, öncelik sırasıyla (termin → yaş) sığdığı kadar
- Esnaf açık rota: rota şoförün evinde biter (ev yoksa depoya döner)
- Boğaz geçişi cezası ile yaka bazlı mesafe modeli
- Kalıcı rota sırası (`sira` kolonu), sürükle-bırak ile manuel atama
- İlçeye göre gruplanmış teslimat havuzu + bölge durumu paneli (hazır/bekleyen)
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
| `app.py` | Flask sunucusu, REST API, doluluk-eşikli bölge dağıtım algoritması, İstanbul sınır kontrolü |
| `coklu_teslimat.py` | Harita rota optimizasyonu (budamalı arama, hibrit arama, 2-opt, Distance Matrix) |
| `rota.py` | Tek rota hesaplama (Google Directions API) |
| `harita.py` | HTML harita oluşturma |
| `templates/index.html` | Harita arayüzü (form + Leaflet) |
| `templates/filo.html` | Filo yönetimi arayüzü (araç listesi + detay paneli + teslimat havuzu + bölge durumu) |
| `migrations/` | Sıralı SQL şema değişiklikleri (elle uygulanır; şema Postgres'te tutulur) |

## Algoritmalar

### Doluluk-eşikli bölge dağıtımı — filo dağıtımı

`POST /api/dagit`. Her araç bir **bölgeye** hizmet eder (18 bölge, ilçe → bölge eşlemesi `BOLGELER` sabitindedir). Yükler bölgesinde birikir; araç yarım çıkmaz, ekonomik doluluğa ulaşınca yola çıkar. `GET /api/havuz` bu birikim durumunu (hangi bölge hazır/bekliyor) salt-okunur döndürür.

**Bir bölge şu koşullardan biriyle "hazır" olur (öncelik sırası: termin > bekleme > doluluk):**
1. Bekleyen bir yükün termini bugün ya da geçmiş — **sert kısıt, eşiği ezer**
2. En eski yükün yaşı `BEKLEME_TAVANI_GUN`'u doldurmuş — sonsuz beklemeyi keser (sayaç en eski yüke bağlı, araca değil)
3. Doluluk (`max(ağırlık%, hacim%)`) `DOLULUK_ESIK`'i geçmiş — ekonomik yumuşak hedef

**Sadece hazır bölgeler çıkar. Her hazır bölge için:**
1. Bölgenin yükleri öncelik sırasıyla (termin, sonra yaş) **kendi aracına** sığdığı kadar yüklenir; sığmayan havuzda bekler
2. Durak sırası **en yakın komşu + 2-opt** ile çözülür
3. **Esnaf açık rota:** rota depo → duraklar → şoförün evinde biter. Eve dönüş bacağı **yola** (2-opt hedefi) girer ama **vardiyaya** (mesai kısıtı) girmez — evine uzak biten rota mesafe metriğinde kötü görünür, algoritma kaçınır. Şoförün ev konumu yoksa rota depoya döner (kapalı)
4. Aracı yolda (meşgul, `durum='atandi'` yükü olan) olan bölge o gün çıkamaz

Mesafe modeli Google API kullanmaz: haversine × 1.35 yol sapma katsayısı, farklı yakalar arasında +12 km Boğaz köprüsü cezası.

Parametreler `app.py` başında tanımlıdır:

| Parametre | Değer | Açıklama |
|-----------|-------|----------|
| `SERVIS_DK` | 25 dk | Teslimat başına sabit süre (montaj + taşıma dahil) |
| `VARDIYA_DK` | 540 dk | 9 saatlik vardiya (aşılırsa uyarı) |
| `HIZ_KMH` | 25 km/s | İstanbul içi ortalama hız |
| `YOL_SAPMA` | 1.35 | Kuş uçuşu → gerçek yol çarpanı |
| `KOPRU_KM` | 12 km | Boğaz geçişi cezası |
| `DOLULUK_ESIK` | %80 | Bölgenin çıkması için doluluk eşiği |
| `BEKLEME_TAVANI_GUN` | 3 gün | En eski yük için zorunlu çıkış tavanı |
| `HEDEF_DOLULUK` | %70–82 | Filo boyutlandırma uyarı bandı |

> Servis süresi sonucu en çok değiştiren varsayımdır; sahadan gerçek veri geldiğinde önce burası güncellenmelidir. Sürücü kâğıdındaki "varış saati" alanı bu ölçümün ilk halkasıdır.

**Bilinen sınır:** Dağıtım randevu pencerelerini dikkate almaz. Pencere mantığı şu an yalnızca `coklu_teslimat.py` içinde (tek araç yolunda) mevcuttur.

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
