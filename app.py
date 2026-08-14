import os
import requests
from flask import Flask, request, jsonify, send_file
from datetime import datetime
from dotenv import load_dotenv
from coklu_teslimat import teslimat_optimize

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()
API_KEY = os.getenv("GOOGLE_DIRECTIONS_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

app = Flask(__name__)

IST_LAT_MIN, IST_LAT_MAX = 40.80, 41.35
IST_LON_MIN, IST_LON_MAX = 28.50, 29.45


def istanbul_ici_mi(lat, lon):
    return IST_LAT_MIN <= lat <= IST_LAT_MAX and IST_LON_MIN <= lon <= IST_LON_MAX


@app.route("/")
def anasayfa():
    return send_file("templates/index.html")


@app.route("/filo")
def filo():
    return send_file("templates/filo.html")


@app.route("/geocode", methods=["POST"])
def geocode():
    adres = request.json.get("adres", "")
    resp = requests.get(GEOCODE_URL, params={
        "address": adres,
        "key": API_KEY,
        "region": "tr",
        "language": "tr",
    })
    veri = resp.json()

    if veri["status"] != "OK" or not veri["results"]:
        return jsonify({"hata": "Adres bulunamadi"}), 404

    sonuc = veri["results"][0]
    loc = sonuc["geometry"]["location"]

    if not istanbul_ici_mi(loc["lat"], loc["lng"]):
        return jsonify({"hata": "Adres Istanbul sinirlarinin disinda"}), 400

    return jsonify({
        "lat": loc["lat"],
        "lon": loc["lng"],
        "adres": sonuc["formatted_address"],
    })


@app.route("/api/araclar", methods=["GET"])
def arac_listele():
    session = Session()
    rows = session.execute(text("SELECT * FROM araclar WHERE aktif = TRUE ORDER BY id")).fetchall()
    session.close()
    return jsonify([{
        "id": r.id, "adi": r.adi, "tip": r.tip,
        "max_agirlik": float(r.max_agirlik), "max_hacim": float(r.max_hacim),
        "plaka": r.plaka
    } for r in rows])


@app.route("/api/araclar", methods=["POST"])
def arac_olustur():
    v = request.json
    session = Session()
    result = session.execute(text(
        "INSERT INTO araclar (adi, tip, max_agirlik, max_hacim, plaka) "
        "VALUES (:adi, :tip, :ag, :hc, :plaka) RETURNING id"
    ), {"adi": v["adi"], "tip": v["tip"], "ag": v["max_agirlik"], "hc": v["max_hacim"], "plaka": v.get("plaka", "")})
    session.commit()
    yeni_id = result.fetchone().id
    session.close()
    return jsonify({"id": yeni_id})


@app.route("/api/araclar/bulk", methods=["POST"])
def arac_bulk():
    liste = request.json
    if not isinstance(liste, list):
        return jsonify({"hata": "Liste bekleniyor"}), 400
    session = Session()
    sonuclar = []
    hatalar = []
    for i, v in enumerate(liste):
        plaka = v.get("plaka", "").strip()
        if not plaka:
            hatalar.append({"index": i, "adi": v.get("adi", ""), "hata": "Plaka zorunludur"})
            continue
        tip = v.get("tip", "kamyonet")
        if tip not in ("kamyon", "kamyonet", "ticari"):
            hatalar.append({"index": i, "adi": v.get("adi", ""), "hata": "Gecersiz tip"})
            continue
        result = session.execute(text(
            "INSERT INTO araclar (adi, tip, max_agirlik, max_hacim, plaka) "
            "VALUES (:adi, :tip, :ag, :hc, :plaka) RETURNING id"
        ), {"adi": v.get("adi", "Arac"), "tip": tip, "ag": v.get("max_agirlik", 0), "hc": v.get("max_hacim", 0), "plaka": plaka})
        sonuclar.append({"index": i, "id": result.fetchone().id})
    session.commit()
    session.close()
    return jsonify({"basarili": sonuclar, "hatalar": hatalar})


@app.route("/api/araclar/<int:arac_id>", methods=["DELETE"])
def arac_sil(arac_id):
    session = Session()
    session.execute(text("UPDATE teslimatlar SET arac_id = NULL, durum = 'beklemede', sira = NULL WHERE arac_id = :id"), {"id": arac_id})
    session.execute(text("UPDATE araclar SET aktif = FALSE WHERE id = :id"), {"id": arac_id})
    session.commit()
    session.close()
    return jsonify({"ok": True})


@app.route("/api/teslimatlar", methods=["GET"])
def teslimat_listele():
    session = Session()
    rows = session.execute(text(
        "SELECT * FROM teslimatlar ORDER BY arac_id NULLS FIRST, sira NULLS LAST, id"
    )).fetchall()
    session.close()
    return jsonify([{
        "id": r.id, "adi": r.adi, "adres": r.adres,
        "lat": float(r.lat) if r.lat else None,
        "lon": float(r.lon) if r.lon else None,
        "agirlik": float(r.agirlik), "hacim": float(r.hacim),
        "termin_tarihi": str(r.termin_tarihi) if r.termin_tarihi else "",
        "randevu_bas": str(r.randevu_bas)[:5] if r.randevu_bas else "",
        "randevu_son": str(r.randevu_son)[:5] if r.randevu_son else "",
        "arac_id": r.arac_id, "durum": r.durum, "sira": r.sira
    } for r in rows])


def adres_geocode(adres):
    resp = requests.get(GEOCODE_URL, params={
        "address": adres, "key": API_KEY, "region": "tr", "language": "tr",
    })
    veri = resp.json()
    if veri["status"] != "OK" or not veri["results"]:
        return None
    sonuc = veri["results"][0]
    loc = sonuc["geometry"]["location"]
    if not istanbul_ici_mi(loc["lat"], loc["lng"]):
        return None

    puan = {"ROOFTOP": 100, "RANGE_INTERPOLATED": 85, "GEOMETRIC_CENTER": 50, "APPROXIMATE": 25}.get(
        sonuc["geometry"].get("location_type", ""), 0)
    if sonuc.get("partial_match"):
        puan -= 15

    parcalar = {}
    tip_esleme = {
        "administrative_area_level_1": "il",
        "administrative_area_level_2": "ilce",
        "sublocality": "mahalle", "sublocality_level_1": "mahalle", "neighborhood": "mahalle",
        "route": "sokak",
        "street_number": "bina_no",
        "postal_code": "posta_kodu",
    }
    for comp in sonuc.get("address_components", []):
        for tip in comp["types"]:
            if tip in tip_esleme:
                parcalar[tip_esleme[tip]] = comp["long_name"]

    return {
        "lat": loc["lat"], "lon": loc["lng"],
        "formatted_address": sonuc["formatted_address"],
        "puan": puan,
        "il": parcalar.get("il"), "ilce": parcalar.get("ilce"),
        "mahalle": parcalar.get("mahalle"), "sokak": parcalar.get("sokak"),
        "bina_no": parcalar.get("bina_no"), "posta_kodu": parcalar.get("posta_kodu"),
    }


def teslimat_kaydet(v, session):
    lat = v.get("lat")
    lon = v.get("lon")
    adres = v.get("adres", "")
    kat = v.get("kat") or None
    daire = v.get("daire") or None

    if not lat or not lon:
        if not adres:
            return None, "Adres veya koordinat gerekli"
        geo = adres_geocode(adres)
        if not geo:
            return None, "Adres bulunamadi, daha spesifik sekilde girin"
        if geo["puan"] < 80:
            return None, "Adres bulunamadi, daha spesifik sekilde girin"
        lat, lon = geo["lat"], geo["lon"]
    else:
        geo = None

    adres_result = session.execute(text(
        "INSERT INTO adresler (il, ilce, mahalle, sokak, bina_no, kat, daire, posta_kodu, formatted_address, lat, lon, puan) "
        "VALUES (:il, :ilce, :mahalle, :sokak, :bina_no, :kat, :daire, :posta_kodu, :formatted, :lat, :lon, :puan) RETURNING id"
    ), {
        "il": geo["il"] if geo else None,
        "ilce": geo["ilce"] if geo else None,
        "mahalle": geo["mahalle"] if geo else None,
        "sokak": geo["sokak"] if geo else None,
        "bina_no": geo["bina_no"] if geo else None,
        "kat": kat, "daire": daire,
        "posta_kodu": geo["posta_kodu"] if geo else None,
        "formatted": geo["formatted_address"] if geo else adres,
        "lat": lat, "lon": lon,
        "puan": geo["puan"] if geo else 100,
    })
    adres_id = adres_result.fetchone().id

    result = session.execute(text(
        "INSERT INTO teslimatlar (adi, adres, lat, lon, agirlik, hacim, termin_tarihi, randevu_bas, randevu_son, adres_id) "
        "VALUES (:adi, :adres, :lat, :lon, :ag, :hc, :termin, :rbas, :rson, :adres_id) RETURNING id"
    ), {
        "adi": v["adi"], "adres": geo["formatted_address"] if geo else adres,
        "lat": lat, "lon": lon,
        "ag": v.get("agirlik", 0), "hc": v.get("hacim", 0),
        "termin": v.get("termin_tarihi") or None,
        "rbas": v.get("randevu_bas") or None,
        "rson": v.get("randevu_son") or None,
        "adres_id": adres_id,
    })
    return result.fetchone().id, None


@app.route("/api/teslimatlar", methods=["POST"])
def teslimat_olustur():
    v = request.json
    session = Session()
    yeni_id, hata = teslimat_kaydet(v, session)
    if hata:
        session.close()
        return jsonify({"hata": hata}), 400
    session.commit()
    session.close()
    return jsonify({"id": yeni_id})


@app.route("/api/teslimatlar/bulk", methods=["POST"])
def teslimat_bulk():
    liste = request.json
    if not isinstance(liste, list):
        return jsonify({"hata": "Liste bekleniyor"}), 400
    session = Session()
    sonuclar = []
    hatalar = []
    for i, v in enumerate(liste):
        yeni_id, hata = teslimat_kaydet(v, session)
        if hata:
            hatalar.append({"index": i, "adi": v.get("adi", ""), "hata": hata})
        else:
            sonuclar.append({"index": i, "id": yeni_id})
    session.commit()
    session.close()
    return jsonify({"basarili": sonuclar, "hatalar": hatalar})


@app.route("/api/teslimatlar/<int:tes_id>", methods=["PUT"])
def teslimat_guncelle(tes_id):
    v = request.json
    session = Session()

    if "arac_id" in v:
        durum = "atandi" if v["arac_id"] else "beklemede"
        # Elle tasinan teslimat optimize edilmis siranin disina cikar; hedef
        # aracin rotasinin sonuna eklenir, araçtan cikarilinca sira silinir.
        yeni_sira = None
        if v["arac_id"]:
            son = session.execute(text(
                "SELECT COALESCE(MAX(sira), 0) FROM teslimatlar WHERE arac_id = :aid"
            ), {"aid": v["arac_id"]}).scalar()
            yeni_sira = (son or 0) + 1
        session.execute(text(
            "UPDATE teslimatlar SET arac_id = :arac_id, durum = :durum, sira = :sira "
            "WHERE id = :id"
        ), {"arac_id": v["arac_id"], "durum": durum, "sira": yeni_sira, "id": tes_id})

    alanlar = {}
    if "adi" in v: alanlar["adi"] = v["adi"]
    if "adres" in v:
        geo = adres_geocode(v["adres"])
        if not geo or geo["puan"] < 80:
            session.close()
            return jsonify({"hata": "Adres bulunamadi, daha spesifik sekilde girin"}), 400
        alanlar["lat"] = geo["lat"]
        alanlar["lon"] = geo["lon"]
        alanlar["adres"] = geo["formatted_address"]
        adres_id_row = session.execute(text("SELECT adres_id FROM teslimatlar WHERE id = :id"), {"id": tes_id}).fetchone()
        if adres_id_row and adres_id_row.adres_id:
            session.execute(text(
                "UPDATE adresler SET il=:il, ilce=:ilce, mahalle=:mahalle, sokak=:sokak, bina_no=:bina_no, "
                "posta_kodu=:posta_kodu, formatted_address=:formatted, lat=:lat, lon=:lon, puan=:puan WHERE id=:id"
            ), {
                "il": geo["il"], "ilce": geo["ilce"], "mahalle": geo["mahalle"],
                "sokak": geo["sokak"], "bina_no": geo["bina_no"], "posta_kodu": geo["posta_kodu"],
                "formatted": geo["formatted_address"], "lat": geo["lat"], "lon": geo["lon"],
                "puan": geo["puan"], "id": adres_id_row.adres_id,
            })
    if "kat" in v or "daire" in v:
        adres_id_row2 = session.execute(text("SELECT adres_id FROM teslimatlar WHERE id = :id"), {"id": tes_id}).fetchone()
        if adres_id_row2 and adres_id_row2.adres_id:
            kat_daire = {}
            if "kat" in v: kat_daire["kat"] = v["kat"]
            if "daire" in v: kat_daire["daire"] = v["daire"]
            set_kd = ", ".join(k + " = :" + k for k in kat_daire)
            kat_daire["id"] = adres_id_row2.adres_id
            session.execute(text("UPDATE adresler SET " + set_kd + " WHERE id = :id"), kat_daire)
    if "agirlik" in v: alanlar["agirlik"] = v["agirlik"]
    if "hacim" in v: alanlar["hacim"] = v["hacim"]
    if "termin_tarihi" in v: alanlar["termin_tarihi"] = v["termin_tarihi"] or None
    if "randevu_bas" in v: alanlar["randevu_bas"] = v["randevu_bas"] or None
    if "randevu_son" in v: alanlar["randevu_son"] = v["randevu_son"] or None
    if "durum" in v: alanlar["durum"] = v["durum"]

    if alanlar:
        set_kismi = ", ".join(k + " = :" + k for k in alanlar)
        alanlar["id"] = tes_id
        session.execute(text("UPDATE teslimatlar SET " + set_kismi + " WHERE id = :id"), alanlar)

    session.commit()
    session.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Dagitim parametreleri (Clarke-Wright tasarruf algoritmasi)
# Kat suresi sonucu en cok degistiren varsayimdir; sahadan gercek deger
# geldiginde once burasi guncellenmeli.
# ---------------------------------------------------------------------------
SERVIS_DK = 20.0       # teslimat + montaj taban suresi
KAT_DK = 2.0           # her kat icin ek sure
VARDIYA_DK = 540.0     # 9 saatlik vardiya
HIZ_KMH = 25.0         # Istanbul ici ortalama hiz
YOL_SAPMA = 1.35       # kus ucusu mesafe -> gercek yol carpani
KOPRU_KM = 12.0        # Bogaz gecisi cezasi
HEDEF_DOLULUK = (70.0, 82.0)   # filo boyutlandirma uyarisi icin bant

ANADOLU_ILCELERI = {
    "adalar", "atasehir", "beykoz", "cekmekoy", "kadikoy", "kartal", "maltepe",
    "pendik", "sancaktepe", "sultanbeyli", "sile", "tuzla", "umraniye", "uskudar",
}

_TR_TABLO = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")


def sadelestir(s):
    return (s or "").translate(_TR_TABLO).lower().strip()


@app.route("/api/dagit", methods=["POST"])
def otomatik_dagit():
    import math

    session = Session()
    araclar = session.execute(text(
        "SELECT id, adi, max_agirlik, max_hacim FROM araclar WHERE aktif = TRUE "
        "ORDER BY max_hacim, max_agirlik"
    )).fetchall()
    teslimatlar = session.execute(text("""
        SELECT t.id, t.agirlik, t.hacim, t.lat, t.lon, a.ilce, a.kat
        FROM teslimatlar t
        LEFT JOIN adresler a ON a.id = t.adres_id
        WHERE t.arac_id IS NULL AND t.lat IS NOT NULL AND t.lon IS NOT NULL
        ORDER BY t.id
    """)).fetchall()
    depo = session.execute(text("SELECT * FROM depolar ORDER BY id LIMIT 1")).fetchone()

    if not araclar:
        session.close()
        return jsonify({"hata": "Aktif araç bulunamadı"}), 400
    if not teslimatlar:
        session.close()
        return jsonify({"hata": "Atanmamış teslimat bulunamadı"}), 400

    depo_lat = float(depo.lat) if depo else 40.98
    depo_lon = float(depo.lon) if depo else 28.872
    depo_pt = (depo_lat, depo_lon)

    tesler = [{
        "id": t.id,
        "ag": float(t.agirlik or 0),
        "hc": float(t.hacim or 0),
        "pt": (float(t.lat), float(t.lon)),
        "yaka": "A" if sadelestir(t.ilce) in ANADOLU_ILCELERI else "E",
        "servis": SERVIS_DK + KAT_DK * int(t.kat or 0),
    } for t in teslimatlar]
    n = len(tesler)

    # Deponun yakasi adres kaydinda tutulmuyor; en yakin teslimatin yakasindan
    # cikariliyor. Depo teslimat bolgesinin icinde oldugu surece dogru sonuc verir.
    depo_yaka = min(tesler, key=lambda t: (t["pt"][0] - depo_lat) ** 2
                                          + (t["pt"][1] - depo_lon) ** 2)["yaka"]

    def kus_ucusu(a, b):
        yer_yaricapi = 6371.0
        p1, p2 = math.radians(a[0]), math.radians(b[0])
        dp, dl = p2 - p1, math.radians(b[1] - a[1])
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * yer_yaricapi * math.asin(math.sqrt(h)) * YOL_SAPMA

    def mesafe(a_yaka, a_pt, b_yaka, b_pt):
        return kus_ucusu(a_pt, b_pt) + (KOPRU_KM if a_yaka != b_yaka else 0.0)

    depo_mes = [mesafe(depo_yaka, depo_pt, t["yaka"], t["pt"]) for t in tesler]
    mes = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            mes[i][j] = mes[j][i] = mesafe(tesler[i]["yaka"], tesler[i]["pt"],
                                           tesler[j]["yaka"], tesler[j]["pt"])

    def rota_km(r):
        return depo_mes[r[0]] + depo_mes[r[-1]] + sum(mes[a][b] for a, b in zip(r, r[1:]))

    def rota_dk(r):
        return rota_km(r) / HIZ_KMH * 60.0 + sum(tesler[i]["servis"] for i in r)

    # --- Clarke-Wright tasarruf birlestirmesi -------------------------------
    # Kapasite ve vardiya SERT kisit: birlestirme kosuluna gomulu oldugu icin
    # algoritma ihlalli plan uretemez.
    max_ag = max(float(a.max_agirlik) for a in araclar)
    max_hc = max(float(a.max_hacim) for a in araclar)

    rotalar = [[i] for i in range(n)]
    nerede = {i: i for i in range(n)}
    yuk = [[tesler[i]["ag"], tesler[i]["hc"]] for i in range(n)]

    tasarruflar = sorted(
        ((depo_mes[i] + depo_mes[j] - mes[i][j], i, j)
         for i in range(n) for j in range(i + 1, n)), reverse=True)

    for tasarruf, i, j in tasarruflar:
        if tasarruf <= 0:
            break
        ri, rj = nerede[i], nerede[j]
        if ri == rj or rotalar[ri] is None or rotalar[rj] is None:
            continue
        rota_i, rota_j = rotalar[ri], rotalar[rj]
        if (yuk[ri][0] + yuk[rj][0] > max_ag) or (yuk[ri][1] + yuk[rj][1] > max_hc):
            continue
        # sadece rota uclari birlestirilebilir
        if rota_i[-1] == i and rota_j[0] == j:
            birlesik = rota_i + rota_j
        elif rota_i[0] == i and rota_j[-1] == j:
            birlesik = rota_j + rota_i
        elif rota_i[-1] == i and rota_j[-1] == j:
            birlesik = rota_i + rota_j[::-1]
        elif rota_i[0] == i and rota_j[0] == j:
            birlesik = rota_i[::-1] + rota_j
        else:
            continue
        if rota_dk(birlesik) > VARDIYA_DK:
            continue
        rotalar[ri], rotalar[rj] = birlesik, None
        yuk[ri][0] += yuk[rj][0]
        yuk[ri][1] += yuk[rj][1]
        for k in rota_j:
            nerede[k] = ri

    rotalar = [r for r in rotalar if r]

    # --- 2-opt: rota ici sira iyilestirmesi ---------------------------------
    def iki_opt(r):
        if len(r) < 4:
            return r
        gelisti = True
        while gelisti:
            gelisti = False
            for a in range(len(r) - 1):
                for b in range(a + 2, len(r)):
                    aday = r[:a + 1] + r[a + 1:b + 1][::-1] + r[b + 1:]
                    if rota_km(aday) < rota_km(r) - 1e-9:
                        r, gelisti = aday, True
        return r

    rotalar = [iki_opt(r) for r in rotalar]

    # --- Arac atamasi: rotayi sigdiran EN KUCUK arac (best-fit) -------------
    # Boylece buyuk araclar bos gitmez, doluluk orani yukselir.
    rotalar.sort(key=lambda r: -sum(tesler[i]["hc"] for i in r))
    bos_araclar = [{"id": a.id, "adi": a.adi, "mag": float(a.max_agirlik),
                    "mhc": float(a.max_hacim)} for a in araclar]

    atamalar, detaylar, acikta = {}, [], []
    for r in rotalar:
        ag = sum(tesler[i]["ag"] for i in r)
        hc = sum(tesler[i]["hc"] for i in r)
        uygun = [a for a in bos_araclar if a["mag"] >= ag and a["mhc"] >= hc]
        if not uygun:
            acikta.extend(tesler[i]["id"] for i in r)
            continue
        arac = min(uygun, key=lambda a: (a["mhc"], a["mag"]))
        bos_araclar.remove(arac)
        atamalar[arac["id"]] = [tesler[i]["id"] for i in r]
        detaylar.append({
            "arac_id": arac["id"], "arac_adi": arac["adi"],
            "teslimat_sayisi": len(r),
            "km": round(rota_km(r), 1),
            "sure_dk": round(rota_dk(r)),
            "agirlik": round(ag, 1), "max_agirlik": arac["mag"],
            "hacim": round(hc, 2), "max_hacim": arac["mhc"],
            "doluluk_agirlik": round(100 * ag / arac["mag"], 1),
            "doluluk_hacim": round(100 * hc / arac["mhc"], 1),
            "vardiya_yuzde": round(100 * rota_dk(r) / VARDIYA_DK),
        })

    # sira: rotadaki ziyaret sirasi (1'den baslar), 2-opt sonrasi kesinlesmis hali
    for arac_id, tes_idler in atamalar.items():
        for sira, tid in enumerate(tes_idler, 1):
            session.execute(text(
                "UPDATE teslimatlar SET arac_id = :arac_id, durum = 'atandi', sira = :sira "
                "WHERE id = :tid"
            ), {"arac_id": arac_id, "sira": sira, "tid": tid})
    if acikta:
        session.execute(text(
            "UPDATE teslimatlar SET sira = NULL WHERE id = ANY(:idler)"
        ), {"idler": acikta})
    session.commit()
    session.close()

    # --- Ozet ve filo boyutlandirma uyarilari -------------------------------
    kullanilan = len(detaylar)
    top_km = round(sum(d["km"] for d in detaylar), 1)
    top_ag = sum(d["agirlik"] for d in detaylar)
    top_hc = sum(d["hacim"] for d in detaylar)
    kap_ag = sum(d["max_agirlik"] for d in detaylar) or 1
    kap_hc = sum(d["max_hacim"] for d in detaylar) or 1
    dol_ag = round(100 * top_ag / kap_ag, 1)
    dol_hc = round(100 * top_hc / kap_hc, 1)
    doluluk = max(dol_ag, dol_hc)
    vardiya = round(100 * sum(d["sure_dk"] for d in detaylar)
                    / (kullanilan * VARDIYA_DK)) if kullanilan else 0

    uyarilar = []
    if acikta:
        uyarilar.append(
            f"{len(acikta)} teslimat açıkta kaldı — filo yetersiz, "
            f"en az {len(rotalar)} araç gerekiyor"
        )
    if kullanilan and doluluk < HEDEF_DOLULUK[0]:
        uyarilar.append(
            f"Doluluk %{doluluk:.0f} — araçlar boş gidiyor, "
            f"daha küçük araç değerlendirilebilir"
        )
    elif kullanilan and doluluk > HEDEF_DOLULUK[1]:
        uyarilar.append(f"Doluluk %{doluluk:.0f} — filo sınırda, pay bırakmıyor")
    if vardiya > 92:
        uyarilar.append(f"Vardiya kullanımı %{vardiya} — gecikmeye tolerans yok")
    if bos_araclar:
        uyarilar.append(f"{len(bos_araclar)} araç boş kaldı: "
                        + ", ".join(a["adi"] for a in bos_araclar))

    return jsonify({
        "atamalar": {str(k): v for k, v in atamalar.items()},
        "ozet": {
            "teslimat": n,
            "atanan": n - len(acikta),
            "acikta": len(acikta),
            "kullanilan_arac": kullanilan,
            "toplam_arac": len(araclar),
            "toplam_km": top_km,
            "doluluk_agirlik": dol_ag,
            "doluluk_hacim": dol_hc,
            "vardiya_yuzde": vardiya,
        },
        "rotalar": detaylar,
        "acikta_teslimatlar": acikta,
        "uyarilar": uyarilar,
    })


@app.route("/api/teslimatlar/<int:tes_id>/adres", methods=["GET"])
def teslimat_adres(tes_id):
    session = Session()
    row = session.execute(text(
        "SELECT a.* FROM adresler a JOIN teslimatlar t ON t.adres_id = a.id WHERE t.id = :id"
    ), {"id": tes_id}).fetchone()
    session.close()
    if not row:
        return jsonify({}), 200
    return jsonify({
        "il": row.il, "ilce": row.ilce, "mahalle": row.mahalle,
        "sokak": row.sokak, "bina_no": row.bina_no, "kat": row.kat, "daire": row.daire,
        "posta_kodu": row.posta_kodu, "formatted_address": row.formatted_address,
        "lat": float(row.lat) if row.lat else None, "lon": float(row.lon) if row.lon else None,
        "puan": row.puan,
    })


@app.route("/api/teslimatlar/<int:tes_id>", methods=["DELETE"])
def teslimat_sil_api(tes_id):
    session = Session()
    session.execute(text("DELETE FROM teslimatlar WHERE id = :id"), {"id": tes_id})
    session.commit()
    session.close()
    return jsonify({"ok": True})


@app.route("/api/adresler", methods=["GET"])
def adresler_listele():
    session = Session()
    rows = session.execute(text("SELECT * FROM adresler ORDER BY id")).fetchall()
    session.close()
    return jsonify([{
        "id": r.id, "il": r.il, "ilce": r.ilce, "mahalle": r.mahalle,
        "sokak": r.sokak, "bina_no": r.bina_no, "kat": r.kat, "daire": r.daire,
        "posta_kodu": r.posta_kodu, "formatted_address": r.formatted_address,
        "lat": float(r.lat) if r.lat else None, "lon": float(r.lon) if r.lon else None,
        "puan": r.puan,
    } for r in rows])


@app.route("/api/adresler/<int:adres_id>", methods=["GET"])
def adres_detay(adres_id):
    session = Session()
    r = session.execute(text("SELECT * FROM adresler WHERE id = :id"), {"id": adres_id}).fetchone()
    session.close()
    if not r:
        return jsonify({"hata": "Adres bulunamadi"}), 404
    return jsonify({
        "id": r.id, "il": r.il, "ilce": r.ilce, "mahalle": r.mahalle,
        "sokak": r.sokak, "bina_no": r.bina_no, "kat": r.kat, "daire": r.daire,
        "posta_kodu": r.posta_kodu, "formatted_address": r.formatted_address,
        "lat": float(r.lat) if r.lat else None, "lon": float(r.lon) if r.lon else None,
        "puan": r.puan,
    })


@app.route("/api/adresler/<int:adres_id>", methods=["PUT"])
def adres_guncelle(adres_id):
    v = request.json
    session = Session()
    mevcut = session.execute(text("SELECT * FROM adresler WHERE id = :id"), {"id": adres_id}).fetchone()
    if not mevcut:
        session.close()
        return jsonify({"hata": "Adres bulunamadi"}), 404
    alanlar = {}
    for alan in ["il", "ilce", "mahalle", "sokak", "bina_no", "kat", "daire", "posta_kodu"]:
        if alan in v:
            alanlar[alan] = v[alan]
    if alanlar:
        set_kismi = ", ".join(k + " = :" + k for k in alanlar)
        alanlar["id"] = adres_id
        session.execute(text("UPDATE adresler SET " + set_kismi + " WHERE id = :id"), alanlar)
    session.commit()
    session.close()
    return jsonify({"ok": True})


@app.route("/api/adresler/<int:adres_id>", methods=["DELETE"])
def adres_sil(adres_id):
    session = Session()
    session.execute(text("UPDATE teslimatlar SET adres_id = NULL WHERE adres_id = :id"), {"id": adres_id})
    session.execute(text("DELETE FROM adresler WHERE id = :id"), {"id": adres_id})
    session.commit()
    session.close()
    return jsonify({"ok": True})


@app.route("/optimize", methods=["POST"])
def optimize():
    veri = request.json
    print("Gelen veri:", veri)

    depo = (veri["depo"]["lat"], veri["depo"]["lon"])

    if not istanbul_ici_mi(depo[0], depo[1]):
        return jsonify({"hata": "Depo Istanbul sinirlarinin disinda"}), 400

    kalkis = datetime.fromisoformat(veri["kalkis_zamani"])
    if kalkis < datetime.now():
        kalkis = datetime.now() + __import__('datetime').timedelta(minutes=5)
    print(f"Depo: {depo}, Kalkis: {kalkis}")

    teslimatlar = []
    isimler = []
    pencereler = {}

    for i, t in enumerate(veri["teslimatlar"]):
        if not istanbul_ici_mi(t["lat"], t["lon"]):
            return jsonify({"hata": f"Teslimat {i+1} Istanbul sinirlarinin disinda"}), 400
        teslimatlar.append((t["lat"], t["lon"]))
        isimler.append(t.get("isim", f"Teslimat {i+1}"))

        if t.get("pencere_bas") and t.get("pencere_son"):
            pencereler[i] = (
                datetime.fromisoformat(t["pencere_bas"]),
                datetime.fromisoformat(t["pencere_son"]),
            )

    depoya_don = veri.get("depoya_don", True)

    sonuc = teslimat_optimize(
        depo=depo,
        teslimatlar=teslimatlar,
        kalkis_zamani=kalkis,
        pencereler=pencereler,
        depoya_don=depoya_don,
    )

    if sonuc is None:
        return jsonify({"hata": "Rota bulunamadi"}), 400

    siralanmis_isimler = [isimler[i] for i in sonuc["optimal_sira"]]

    return jsonify({
        "optimal_sira": sonuc["optimal_sira"],
        "isimler": siralanmis_isimler,
        "bacaklar": sonuc["bacaklar"],
        "toplam_mesafe": sonuc["toplam_mesafe"],
        "toplam_sure": sonuc["toplam_sure"],
        "toplam_trafik": sonuc["toplam_trafik"],
        "varis_zamanlari": sonuc["varis_zamanlari"],
        "polyline": sonuc["polyline"],
        "bacak_polylines": sonuc["bacak_polylines"],
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(debug=True, port=port)
