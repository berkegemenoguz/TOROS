import requests
import os
import polyline
from datetime import datetime, timedelta
from itertools import permutations
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GOOGLE_DIRECTIONS_API_KEY")
MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
TESLIMAT_SURESI = 900  # 15 dakika (saniye)


def sure_matrisi_al(noktalar, kalkis_zamani):
    n = len(noktalar)
    matris = [[0] * n for _ in range(n)]
    koordinatlar = [f"{p[0]},{p[1]}" for p in noktalar]

    BATCH = 10
    istek_sayisi = 0

    for orig_bas in range(0, n, BATCH):
        orig_bitis = min(orig_bas + BATCH, n)
        origins = "|".join(koordinatlar[orig_bas:orig_bitis])

        for dest_bas in range(0, n, BATCH):
            dest_bitis = min(dest_bas + BATCH, n)
            destinations = "|".join(koordinatlar[dest_bas:dest_bitis])

            params = {
                "origins": origins,
                "destinations": destinations,
                "departure_time": int(kalkis_zamani.timestamp()),
                "traffic_model": "best_guess",
                "key": API_KEY,
            }

            resp = requests.get(MATRIX_URL, params=params)
            veri = resp.json()
            istek_sayisi += 1

            if veri["status"] != "OK":
                print(f"Matrix hatasi: {veri['status']}")
                if "error_message" in veri:
                    print(f"Detay: {veri['error_message']}")
                return None

            for i, satir in enumerate(veri["rows"]):
                for j, hucre in enumerate(satir["elements"]):
                    if hucre["status"] == "OK":
                        matris[orig_bas + i][dest_bas + j] = hucre.get(
                            "duration_in_traffic", hucre["duration"]
                        )["value"]
                    else:
                        matris[orig_bas + i][dest_bas + j] = float("inf")

    print(f"  {istek_sayisi} matrix istegi kullanildi")
    return matris


def budamali_arama(matris, n, pencereler, kalkis_zamani, depoya_don=True):
    en_iyi_sure = float("inf")
    en_iyi_sira = None

    def hizli_rota(kalanlar, son_nokta):
        if not kalanlar:
            return matris[son_nokta][0] if depoya_don else 0
        en_yakin = min(matris[son_nokta][k] for k in kalanlar)
        return en_yakin + TESLIMAT_SURESI

    def ara(sira, son_nokta, gecen_sure, kalanlar):
        nonlocal en_iyi_sure, en_iyi_sira

        if not kalanlar:
            donus = gecen_sure + (matris[son_nokta][0] if depoya_don else 0)
            if donus < en_iyi_sure:
                en_iyi_sure = donus
                en_iyi_sira = list(sira)
            return

        for sonraki in kalanlar:
            yol_suresi = matris[son_nokta][sonraki]
            varis_suresi = gecen_sure + yol_suresi
            varis_zamani = kalkis_zamani + timedelta(seconds=varis_suresi)

            teslimat_idx = sonraki - 1
            if teslimat_idx in pencereler:
                bas, son = pencereler[teslimat_idx]
                if varis_zamani > son:
                    continue
                if varis_zamani < bas:
                    bekleme = (bas - varis_zamani).total_seconds()
                    varis_suresi += bekleme

            varis_suresi += TESLIMAT_SURESI

            alt_sinir = varis_suresi + hizli_rota(kalanlar - {sonraki}, sonraki)
            if alt_sinir >= en_iyi_sure:
                continue

            sira.append(sonraki)
            ara(sira, sonraki, varis_suresi, kalanlar - {sonraki})
            sira.pop()

    teslimat_idxler = set(range(1, n))

    sira = []
    kalanlar = set(teslimat_idxler)
    son = 0
    sure = 0
    gecerli = True
    while kalanlar:
        en_yakin = min(kalanlar, key=lambda k: matris[son][k])
        yol = matris[son][en_yakin]
        sure += yol
        varis = kalkis_zamani + timedelta(seconds=sure)

        tidx = en_yakin - 1
        if tidx in pencereler:
            bas, son_zaman = pencereler[tidx]
            if varis > son_zaman:
                gecerli = False
                break
            if varis < bas:
                sure += (bas - varis).total_seconds()

        sure += TESLIMAT_SURESI
        sira.append(en_yakin)
        kalanlar.remove(en_yakin)
        son = en_yakin

    if gecerli:
        if depoya_don:
            sure += matris[son][0]
        en_iyi_sure = sure
        en_iyi_sira = list(sira)

    ara([], 0, 0, teslimat_idxler)

    if en_iyi_sira is None:
        return None, float("inf")

    gercek_sira = [i - 1 for i in en_iyi_sira]
    return gercek_sira, en_iyi_sure


