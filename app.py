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


@app.route("/api/teslimatlar", methods=["POST"])
def teslimat_olustur():
    v = request.json
    session = Session()
    result = session.execute(text(
        "INSERT INTO teslimatlar (adi, adres, lat, lon, agirlik, hacim, termin_tarihi, randevu_bas, randevu_son) "
        "VALUES (:adi, :adres, :lat, :lon, :ag, :hc, :termin, :rbas, :rson) RETURNING id"
    ), {
        "adi": v["adi"], "adres": v["adres"],
        "lat": v.get("lat"), "lon": v.get("lon"),
        "ag": v.get("agirlik", 0), "hc": v.get("hacim", 0),
        "termin": v.get("termin_tarihi") or None,
        "rbas": v.get("randevu_bas") or None,
        "rson": v.get("randevu_son") or None,
    })
    session.commit()
    yeni_id = result.fetchone().id
    session.close()
    return jsonify({"id": yeni_id})


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
