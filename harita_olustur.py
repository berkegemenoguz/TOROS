import pandas as pd
import numpy as np
import json
import osmnx as ox
from rota_bul import rota_hesapla, nodes, agirliklar


G = ox.graph_from_place("Bakırköy, Istanbul, Turkey", network_type="drive")
_, edges_gdf = ox.graph_to_gdfs(G)


def edge_geometri(u, v, key=0):
    try:
        row = edges_gdf.loc[(u, v, key)]
        if row.geometry is not None:
            return [[c[1], c[0]] for c in row.geometry.coords]
    except KeyError:
        pass
    u_lat, u_lon = nodes.loc[u, "lat"], nodes.loc[u, "lon"]
    v_lat, v_lon = nodes.loc[v, "lat"], nodes.loc[v, "lon"]
    return [[u_lat, u_lon], [v_lat, v_lon]]


def harita_html(baslangic_lat, baslangic_lon, hedef_lat, hedef_lon, kategori, saat, dosya="harita.html"):
    sonuc = rota_hesapla(baslangic_lat, baslangic_lon, hedef_lat, hedef_lon, kategori, saat)
    if sonuc is None:
        print("Rota bulunamadi, harita olusturulamadi.")
        return

    print("Rota geometrisi olusturuluyor...")
    rota_coords = []
    for i in range(len(sonuc["rota_nodelar"]) - 1):
        u = sonuc["rota_nodelar"][i]
        v = sonuc["rota_nodelar"][i + 1]
        segment = edge_geometri(u, v)
        if rota_coords and segment:
            rota_coords.extend(segment[1:])
        else:
            rota_coords.extend(segment)

    print("Trafik katmani olusturuluyor...")
    saat_agirlik = agirliklar[(agirliklar["kategori"] == kategori) & (agirliklar["saat"] == saat)]

    trafik_segmentler = []
    for _, row in saat_agirlik.iterrows():
        coords = edge_geometri(int(row["u"]), int(row["v"]), int(row.get("key", 0)))
        trafik_segmentler.append({
            "coords": coords,
            "hiz": row["hiz_kmh"],
        })

    merkez_lat = sum(c[0] for c in rota_coords) / len(rota_coords)
    merkez_lon = sum(c[1] for c in rota_coords) / len(rota_coords)

    kategori_tr = {
        "hafta_ici": "Hafta İçi",
        "hafta_sonu": "Hafta Sonu",
        "resmi_tatil": "Resmi Tatil",
        "bayram_blogu": "Bayram Bloğu",
    }

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
  #map {{ width: 100%; height: calc(100vh - 80px); }}
  .bilgi-panel {{
    height: 80px; background: #16213e; display: flex;
    align-items: center; justify-content: space-around; padding: 0 20px;
    border-top: 2px solid #0f3460;
  }}
  .bilgi-kutu {{
    text-align: center; padding: 8px 20px;
    background: #0f3460; border-radius: 8px;
  }}
  .bilgi-kutu .deger {{ font-size: 22px; font-weight: bold; color: #e94560; }}
  .bilgi-kutu .etiket {{ font-size: 12px; color: #a0a0b0; margin-top: 2px; }}
  .lejant {{
    background: rgba(22, 33, 62, 0.95); padding: 12px 16px;
    border-radius: 8px; color: #eee; font-size: 13px; line-height: 22px;
  }}
  .lejant-baslik {{ font-weight: bold; margin-bottom: 6px; }}
  .lejant-renk {{
    display: inline-block; width: 30px; height: 4px;
    vertical-align: middle; margin-right: 6px; border-radius: 2px;
  }}
</style>
</head>
<body>
<div id="map"></div>
<div class="bilgi-panel">
  <div class="bilgi-kutu">
    <div class="deger">{sonuc['sure_dk']}</div>
    <div class="etiket">Dakika</div>
  </div>
  <div class="bilgi-kutu">
    <div class="deger">{len(sonuc['rota_nodelar'])}</div>
    <div class="etiket">Düğüm</div>
  </div>
  <div class="bilgi-kutu">
    <div class="deger">{kategori_tr.get(kategori, kategori)}</div>
    <div class="etiket">Gün Tipi</div>
  </div>
  <div class="bilgi-kutu">
    <div class="deger">{saat:02d}:00</div>
    <div class="etiket">Saat</div>
  </div>
</div>
<script>
var map = L.map('map', {{
  center: [{merkez_lat}, {merkez_lon}],
  zoom: 14,
  zoomControl: true,
}});

L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution: '&copy; OSM &copy; CARTO',
  maxZoom: 19,
}}).addTo(map);

var trafik = {json.dumps(trafik_segmentler)};

function hizRenk(hiz) {{
  if (hiz >= 50) return '#00e676';
  if (hiz >= 35) return '#76ff03';
  if (hiz >= 25) return '#ffeb3b';
  if (hiz >= 15) return '#ff9800';
  return '#f44336';
}}

trafik.forEach(function(s) {{
  L.polyline(s.coords, {{
    color: hizRenk(s.hiz),
    weight: 3,
    opacity: 0.5,
  }}).addTo(map);
}});

var rota = {json.dumps(rota_coords)};
L.polyline(rota, {{
  color: '#00b0ff',
  weight: 6,
  opacity: 0.9,
}}).addTo(map);

L.marker(rota[0], {{
  icon: L.divIcon({{
    html: '<div style="background:#00e676;color:#000;padding:4px 8px;border-radius:12px;font-weight:bold;font-size:12px;white-space:nowrap;">Başlangıç</div>',
    className: '',
  }})
}}).addTo(map);

L.marker(rota[rota.length - 1], {{
  icon: L.divIcon({{
    html: '<div style="background:#e94560;color:#fff;padding:4px 8px;border-radius:12px;font-weight:bold;font-size:12px;white-space:nowrap;">Hedef</div>',
    className: '',
  }})
}}).addTo(map);

var lejant = L.control({{position: 'topright'}});
lejant.onAdd = function() {{
  var div = L.DomUtil.create('div', 'lejant');
  div.innerHTML = '<div class="lejant-baslik">Trafik Hızı</div>'
    + '<span class="lejant-renk" style="background:#00e676"></span>50+ km/h<br>'
    + '<span class="lejant-renk" style="background:#76ff03"></span>35-50 km/h<br>'
    + '<span class="lejant-renk" style="background:#ffeb3b"></span>25-35 km/h<br>'
    + '<span class="lejant-renk" style="background:#ff9800"></span>15-25 km/h<br>'
    + '<span class="lejant-renk" style="background:#f44336"></span>&lt;15 km/h';
  return div;
}};
lejant.addTo(map);
</script>
</body>
</html>"""

    with open(dosya, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nHarita {dosya} dosyasina kaydedildi.")
    return dosya


if __name__ == "__main__":
    harita_html(
        baslangic_lat=40.9800, baslangic_lon=28.8720,
        hedef_lat=40.9720, hedef_lon=28.8370,
        kategori="hafta_ici", saat=8,
        dosya="harita.html",
    )
