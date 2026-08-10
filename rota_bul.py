import pandas as pd
import numpy as np
import heapq
from math import sqrt

nodes = pd.read_csv("data/nodes.csv", index_col=0)
agirliklar = pd.read_csv("data/edge_agirliklar.csv")

print("Graf yukleniyor...")
graf = {}
for _, row in agirliklar.iterrows():
    key = (row["kategori"], int(row["saat"]))
    if key not in graf:
        graf[key] = {}
    u = int(row["u"])
    v = int(row["v"])
    if u not in graf[key]:
        graf[key][u] = []
    graf[key][u].append((v, row["sure_dk"]))

tum_nodelar = set(nodes.index)
print(f"Graf yuklendi: {len(graf)} kategori-saat kombinasyonu, {len(tum_nodelar)} node")


def en_yakin_node(lat, lon):
    mesafeler = np.sqrt(((nodes["lat"] - lat) * 111) ** 2 + ((nodes["lon"] - lon) * 85) ** 2)
    idx = mesafeler.idxmin()
    return idx, mesafeler[idx]


def dijkstra(baslangic, hedef, kategori, saat):
    komsu = graf.get((kategori, saat), {})
    if not komsu:
        return None, float("inf")

    mesafe = {baslangic: 0}
    onceki = {baslangic: None}
    kuyruk = [(0, baslangic)]

    while kuyruk:
        d, u = heapq.heappop(kuyruk)
        if u == hedef:
            break
        if d > mesafe.get(u, float("inf")):
            continue
        for v, agirlik in komsu.get(u, []):
            yeni_d = d + agirlik
            if yeni_d < mesafe.get(v, float("inf")):
                mesafe[v] = yeni_d
                onceki[v] = u
                heapq.heappush(kuyruk, (yeni_d, v))

    if hedef not in onceki:
        return None, float("inf")

    rota = []
    node = hedef
    while node is not None:
        rota.append(node)
        node = onceki[node]
    rota.reverse()
    return rota, mesafe[hedef]


def rota_hesapla(baslangic_lat, baslangic_lon, hedef_lat, hedef_lon, kategori, saat):
    bas_node, bas_mesafe = en_yakin_node(baslangic_lat, baslangic_lon)
    hed_node, hed_mesafe = en_yakin_node(hedef_lat, hedef_lon)

    print(f"Baslangic node: {bas_node} ({bas_mesafe:.3f} km uzakta)")
    print(f"Hedef node: {hed_node} ({hed_mesafe:.3f} km uzakta)")

    rota, sure = dijkstra(bas_node, hed_node, kategori, saat)

    if rota is None:
        print("Rota bulunamadi!")
        return None

    koordinatlar = [(nodes.loc[n, "lat"], nodes.loc[n, "lon"]) for n in rota]

    print(f"Rota bulundu: {len(rota)} node, {sure:.1f} dakika")
    return {
        "rota_nodelar": rota,
        "koordinatlar": koordinatlar,
        "sure_dk": round(sure, 1),
        "kategori": kategori,
        "saat": saat,
    }


if __name__ == "__main__":
    # Bakirkoy Meydani -> Atakoy Sahil
    sonuc = rota_hesapla(
        baslangic_lat=40.9800, baslangic_lon=28.8720,
        hedef_lat=40.9720, hedef_lon=28.8370,
        kategori="hafta_ici", saat=8,
    )

    if sonuc:
        print(f"\nKategori: {sonuc['kategori']}, Saat: {sonuc['saat']}:00")
        print(f"Toplam sure: {sonuc['sure_dk']} dakika")
        print(f"Rota uzunlugu: {len(sonuc['koordinatlar'])} nokta")

        print("\n--- Farkli saatlerde ayni rota ---")
        for s in [6, 8, 12, 17, 22]:
            r = rota_hesapla(40.9800, 28.8720, 40.9720, 28.8370, "hafta_ici", s)
            if r:
                print(f"  Saat {s:02d}:00 -> {r['sure_dk']} dk")
