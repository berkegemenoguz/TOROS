import requests
import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GOOGLE_DIRECTIONS_API_KEY")
DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


def rota_hesapla(baslangic, hedef, kalkis_zamani):
    params = {
        "origin": f"{baslangic[0]},{baslangic[1]}",
        "destination": f"{hedef[0]},{hedef[1]}",
        "departure_time": int(kalkis_zamani.timestamp()),
        "traffic_model": "best_guess",
        "key": API_KEY,
    }

    resp = requests.get(DIRECTIONS_URL, params=params)
    veri = resp.json()

    if veri["status"] != "OK":
        print(f"Hata: {veri['status']}")
        return None

    rota = veri["routes"][0]
    bacak = rota["legs"][0]

    sonuc = {
        "ozet": rota["summary"],
        "mesafe": bacak["distance"]["text"],
        "normal_sure": bacak["duration"]["text"],
        "trafik_sure": bacak["duration_in_traffic"]["text"],
        "normal_sure_sn": bacak["duration"]["value"],
        "trafik_sure_sn": bacak["duration_in_traffic"]["value"],
        "baslangic_adres": bacak["start_address"],
        "hedef_adres": bacak["end_address"],
        "polyline": rota["overview_polyline"]["points"],
        "adimlar": [],
    }

    for adim in bacak["steps"]:
        sonuc["adimlar"].append({
            "mesafe": adim["distance"]["text"],
            "sure": adim["duration"]["text"],
            "talimat": adim["html_instructions"],
            "polyline": adim["polyline"]["points"],
        })

    return sonuc


if __name__ == "__main__":
    # Test: Bakirkoy Meydani -> Kucukcekmece Meydan
    kalkis = datetime(2026, 8, 11, 15, 0)  # Yarin saat 15:00

    sonuc = rota_hesapla(
        baslangic=(40.9800, 28.8720),
        hedef=(41.0020, 28.7730),
        kalkis_zamani=kalkis,
    )

    if sonuc:
        print(f"Rota: {sonuc['ozet']}")
        print(f"Mesafe: {sonuc['mesafe']}")
        print(f"Normal sure: {sonuc['normal_sure']}")
        print(f"Trafikli sure: {sonuc['trafik_sure']}")
        print(f"Baslangic: {sonuc['baslangic_adres']}")
        print(f"Hedef: {sonuc['hedef_adres']}")
