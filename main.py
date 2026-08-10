import pandas as pd
import re
import math

ukome = pd.read_csv("https://data.ibb.gov.tr/dataset/d155972f-916f-45fb-9f2b-f28539bf67b8/resource/c3dcec9d-9842-4441-8db4-4d6c55c6ac89/download/ukome_ana_arter_yol_parcalari.csv")

def extract_coords(linestring):
    return [(float(lon), float(lat)) for lon, lat in re.findall(r'([\d.]+)\s+([\d.]+)', str(linestring))]

road_coords = {}
for name_filter, label, type_filter in [
    ("D-100 Karayolu", "D100", None),
    ("^TEM$", "TEM", "Otoyol"),
]:
    roads = ukome[ukome["road_name"].str.contains(name_filter, case=False, na=False)]
    if type_filter:
        roads = roads[roads["road_type_desc"] == type_filter]
    coords = []
    for _, row in roads.iterrows():
        coords.extend(extract_coords(row["shape"]))
    road_coords[label] = coords

density = pd.read_csv("https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/57cb067b-1a0b-460b-8342-7884bd4537e8/download/traffic_density_202501.csv")

points = density[["LATITUDE", "LONGITUDE", "GEOHASH"]].drop_duplicates()

def min_distance_to_road(lat, lon, road_points):
    min_d = float("inf")
    for rlon, rlat in road_points:
        d = math.sqrt(((lat - rlat) * 111) ** 2 + ((lon - rlon) * 85) ** 2)
        if d < min_d:
            min_d = d
    return min_d

matched = {}
for label, rcoords in road_coords.items():
    matches = []
    for _, p in points.iterrows():
        d = min_distance_to_road(p["LATITUDE"], p["LONGITUDE"], rcoords)
        if d < 0.5:
            matches.append(p["GEOHASH"])
    matched[label] = set(matches)

day = density[density["DATE_TIME"].str.startswith("2025-01-06")].copy()
day["DATE_TIME"] = pd.to_datetime(day["DATE_TIME"])
day["Saat"] = day["DATE_TIME"].dt.hour

frames = []
for label, geohashes in matched.items():
    road_data = day[day["GEOHASH"].isin(geohashes)]
    hourly = road_data.groupby("Saat").agg(
        Ort_Hiz=("AVERAGE_SPEED", "mean"),
        Min_Hiz=("MINIMUM_SPEED", "mean"),
        Max_Hiz=("MAXIMUM_SPEED", "mean"),
        Toplam_Arac=("NUMBER_OF_VEHICLES", "sum"),
        Nokta=("GEOHASH", "nunique"),
    ).reset_index()
    hourly["Ort_Hiz"] = hourly["Ort_Hiz"].round(1)
    hourly["Min_Hiz"] = hourly["Min_Hiz"].round(1)
    hourly["Max_Hiz"] = hourly["Max_Hiz"].round(1)
    hourly["Yol"] = label
    frames.append(hourly)

combined = pd.concat(frames).sort_values(["Saat", "Yol"]).reset_index(drop=True)
print(combined.to_string(index=False))

combined[combined["Yol"] == "D100"].drop(columns="Yol").to_csv("d100_traffic.csv", index=False)
combined[combined["Yol"] == "TEM"].drop(columns="Yol").to_csv("tem_traffic.csv", index=False)
print("\nVeri 'd100_traffic.csv' ve 'tem_traffic.csv' dosyalarına aktarıldı.")
