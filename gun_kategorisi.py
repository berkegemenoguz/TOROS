from hijri_converter import Hijri
from datetime import date, timedelta

RESMI_TATILLER = [
    (1, 1),    # Yilbasi
    (4, 23),   # Ulusal Egemenlik ve Cocuk Bayrami
    (5, 1),    # Emek ve Dayanisma Gunu
    (5, 19),   # Ataturk'u Anma, Genclik ve Spor Bayrami
    (7, 15),   # Demokrasi ve Milli Birlik Gunu
    (8, 30),   # Zafer Bayrami
    (10, 29),  # Cumhuriyet Bayrami
]


def bayram_blogu_tarihleri(yil):
    hicri_yil = Hijri(yil - 579, 10, 1)
    try:
        ramazan_start = Hijri(hicri_yil.year, 10, 1).to_gregorian()
    except:
        ramazan_start = Hijri(hicri_yil.year - 1, 10, 1).to_gregorian()

    if ramazan_start.year != yil:
        ramazan_start = Hijri(hicri_yil.year + 1, 10, 1).to_gregorian()

    try:
        kurban_start = Hijri(hicri_yil.year, 12, 10).to_gregorian()
    except:
        kurban_start = Hijri(hicri_yil.year - 1, 12, 10).to_gregorian()

    if kurban_start.year != yil:
        kurban_start = Hijri(hicri_yil.year + 1, 12, 10).to_gregorian()

    ramazan_days = {ramazan_start + timedelta(days=i) for i in range(3)}
    kurban_days = {kurban_start + timedelta(days=i) for i in range(4)}
    bayram_days = ramazan_days | kurban_days

    blok = set(bayram_days)
    for d in list(bayram_days):
        check = d - timedelta(days=1)
        while check.weekday() >= 5:
            blok.add(check)
            check -= timedelta(days=1)
        check = d + timedelta(days=1)
        while check.weekday() >= 5:
            blok.add(check)
            check += timedelta(days=1)

    return blok


def gun_kategorisi(tarih):
    yil = tarih.year
    blok = bayram_blogu_tarihleri(yil)

    if tarih in blok:
        return "bayram_blogu"

    if (tarih.month, tarih.day) in RESMI_TATILLER:
        return "resmi_tatil"

    if tarih.weekday() >= 5:
        return "hafta_sonu"

    return "hafta_ici"


if __name__ == "__main__":
    print("=== 2024 kategori dagilimi ===")
    sayac = {"hafta_ici": 0, "hafta_sonu": 0, "resmi_tatil": 0, "bayram_blogu": 0}
    d = date(2024, 1, 1)
    while d <= date(2024, 12, 31):
        kat = gun_kategorisi(d)
        sayac[kat] += 1
        if kat in ("resmi_tatil", "bayram_blogu"):
            gun_isimleri = ["Pzt", "Sal", "Car", "Per", "Cum", "Cmt", "Paz"]
            print(f"  {d} ({gun_isimleri[d.weekday()]}) -> {kat}")
        d += timedelta(days=1)

    print()
    for k, v in sayac.items():
        print(f"  {k}: {v} gun")
