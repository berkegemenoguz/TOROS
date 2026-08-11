import requests
import os
import polyline
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GOOGLE_DIRECTIONS_API_KEY")
DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


def teslimat_optimize(depo, teslimatlar, kalkis_zamani, depoya_don=True):
    waypoints = "|".join(f"{t[0]},{t[1]}" for t in teslimatlar)
    waypoints = f"optimize:true|{waypoints}"

    params = {
        "origin": f"{depo[0]},{depo[1]}",
        "destination": f"{depo[0]},{depo[1]}" if depoya_don else f"{teslimatlar[-1][0]},{teslimatlar[-1][1]}",
        "waypoints": waypoints,
        "departure_time": int(kalkis_zamani.timestamp()),
        "traffic_model": "best_guess",
        "key": API_KEY,
    }

    resp = requests.get(DIRECTIONS_URL, params=params)
    veri = resp.json()

    if veri["status"] != "OK":
        print(f"Hata: {veri['status']}")
        if "error_message" in veri:
            print(f"Detay: {veri['error_message']}")
        return None

    rota = veri["routes"][0]
    optimal_sira = rota["waypoint_order"]

    bacaklar = []
    toplam_mesafe = 0
    toplam_sure = 0
    toplam_trafik = 0

    for i, bacak in enumerate(rota["legs"]):
        toplam_mesafe += bacak["distance"]["value"]
        toplam_sure += bacak["duration"]["value"]
        trafik_sn = bacak.get("duration_in_traffic", bacak["duration"])["value"]
        toplam_trafik += trafik_sn

        bacaklar.append({
            "sira": i,
            "baslangic": bacak["start_address"],
            "hedef": bacak["end_address"],
            "mesafe": bacak["distance"]["text"],
            "mesafe_m": bacak["distance"]["value"],
            "sure": bacak["duration"]["text"],
            "sure_sn": bacak["duration"]["value"],
            "trafik_sure": bacak.get("duration_in_traffic", bacak["duration"])["text"],
            "trafik_sure_sn": trafik_sn,
        })

    sonuc = {
        "optimal_sira": optimal_sira,
        "bacaklar": bacaklar,
        "toplam_mesafe_m": toplam_mesafe,
        "toplam_mesafe": f"{toplam_mesafe / 1000:.1f} km",
        "toplam_sure_sn": toplam_sure,
        "toplam_sure": f"{toplam_sure // 60} dk",
        "toplam_trafik_sn": toplam_trafik,
        "toplam_trafik": f"{toplam_trafik // 60} dk",
        "polyline": rota["overview_polyline"]["points"],
        "teslimat_sayisi": len(teslimatlar),
    }

    return sonuc


def sonuc_yazdir(sonuc, teslimat_isimleri=None):
    if sonuc is None:
        return

    print(f"\n{'='*50}")
    print(f"  TOROS - Coklu Teslimat Optimizasyonu")
    print(f"{'='*50}")
    print(f"  Teslimat sayisi: {sonuc['teslimat_sayisi']}")
    print(f"  Toplam mesafe: {sonuc['toplam_mesafe']}")
    print(f"  Toplam sure (normal): {sonuc['toplam_sure']}")
    print(f"  Toplam sure (trafik): {sonuc['toplam_trafik']}")
    print(f"\n  Optimal siralama: {sonuc['optimal_sira']}")

    if teslimat_isimleri:
        print(f"\n  Rota sirasi:")
        print(f"    0. Depo (baslangic)")
        for i, idx in enumerate(sonuc["optimal_sira"]):
            print(f"    {i+1}. {teslimat_isimleri[idx]}")
        print(f"    {len(sonuc['optimal_sira'])+1}. Depo (donus)")

    print(f"\n  Bacak detaylari:")
    for b in sonuc["bacaklar"]:
        print(f"    {b['sira']+1}. {b['mesafe']:>8s} | {b['trafik_sure']:>8s} | {b['hedef'][:50]}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    # Test: Depo Bakirkoy, 5 teslimat noktasi
    depo = (40.9800, 28.8720)  # Bakirkoy Meydani

    teslimatlar = [
        (41.0020, 28.7730),   # Kucukcekmece
        (40.9985, 28.8590),   # Bahcelievler
        (40.9870, 28.8400),   # Yesilkoy
        (40.9750, 28.8500),   # Atakoy
        (41.0100, 28.8300),   # Basaksehir yolu
    ]

    isimler = [
        "Kucukcekmece Merkez",
        "Bahcelievler Merkez",
        "Yesilkoy",
        "Atakoy",
        "Basaksehir Yolu",
    ]

    sonuc = teslimat_optimize(
        depo=depo,
        teslimatlar=teslimatlar,
        kalkis_zamani=datetime(2026, 8, 11, 15, 0),
    )

    sonuc_yazdir(sonuc, isimler)