def en_yakin_komsu(matris, n, pencereler, kalkis_zamani, depoya_don=True):
    sira = []
    kalanlar = set(range(1, n))
    son = 0
    sure = 0

    while kalanlar:
        en_yakin = min(kalanlar, key=lambda k: matris[son][k])
        yol = matris[son][en_yakin]
        sure += yol
        varis = kalkis_zamani + timedelta(seconds=sure)

        tidx = en_yakin - 1
        if tidx in pencereler:
            bas, son_zaman = pencereler[tidx]
            if varis < bas:
                sure += (bas - varis).total_seconds()

        sure += TESLIMAT_SURESI
        sira.append(en_yakin)
        kalanlar.remove(en_yakin)
        son = en_yakin

    if depoya_don:
        sure += matris[son][0]
    return sira, sure


def pencere_gecerli_mi(sira, matris, pencereler, kalkis_zamani, depoya_don=True):
    sure = 0
    son = 0
    for nokta in sira:
        sure += matris[son][nokta]
        varis = kalkis_zamani + timedelta(seconds=sure)

        tidx = nokta - 1
        if tidx in pencereler:
            bas, son_zaman = pencereler[tidx]
            if varis > son_zaman:
                return False, float("inf")
            if varis < bas:
                sure += (bas - varis).total_seconds()
        sure += TESLIMAT_SURESI
        son = nokta

    if depoya_don:
        sure += matris[son][0]
    return True, sure


def iki_opt(matris, n, pencereler, kalkis_zamani, baslangic_sira, depoya_don=True):
    en_iyi = list(baslangic_sira)
    _, en_iyi_sure = pencere_gecerli_mi(en_iyi, matris, pencereler, kalkis_zamani, depoya_don)
    iyilesti = True

    while iyilesti:
        iyilesti = False
        for i in range(len(en_iyi) - 1):
            for j in range(i + 1, len(en_iyi)):
                yeni = list(en_iyi)
                yeni[i], yeni[j] = yeni[j], yeni[i]

                gecerli, sure = pencere_gecerli_mi(yeni, matris, pencereler, kalkis_zamani, depoya_don)
                if gecerli and sure < en_iyi_sure:
                    en_iyi = yeni
                    en_iyi_sure = sure
                    iyilesti = True

    return en_iyi, en_iyi_sure


def hibrit_arama(matris, n, pencereler, kalkis_zamani, depoya_don=True):
    baslangic_sira, _ = en_yakin_komsu(matris, n, pencereler, kalkis_zamani, depoya_don)
    optimal_sira, optimal_sure = iki_opt(matris, n, pencereler, kalkis_zamani, baslangic_sira, depoya_don)

    import random
    random.seed(42)
    for _ in range(20):
        rastgele = list(range(1, n))
        random.shuffle(rastgele)
        gecerli, _ = pencere_gecerli_mi(rastgele, matris, pencereler, kalkis_zamani, depoya_don)
        if gecerli:
            sira, sure = iki_opt(matris, n, pencereler, kalkis_zamani, rastgele, depoya_don)
            if sure < optimal_sure:
                optimal_sira = sira
                optimal_sure = sure

    gercek_sira = [i - 1 for i in optimal_sira]
    return gercek_sira, optimal_sure


