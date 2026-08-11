# TOROS - Trafik Odakli Rota Optimizasyon Sistemi

Istanbul'un Bakirköy, Bahcelievler ve Kucukcekmece ilcelerinde teslimat rotalarini trafik verisiyle optimize eden bir sistem.

## Ozellikler

- Google Directions API ile gercek zamanli trafik verisi
- Distance Matrix API ile coklu teslimat noktasi optimizasyonu
- Budamali arama (≤14 teslimat) ve hibrit arama (15+ teslimat) algoritmalari
- Zaman penceresi destegi (belirli saatlerde teslimat zorunlulugu)
- Depoya donus rotasi (acilip kapatilabilir)
- Adres tabanli konum arama (Geocoding API)
- Optimize edilmis rotayi Google Maps'te acma ve link paylasma
- Leaflet harita gorsellestirmesi (CARTO dark tema)

## Kurulum

```bash
pip install flask requests polyline python-dotenv
```

`.env` dosyasi olusturun:

```
GOOGLE_DIRECTIONS_API_KEY=your_api_key_here
```

Google Cloud Console'da su API'leri aktif edin:
- Directions API
- Distance Matrix API
- Geocoding API

## Calistirma

```bash
python3 app.py
```

Tarayicida `http://localhost:5050` adresine gidin.

## Dosya Yapisi

| Dosya | Aciklama |
|-------|----------|
| `app.py` | Flask web sunucusu, API endpoint'leri |
| `coklu_teslimat.py` | Rota optimizasyon algoritmalari (budamali arama, hibrit arama, 2-opt) |
| `rota.py` | Tek rota hesaplama (Google Directions API) |
| `harita.py` | HTML harita olusturma |
| `templates/index.html` | Web arayuzu (form + Leaflet harita) |

## Algoritmalar

**Budamali Arama (Branch and Bound):** 14 ve alti teslimat icin optimal cozum bulur. En yakin komsu ile baslangic esigi belirler, alt sinir hesabiyla dallanmalari budar.

**Hibrit Arama:** 15+ teslimat icin en yakin komsu + 2-opt iyilestirme + 20 rastgele baslangic noktasi ile yakin-optimal cozum bulur.

## API Maliyeti

Ornek: 2 teslimatli bir rota ~$0.02, 30 teslimatli bir rota ~$0.15 tutar (Distance Matrix + Directions).
