import json
import polyline
from rota import rota_hesapla
from datetime import datetime


def polyline_coz(encoded):
    return [[lat, lon] for lat, lon in polyline.decode(encoded)]


def harita_html(baslangic, hedef, kalkis_zamani, dosya="harita.html"):
    sonuc = rota_hesapla(baslangic, hedef, kalkis_zamani)
    if sonuc is None:
        print("Rota bulunamadi.")
        return

    rota_coords = polyline_coz(sonuc["polyline"])

    adim_segmentler = []
    for adim in sonuc["adimlar"]:
        coords = polyline_coz(adim["polyline"])
        adim_segmentler.append(coords)

    merkez_lat = sum(c[0] for c in rota_coords) / len(rota_coords)
    merkez_lon = sum(c[1] for c in rota_coords) / len(rota_coords)

    fark_sn = sonuc["trafik_sure_sn"] - sonuc["normal_sure_sn"]
    if fark_sn > 300:
        trafik_durum = "Yoğun"
        trafik_renk = "#f44336"
    elif fark_sn > 120:
        trafik_durum = "Orta"
        trafik_renk = "#ff9800"
    else:
        trafik_durum = "Akıcı"
        trafik_renk = "#00e676"

    saat_str = kalkis_zamani.strftime("%H:%M")
    tarih_str = kalkis_zamani.strftime("%d.%m.%Y")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>TOROS - Rota Haritasi</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; }}
  #map {{ width: 100%; height: calc(100vh - 90px); }}
  .bilgi-panel {{
    height: 90px; background: #16213e; display: flex;
    align-items: center; justify-content: space-around; padding: 0 15px;
    border-top: 2px solid #0f3460;
  }}
  .bilgi-kutu {{
    text-align: center; padding: 8px 16px;
    background: #0f3460; border-radius: 8px;
  }}
  .bilgi-kutu .deger {{ font-size: 20px; font-weight: bold; color: #e94560; }}
  .bilgi-kutu .etiket {{ font-size: 11px; color: #a0a0b0; margin-top: 2px; }}
  .adres-kutu {{
    background: rgba(22, 33, 62, 0.95); padding: 10px 14px;
    border-radius: 8px; color: #eee; font-size: 12px; max-width: 300px;
  }}
  .adres-kutu b {{ color: #e94560; }}
</style>
</head>
<body>
<div id="map"></div>
<div class="bilgi-panel">
  <div class="bilgi-kutu">
    <div class="deger">{sonuc['mesafe']}</div>
    <div class="etiket">Mesafe</div>
  </div>
  <div class="bilgi-kutu">
    <div class="deger">{sonuc['trafik_sure']}</div>
    <div class="etiket">Trafikli Sure</div>
  </div>
  <div class="bilgi-kutu">
    <div class="deger">{sonuc['normal_sure']}</div>
    <div class="etiket">Normal Sure</div>
  </div>
  <div class="bilgi-kutu">
    <div class="deger" style="color:{trafik_renk}">{trafik_durum}</div>
    <div class="etiket">Trafik</div>
  </div>
  <div class="bilgi-kutu">
    <div class="deger">{saat_str}</div>
    <div class="etiket">{tarih_str}</div>
  </div>
  <div class="bilgi-kutu">
    <div class="deger">{sonuc['ozet']}</div>
    <div class="etiket">Rota</div>
  </div>
</div>
<script>
var map = L.map('map', {{
  center: [{merkez_lat}, {merkez_lon}],
  zoom: 13,
  zoomControl: true,
}});

L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution: '&copy; OSM &copy; CARTO',
  maxZoom: 19,
}}).addTo(map);

var rota = {json.dumps(rota_coords)};
L.polyline(rota, {{
  color: '#00b0ff',
  weight: 5,
  opacity: 0.9,
}}).addTo(map);

L.marker(rota[0], {{
  icon: L.divIcon({{
    html: '<div style="background:#00e676;color:#000;padding:4px 8px;border-radius:12px;font-weight:bold;font-size:12px;white-space:nowrap;">Baslangic</div>',
    className: '',
  }})
}}).addTo(map);

L.marker(rota[rota.length - 1], {{
  icon: L.divIcon({{
    html: '<div style="background:#e94560;color:#fff;padding:4px 8px;border-radius:12px;font-weight:bold;font-size:12px;white-space:nowrap;">Hedef</div>',
    className: '',
  }})
}}).addTo(map);

var bounds = L.latLngBounds(rota);
map.fitBounds(bounds, {{padding: [40, 40]}});

var bilgi = L.control({{position: 'topright'}});
bilgi.onAdd = function() {{
  var div = L.DomUtil.create('div', 'adres-kutu');
  div.innerHTML = '<b>Baslangic:</b> {sonuc["baslangic_adres"]}<br><br>'
    + '<b>Hedef:</b> {sonuc["hedef_adres"]}';
  return div;
}};
bilgi.addTo(map);
</script>
</body>
</html>"""

    with open(dosya, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Harita {dosya} dosyasina kaydedildi.")
    print(f"Rota: {sonuc['ozet']} | {sonuc['mesafe']} | Trafik: {sonuc['trafik_sure']}")
    return dosya


if __name__ == "__main__":
    harita_html(
        baslangic=(40.9800, 28.8720),
        hedef=(41.0020, 28.7730),
        kalkis_zamani=datetime(2026, 8, 11, 15, 0),
    )