def teslimat_optimize(depo, teslimatlar, kalkis_zamani, pencereler=None, depoya_don=True):
    if pencereler is None:
        pencereler = {}

    noktalar = [depo] + teslimatlar
    n = len(noktalar)

    print(f"Distance Matrix istegi gonderiliyor ({n} nokta)...")
    matris = sure_matrisi_al(noktalar, kalkis_zamani)
    if matris is None:
        return None

    if len(teslimatlar) <= 14:
        print(f"Budamali arama basliyor ({len(teslimatlar)} teslimat)...")
        optimal_sira, toplam_sn = budamali_arama(matris, n, pencereler, kalkis_zamani, depoya_don)
    else:
        print(f"Hibrit arama basliyor ({len(teslimatlar)} teslimat)...")
        optimal_sira, toplam_sn = hibrit_arama(matris, n, pencereler, kalkis_zamani, depoya_don)

    if optimal_sira is None:
        print("Zaman pencerelerine uyan bir siralama bulunamadi!")
        return None

    print(f"Optimal sira bulundu: {optimal_sira} ({toplam_sn / 60:.0f} dk)")

    siralanmis = [teslimatlar[i] for i in optimal_sira]

    MAX_WP = 25
    tum_bacaklar_raw = []
    tum_polylines = []
    bacak_polylines = []
    directions_istek = 0

    for parca_bas in range(0, len(siralanmis), MAX_WP):
        parca = siralanmis[parca_bas:parca_bas + MAX_WP]

        if parca_bas == 0:
            origin = f"{depo[0]},{depo[1]}"
        else:
            onceki = siralanmis[parca_bas - 1]
            origin = f"{onceki[0]},{onceki[1]}"

        son_parca = parca_bas + MAX_WP >= len(siralanmis)
        if son_parca and depoya_don:
            dest = f"{depo[0]},{depo[1]}"
        else:
            dest = f"{parca[-1][0]},{parca[-1][1]}"
            parca = parca[:-1]

        waypoints = "|".join(f"{t[0]},{t[1]}" for t in parca)

        params = {
            "origin": origin,
            "destination": dest,
            "waypoints": waypoints,
            "departure_time": int(kalkis_zamani.timestamp()),
            "traffic_model": "best_guess",
            "key": API_KEY,
        }

        print(f"Directions API parca {parca_bas // MAX_WP + 1} gonderiliyor...")
        resp = requests.get(DIRECTIONS_URL, params=params)
        veri = resp.json()
        directions_istek += 1

        if veri["status"] != "OK":
            print(f"Directions hatasi: {veri['status']}")
            return None

        rota = veri["routes"][0]
        tum_bacaklar_raw.extend(rota["legs"])
        tum_polylines.append(rota["overview_polyline"]["points"])
        for bacak in rota["legs"]:
            bacak_noktalar = []
            for adim in bacak["steps"]:
                bacak_noktalar.extend(polyline.decode(adim["polyline"]["points"]))
            bacak_polylines.append(bacak_noktalar)

    print(f"  {directions_istek} directions istegi kullanildi")

    bacaklar = []
    toplam_mesafe = 0
    toplam_sure = 0
    toplam_trafik = 0
    varis_zamanlari = []
    suan = kalkis_zamani

    for i, bacak in enumerate(tum_bacaklar_raw):
        toplam_mesafe += bacak["distance"]["value"]
        sure_sn = bacak["duration"]["value"]
        trafik_sn = bacak.get("duration_in_traffic", bacak["duration"])["value"]
        toplam_sure += sure_sn
        toplam_trafik += trafik_sn

        suan = suan + timedelta(seconds=trafik_sn)

        teslimat_idx = optimal_sira[i] if i < len(optimal_sira) else None
        if teslimat_idx is not None and teslimat_idx in pencereler:
            bas, son = pencereler[teslimat_idx]
            if suan < bas:
                bekleme = (bas - suan).total_seconds()
                toplam_trafik += int(bekleme)
                suan = bas

        varis_zamanlari.append(suan.strftime("%H:%M"))

        son_bacak_mi = (i == len(tum_bacaklar_raw) - 1 and depoya_don) or (i == len(tum_bacaklar_raw) - 1 and not depoya_don)
        depoya_donus_bacagi = depoya_don and i == len(tum_bacaklar_raw) - 1
        if not depoya_donus_bacagi:
            suan = suan + timedelta(seconds=TESLIMAT_SURESI)
            toplam_trafik += TESLIMAT_SURESI

        bacaklar.append({
            "sira": i,
            "baslangic": bacak["start_address"],
            "hedef": bacak["end_address"],
            "mesafe": bacak["distance"]["text"],
            "mesafe_m": bacak["distance"]["value"],
            "sure": bacak["duration"]["text"],
            "sure_sn": sure_sn,
            "trafik_sure": bacak.get("duration_in_traffic", bacak["duration"])["text"],
            "trafik_sure_sn": trafik_sn,
            "varis_zamani": varis_zamanlari[-1],
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
        "polyline": tum_polylines,
        "bacak_polylines": [[[p[0], p[1]] for p in bp] for bp in bacak_polylines],
        "teslimat_sayisi": len(teslimatlar),
        "varis_zamanlari": varis_zamanlari,
    }

    return sonuc


def sonuc_yazdir(sonuc, teslimat_isimleri=None):
    if sonuc is None:
        return

    print(f"\n{'='*60}")
    print(f"  TOROS - Coklu Teslimat Optimizasyonu")
    print(f"{'='*60}")
    print(f"  Teslimat sayisi: {sonuc['teslimat_sayisi']}")
    print(f"  Toplam mesafe: {sonuc['toplam_mesafe']}")
    print(f"  Toplam sure (normal): {sonuc['toplam_sure']}")
    print(f"  Toplam sure (trafik): {sonuc['toplam_trafik']}")
    print(f"\n  Optimal siralama: {sonuc['optimal_sira']}")

    print(f"\n  Rota sirasi:")
    print(f"    0. Depo (kalkis)")
    for i, idx in enumerate(sonuc["optimal_sira"]):
        isim = teslimat_isimleri[idx] if teslimat_isimleri else f"Teslimat {idx}"
        varis = sonuc["varis_zamanlari"][i]
        print(f"    {i+1}. {isim} (varis: {varis})")
    donus = sonuc["varis_zamanlari"][-1]
    print(f"    {len(sonuc['optimal_sira'])+1}. Depo (donus: {donus})")

    print(f"\n  Bacak detaylari:")
    for b in sonuc["bacaklar"]:
        print(f"    {b['sira']+1}. {b['mesafe']:>8s} | {b['trafik_sure']:>8s} | {b['varis_zamani']} | {b['hedef'][:40]}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    depo = (40.9800, 28.8720)

    teslimatlar = [
        (40.9985, 28.8590),
        (40.9870, 28.8400),
    ]

    isimler = [
        "Bahcelievler Kultur Sk",
        "Yesilkoy Ataturk Cd",
    ]

    sonuc = teslimat_optimize(
        depo=depo,
        teslimatlar=teslimatlar,
        kalkis_zamani=datetime(2026, 8, 12, 15, 0),
        pencereler={},
        depoya_don=True,
    )

    sonuc_yazdir(sonuc, isimler)
