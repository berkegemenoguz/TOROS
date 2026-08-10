import pandas as pd
from datetime import datetime
from gun_kategorisi import gun_kategorisi

BAKIRKOY_LAT = (40.96, 41.01)
BAKIRKOY_LON = (28.82, 28.91)

AYLIK_URLS = {
    1: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/7d9cbf11-f4b8-464d-bb3a-642b79e8b32b/download/traffic_density_202401.csv",
    2: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/601cd734-9a62-44e0-89e5-bbfc2161d389/download/traffic_density_202402.csv",
    3: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/b67e9415-0ba8-4319-8d36-359240a93808/download/traffic_density_202403.csv",
    4: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/0c7d60f3-8349-4836-a1c2-56ec93cbbd50/download/traffic_density_202404.csv",
    5: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/674604c8-8d08-42ff-a0b3-e2bde9f39455/download/traffic_density_202405.csv",
    6: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/674ba2c5-76b0-4f24-8e17-9aa2071d2572/download/traffic_density_202406.csv",
    7: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/0019216e-48e0-4cec-9ab8-93d67f66dac3/download/traffic_density_202407.csv",
    8: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/168467fe-0495-4cdf-a93a-7c1e91179457/download/traffic_density_202408.csv",
    9: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/914cb0b9-d941-4408-98eb-f378519c26f4/download/traffic_density_202409.csv",
    10: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/d291989c-429d-4e61-9c70-1f76294b96b8/download/traffic_density_202410.csv",
    11: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/bedd5ab2-9a00-4966-9921-9672d4478a51/download/traffic_density_202411.csv",
    12: "https://data.ibb.gov.tr/dataset/3ee6d744-5da2-40c8-9cd6-0e3e41f1928f/resource/76671ebe-2fd2-426f-b85a-e3772263f483/download/traffic_density_202412.csv",
}


def ay_isle(ay, url):
    print(f"  Ay {ay:02d} indiriliyor...")
    df = pd.read_csv(url)

    bakirkoy = df[
        (df["LATITUDE"] >= BAKIRKOY_LAT[0]) & (df["LATITUDE"] <= BAKIRKOY_LAT[1]) &
        (df["LONGITUDE"] >= BAKIRKOY_LON[0]) & (df["LONGITUDE"] <= BAKIRKOY_LON[1])
    ].copy()

    print(f"  Ay {ay:02d}: {len(bakirkoy)} Bakirkoy kaydi (toplam {len(df)})")

    bakirkoy["DATE_TIME"] = pd.to_datetime(bakirkoy["DATE_TIME"])
    bakirkoy["saat"] = bakirkoy["DATE_TIME"].dt.hour
    bakirkoy["tarih"] = bakirkoy["DATE_TIME"].dt.date
    bakirkoy["kategori"] = bakirkoy["tarih"].apply(gun_kategorisi)

    ozet = bakirkoy.groupby(["kategori", "saat", "GEOHASH", "LATITUDE", "LONGITUDE"]).agg(
        ort_hiz=("AVERAGE_SPEED", "mean"),
        min_hiz=("MINIMUM_SPEED", "mean"),
        max_hiz=("MAXIMUM_SPEED", "mean"),
        toplam_arac=("NUMBER_OF_VEHICLES", "sum"),
        gun_sayisi=("tarih", "nunique"),
    ).reset_index()

    ozet["ay"] = ay
    return ozet


if __name__ == "__main__":
    tum_ozetler = []

    for ay, url in AYLIK_URLS.items():
        ozet = ay_isle(ay, url)
        tum_ozetler.append(ozet)

    sonuc = pd.concat(tum_ozetler, ignore_index=True)
    sonuc.to_csv("data/bakirkoy_trafik_2024.csv", index=False)
    print(f"\nToplam {len(sonuc)} satir data/bakirkoy_trafik_2024.csv dosyasina kaydedildi.")
