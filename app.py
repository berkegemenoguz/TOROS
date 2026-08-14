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
    session.execute(text("UPDATE teslimatlar SET arac_id = NULL, durum = 'beklemede' WHERE arac_id = :id"), {"id": arac_id})
    session.execute(text("UPDATE araclar SET aktif = FALSE WHERE id = :id"), {"id": arac_id})
    session.commit()
    session.close()
    return jsonify({"ok": True})


@app.route("/api/teslimatlar", methods=["GET"])
def teslimat_listele():
    session = Session()
    rows = session.execute(text("SELECT * FROM teslimatlar ORDER BY id")).fetchall()
    session.close()
    return jsonify([{
        "id": r.id, "adi": r.adi, "adres": r.adres,
        "lat": float(r.lat) if r.lat else None,
        "lon": float(r.lon) if r.lon else None,
        "agirlik": float(r.agirlik), "hacim": float(r.hacim),
        "termin_tarihi": str(r.termin_tarihi) if r.termin_tarihi else "",
        "randevu_bas": str(r.randevu_bas)[:5] if r.randevu_bas else "",
        "randevu_son": str(r.randevu_son)[:5] if r.randevu_son else "",
        "arac_id": r.arac_id, "durum": r.durum
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
        session.execute(text(
            "UPDATE teslimatlar SET arac_id = :arac_id, durum = :durum WHERE id = :id"
        ), {"arac_id": v["arac_id"], "durum": durum, "id": tes_id})

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


@app.route("/api/dagit", methods=["POST"])
def otomatik_dagit():
    import math

    session = Session()
    araclar = session.execute(text("SELECT * FROM araclar WHERE aktif = TRUE ORDER BY max_agirlik DESC")).fetchall()
    teslimatlar = session.execute(text("SELECT * FROM teslimatlar WHERE arac_id IS NULL AND lat IS NOT NULL AND lon IS NOT NULL ORDER BY id")).fetchall()
    depo = session.execute(text("SELECT * FROM depolar ORDER BY id LIMIT 1")).fetchone()

    if not araclar:
        session.close()
        return jsonify({"hata": "Aktif arac bulunamadi"}), 400
    if not teslimatlar:
        session.close()
        return jsonify({"hata": "Atanmamis teslimat bulunamadi"}), 400

    depo_lat = float(depo.lat) if depo else 40.98
    depo_lon = float(depo.lon) if depo else 28.872

    def aci_farki(a, b):
        d = abs(a - b) % (2 * math.pi)
        return min(d, 2 * math.pi - d)

    yakin_liste = []
    tes_listesi = []
    for t in teslimatlar:
        lat, lon = float(t.lat), float(t.lon)
        kayit = {"id": t.id, "ag": float(t.agirlik), "hc": float(t.hacim),
                 "aci": math.atan2(lon - depo_lon, lat - depo_lat)}
        mesafe_km = math.hypot((lat - depo_lat) * 111.0, (lon - depo_lon) * 84.0)
        if mesafe_km <= 2.0:
            yakin_liste.append(kayit)
        else:
            tes_listesi.append(kayit)
    tes_listesi.sort(key=lambda x: x["aci"])

    n_arac = len(araclar)
    n_tes = len(tes_listesi)

    kumeler = []
    if n_tes > 0:
        bosluklar = []
        for i in range(n_tes):
            sonraki = (i + 1) % n_tes
            fark = tes_listesi[sonraki]["aci"] - tes_listesi[i]["aci"]
            if sonraki == 0:
                fark += 2 * math.pi
            bosluklar.append(fark)
        baslangic = (bosluklar.index(max(bosluklar)) + 1) % n_tes
        sirali = tes_listesi[baslangic:] + tes_listesi[:baslangic]

        esik = math.radians(15)
        kumeler = [[sirali[0]]]
        for i in range(1, n_tes):
            fark = sirali[i]["aci"] - sirali[i - 1]["aci"]
            if fark < 0:
                fark += 2 * math.pi
            if fark > esik and len(kumeler) < n_arac:
                kumeler.append([])
            kumeler[-1].append(sirali[i])

        # 2 ve alti teslimatli kumeler ayri arac acmaz, acisal en yakin kumeye katilir
        birlesti = True
        while birlesti and len(kumeler) > 1:
            birlesti = False
            for i in range(len(kumeler)):
                if len(kumeler[i]) <= 2:
                    ort = sum(t["aci"] for t in kumeler[i]) / len(kumeler[i])
                    hedef = min((j for j in range(len(kumeler)) if j != i),
                                key=lambda j: aci_farki(sum(t["aci"] for t in kumeler[j]) / len(kumeler[j]), ort))
                    kumeler[hedef].extend(kumeler.pop(i))
                    birlesti = True
                    break

        # bos arac varsa buyuk kumeler bolunur; 4 ve alti teslimatli kume bolunmez
        while len(kumeler) < n_arac:
            en_buyuk = max(range(len(kumeler)), key=lambda i: len(kumeler[i]))
            k = kumeler[en_buyuk]
            if len(k) <= 4:
                break
            kumeler.pop(en_buyuk)
            m = len(k)
            orta = m // 2
            pencere = max(1, int(m * 0.3))
            en_iyi, en_iyi_fark = orta, -1.0
            for i in range(max(1, orta - pencere), min(m - 1, orta + pencere) + 1):
                fark = k[i]["aci"] - k[i - 1]["aci"]
                if fark > en_iyi_fark:
                    en_iyi_fark = fark
                    en_iyi = i
            kumeler.insert(en_buyuk, k[:en_iyi])
            kumeler.insert(en_buyuk + 1, k[en_iyi:])

    kumeler.sort(key=lambda k: -sum(t["ag"] for t in k))
    arac_bilgi = []
    for i, a in enumerate(araclar):
        seg = kumeler[i] if i < len(kumeler) else []
        arac_bilgi.append({
            "id": a.id, "max_ag": float(a.max_agirlik), "max_hc": float(a.max_hacim),
            "ort_aci": (sum(t["aci"] for t in seg) / len(seg)) if seg else None,
            "teslimatlar": [t["id"] for t in seg],
        })

    # depoya 2 km'den yakin teslimatlar ekstra sefer acmaz, mevcut rotalardan uygun olana eklenir
    if yakin_liste:
        dolu = [a for a in arac_bilgi if a["teslimatlar"]]
        if not dolu:
            arac_bilgi[0]["teslimatlar"] = [t["id"] for t in yakin_liste]
        else:
            for t in yakin_liste:
                hedef = min(dolu, key=lambda a: aci_farki(a["ort_aci"], t["aci"]))
                hedef["teslimatlar"].append(t["id"])

    atamalar = {}
    for a in arac_bilgi:
        atamalar[a["id"]] = a["teslimatlar"]
        for tid in a["teslimatlar"]:
            session.execute(text(
                "UPDATE teslimatlar SET arac_id = :arac_id, durum = 'atandi' WHERE id = :tid"
            ), {"arac_id": a["id"], "tid": tid})

    session.commit()
    session.close()

    sonuc = {str(k): v for k, v in atamalar.items()}
    return jsonify({"atamalar": sonuc})


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
