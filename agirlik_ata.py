import pandas as pd
import numpy as np
import osmnx as ox
from math import radians, cos, sqrt

G = ox.graph_from_place("Bakırköy, Istanbul, Turkey", network_type="drive")
nodes, edges = ox.graph_to_gdfs(G)

trafik = pd.read_csv("data/bakirkoy_trafik_2024.csv")

geohash_noktalar = trafik[["GEOHASH", "LATITUDE", "LONGITUDE"]].drop_duplicates()
print(f"Yol agi: {len(edges)} edge, Trafik: {len(geohash_noktalar)} olcum noktasi")

ESIK_KM = 0.3

def haversine_hizli(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111.0
    dx = (lon2 - lon1) * 85.0
    return sqrt(dy * dy + dx * dx)


def edge_merkez(row):
    if row.geometry is not None:
        coords = list(row.geometry.coords)
        mid = coords[len(coords) // 2]
        return mid[1], mid[0]
    u_node = nodes.loc[row.name[0]]
    v_node = nodes.loc[row.name[1]]
    return (u_node["y"] + v_node["y"]) / 2, (u_node["x"] + v_node["x"]) / 2


print("Edge-geohash eslestirmesi yapiliyor...")
gh_lats = geohash_noktalar["LATITUDE"].values
gh_lons = geohash_noktalar["LONGITUDE"].values
gh_ids = geohash_noktalar["GEOHASH"].values

eslesmeler = []
eslesmeyen = []
for idx, row in edges.iterrows():
    lat, lon = edge_merkez(row)
    mesafeler = np.sqrt(((gh_lats - lat) * 111) ** 2 + ((gh_lons - lon) * 85) ** 2)
    yakin = np.where(mesafeler < ESIK_KM)[0]

    hw = row["highway"]
    if isinstance(hw, list):
        hw = hw[0]

    if len(yakin) > 0:
        en_yakin_idx = yakin[mesafeler[yakin].argmin()]
        eslesmeler.append({
            "u": idx[0],
            "v": idx[1],
            "key": idx[2],
            "geohash": gh_ids[en_yakin_idx],
            "mesafe_km": mesafeler[en_yakin_idx],
            "highway": hw,
            "name": row["name"],
            "length": row["length"],
        })
    else:
        eslesmeyen.append({
            "u": idx[0],
            "v": idx[1],
            "key": idx[2],
            "highway": hw,
            "name": row["name"],
            "length": row["length"],
        })

eslesme_df = pd.DataFrame(eslesmeler)
eslesmeyen_df = pd.DataFrame(eslesmeyen)
print(f"Eslesen edge: {len(eslesme_df)} / {len(edges)}")
print(f"Eslesmeyen edge (ara sokak): {len(eslesmeyen_df)}")

eslesme_df.to_csv("data/edge_geohash_eslesme.csv", index=False)
print("data/edge_geohash_eslesme.csv kaydedildi.")

HW_HIZ = {
    "motorway": 90, "trunk": 70, "primary": 50, "secondary": 40,
    "tertiary": 35, "residential": 25, "living_street": 15,
    "motorway_link": 60, "trunk_link": 50, "primary_link": 40,
    "secondary_link": 35, "tertiary_link": 30, "unclassified": 30,
    "service": 20,
}

agirliklar = []
for kategori in ["hafta_ici", "hafta_sonu", "resmi_tatil", "bayram_blogu"]:
    for saat in range(24):
        saat_veri = trafik[(trafik["kategori"] == kategori) & (trafik["saat"] == saat)]
        gh_hiz = saat_veri.groupby("GEOHASH")["ort_hiz"].mean().to_dict()

        for _, row in eslesme_df.iterrows():
            hiz = gh_hiz.get(row["geohash"])
            if hiz is None or hiz < 1:
                hiz = HW_HIZ.get(row["highway"], 30)

            sure_dk = (row["length"] / 1000) / hiz * 60
            agirliklar.append({
                "u": row["u"],
                "v": row["v"],
                "key": row["key"],
                "kategori": kategori,
                "saat": saat,
                "hiz_kmh": round(hiz, 1),
                "sure_dk": round(sure_dk, 3),
            })

        for _, row in eslesmeyen_df.iterrows():
            hiz = HW_HIZ.get(row["highway"], 30)
            sure_dk = (row["length"] / 1000) / hiz * 60
            agirliklar.append({
                "u": row["u"],
                "v": row["v"],
                "key": row["key"],
                "kategori": kategori,
                "saat": saat,
                "hiz_kmh": round(hiz, 1),
                "sure_dk": round(sure_dk, 3),
            })

agirlik_df = pd.DataFrame(agirliklar)
agirlik_df.to_csv("data/edge_agirliklar.csv", index=False)
print(f"\n{len(agirlik_df)} satir data/edge_agirliklar.csv kaydedildi.")
print("Kategoriler:", agirlik_df["kategori"].unique())
print("Saat araligi:", agirlik_df["saat"].min(), "-", agirlik_df["saat"].max())
