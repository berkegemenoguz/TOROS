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
    loc = veri["results"][0]["geometry"]["location"]
    if not istanbul_ici_mi(loc["lat"], loc["lng"]):
        return None
    return {"lat": loc["lat"], "lon": loc["lng"], "adres": veri["results"][0]["formatted_address"]}


def teslimat_kaydet(v, session):
    lat = v.get("lat")
    lon = v.get("lon")
    adres = v.get("adres", "")

    if not lat or not lon:
        if not adres:
            return None, "Adres veya koordinat gerekli"
        geo = adres_geocode(adres)
        if not geo:
            return None, "Adres bulunamadi veya Istanbul disinda"
        lat, lon, adres = geo["lat"], geo["lon"], geo["adres"]

    result = session.execute(text(
        "INSERT INTO teslimatlar (adi, adres, lat, lon, agirlik, hacim, termin_tarihi, randevu_bas, randevu_son) "
        "VALUES (:adi, :adres, :lat, :lon, :ag, :hc, :termin, :rbas, :rson) RETURNING id"
    ), {
        "adi": v["adi"], "adres": adres,
        "lat": lat, "lon": lon,
        "ag": v.get("agirlik", 0), "hc": v.get("hacim", 0),
        "termin": v.get("termin_tarihi") or None,
        "rbas": v.get("randevu_bas") or None,
        "rson": v.get("randevu_son") or None,
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

    tes_listesi = []
    for t in teslimatlar:
        aci = math.atan2(float(t.lon) - depo_lon, float(t.lat) - depo_lat)
        tes_listesi.append({"id": t.id, "ag": float(t.agirlik), "hc": float(t.hacim), "aci": aci})
    tes_listesi.sort(key=lambda x: x["aci"])

    toplam_tes = len(tes_listesi)
    n_arac = len(araclar)
    esit_pay = toplam_tes // n_arac
    kalan = toplam_tes % n_arac
    arac_bilgi = []
    for i, a in enumerate(araclar):
        arac_bilgi.append({
            "id": a.id, "max_ag": float(a.max_agirlik), "max_hc": float(a.max_hacim),
            "kalan_ag": float(a.max_agirlik), "kalan_hc": float(a.max_hacim),
            "hedef_adet": esit_pay + (1 if i < kalan else 0),
            "teslimatlar": []
        })

    arac_idx = 0
    for t in tes_listesi:
        atandi = False
        for deneme in range(len(arac_bilgi)):
            a = arac_bilgi[(arac_idx + deneme) % len(arac_bilgi)]
            if t["ag"] <= a["kalan_ag"] and t["hc"] <= a["kalan_hc"]:
                a["teslimatlar"].append(t["id"])
                a["kalan_ag"] -= t["ag"]
                a["kalan_hc"] -= t["hc"]
                if len(a["teslimatlar"]) >= a["hedef_adet"]:
                    arac_idx = (arac_idx + deneme + 1) % len(arac_bilgi)
                atandi = True
                break
        if not atandi:
            for a in arac_bilgi:
                if t["ag"] <= a["kalan_ag"] and t["hc"] <= a["kalan_hc"]:
                    a["teslimatlar"].append(t["id"])
                    a["kalan_ag"] -= t["ag"]
                    a["kalan_hc"] -= t["hc"]
                    break

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
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=True, port=port)
