import os
import io
import requests
import segno
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


@app.route("/sofor")
def sofor():
    return send_file("templates/sofor.html")


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
    rows = session.execute(text(
        "SELECT a.*, s.ad AS sofor_ad FROM araclar a "
        "LEFT JOIN soforler s ON s.id = a.sofor_id "
        "WHERE a.aktif = TRUE ORDER BY a.id"
    )).fetchall()
    session.close()
    return jsonify([{
        "id": r.id, "adi": r.adi, "tip": r.tip,
        "max_agirlik": float(r.max_agirlik), "max_hacim": float(r.max_hacim),
        "plaka": r.plaka,
        "rota_km": float(r.son_rota_km) if r.son_rota_km is not None else None,
        "rota_dk": r.son_rota_dk,
        "sofor_id": r.sofor_id, "sofor_ad": r.sofor_ad or "",
        "bolge": r.bolge or ""
    } for r in rows])


@app.route("/api/araclar/<int:arac_id>/sofor", methods=["PUT"])
def arac_sofor_ata(arac_id):
    # sofor_id null gonderilirse atama kaldirilir
    sofor_id = (request.json or {}).get("sofor_id")
    session = Session()
    session.execute(text("UPDATE araclar SET sofor_id = :sid WHERE id = :aid"),
                    {"sid": sofor_id, "aid": arac_id})
    session.commit()
    ad = session.execute(text("SELECT ad FROM soforler WHERE id = :sid"),
                         {"sid": sofor_id}).scalar() if sofor_id else ""
    session.close()
    return jsonify({"ok": True, "sofor_ad": ad or ""})


@app.route("/api/araclar/<int:arac_id>/bolge", methods=["PUT"])
def arac_bolge_ata(arac_id):
    # bolge bos/null gonderilirse atama kaldirilir
    bolge = ((request.json or {}).get("bolge") or "").strip() or None
    session = Session()
    session.execute(text("UPDATE araclar SET bolge = :b WHERE id = :aid"),
                    {"b": bolge, "aid": arac_id})
    session.commit()
    session.close()
    return jsonify({"ok": True, "bolge": bolge or ""})


@app.route("/api/araclar", methods=["POST"])
def arac_olustur():
    v = request.json
    session = Session()
    result = session.execute(text(
        "INSERT INTO araclar (adi, tip, max_agirlik, max_hacim, plaka, bolge) "
        "VALUES (:adi, :tip, :ag, :hc, :plaka, :bolge) RETURNING id"
    ), {"adi": v["adi"], "tip": v["tip"], "ag": v["max_agirlik"], "hc": v["max_hacim"],
        "plaka": v.get("plaka", ""), "bolge": (v.get("bolge") or "").strip() or None})
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
            "INSERT INTO araclar (adi, tip, max_agirlik, max_hacim, plaka, bolge) "
            "VALUES (:adi, :tip, :ag, :hc, :plaka, :bolge) RETURNING id"
        ), {"adi": v.get("adi", "Arac"), "tip": tip, "ag": v.get("max_agirlik", 0),
            "hc": v.get("max_hacim", 0), "plaka": plaka, "bolge": (v.get("bolge") or "").strip() or None})
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
        "SELECT t.*, a.ilce, a.mahalle, a.sokak, a.bina_no, a.kat, a.daire "
        "FROM teslimatlar t LEFT JOIN adresler a ON a.id = t.adres_id "
        "ORDER BY t.arac_id NULLS FIRST, t.sira NULLS LAST, t.id"
    )).fetchall()
    session.close()
    return jsonify([{
        "id": r.id, "adi": r.adi, "adres": r.adres, "ilce": r.ilce or "",
        "mahalle": r.mahalle or "", "sokak": r.sokak or "",
        "bina_no": r.bina_no or "", "kat": r.kat or "", "daire": r.daire or "",
        "lat": float(r.lat) if r.lat else None,
        "lon": float(r.lon) if r.lon else None,
        "agirlik": float(r.agirlik), "hacim": float(r.hacim),
        "termin_tarihi": str(r.termin_tarihi) if r.termin_tarihi else "",
        "randevu_bas": str(r.randevu_bas)[:5] if r.randevu_bas else "",
        "randevu_son": str(r.randevu_son)[:5] if r.randevu_son else "",
        "arac_id": r.arac_id, "durum": r.durum, "sira": r.sira,
        "bolge": bolge_bul(r.ilce) or ""
    } for r in rows])


@app.route("/api/bolgeler", methods=["GET"])
def bolge_listele():
    # Araclara bolge atarken arayuzun kullanacagi kanonik liste
    return jsonify(list(BOLGELER.keys()))


def bolge_havuzu(session):
    """Bekleyen (henuz araca atanmamis) teslimatlari bolgesine gore toplar ve
    her bolge icin doluluk / en eski yuk yasi / termin durumu / hazir-mi sonucunu
    hesaplar. SALT OKUNUR - hicbir sey yazmaz, sevkiyati degistirmez.

    Gun yasi teslimatin olusturma_zamani'ndan turetilir; sayac ARACA degil,
    bolgedeki EN ESKI YUKE baglidir (yeni teslimat sayaci sifirlamaz)."""
    bugun = datetime.now().date()

    # Bolge -> o bolgeye bakan aktif araclarin toplam kapasitesi (1 bolge = 1 arac
    # modeli, ama birden fazla olursa kapasiteler toplanir)
    arac_rows = session.execute(text(
        "SELECT id, adi, max_agirlik, max_hacim, bolge FROM araclar "
        "WHERE aktif = TRUE AND bolge IS NOT NULL"
    )).fetchall()
    bolge_arac = {}
    for a in arac_rows:
        b = bolge_arac.setdefault(a.bolge, {
            "arac_idler": [], "arac_adlari": [], "cap_ag": 0.0, "cap_hc": 0.0})
        b["arac_idler"].append(a.id)
        b["arac_adlari"].append(a.adi)
        b["cap_ag"] += float(a.max_agirlik)
        b["cap_hc"] += float(a.max_hacim)

    # Bekleyen teslimatlar (araca atanmamis, konumu belli)
    tesler = session.execute(text("""
        SELECT t.id, t.agirlik, t.hacim, t.termin_tarihi, t.olusturma_zamani, a.ilce
        FROM teslimatlar t
        LEFT JOIN adresler a ON a.id = t.adres_id
        WHERE t.arac_id IS NULL AND t.lat IS NOT NULL AND t.lon IS NOT NULL
    """)).fetchall()

    havuz = {}
    bolgesiz = {"teslimat_sayisi": 0, "agirlik": 0.0, "hacim": 0.0}
    for t in tesler:
        bolge = bolge_bul(t.ilce)
        if not bolge:
            bolgesiz["teslimat_sayisi"] += 1
            bolgesiz["agirlik"] += float(t.agirlik or 0)
            bolgesiz["hacim"] += float(t.hacim or 0)
            continue
        h = havuz.setdefault(bolge, {
            "teslimat_sayisi": 0, "agirlik": 0.0, "hacim": 0.0,
            "en_eski": None, "en_erken_termin": None})
        h["teslimat_sayisi"] += 1
        h["agirlik"] += float(t.agirlik or 0)
        h["hacim"] += float(t.hacim or 0)
        if t.olusturma_zamani and (h["en_eski"] is None or t.olusturma_zamani < h["en_eski"]):
            h["en_eski"] = t.olusturma_zamani
        if t.termin_tarihi and (h["en_erken_termin"] is None or t.termin_tarihi < h["en_erken_termin"]):
            h["en_erken_termin"] = t.termin_tarihi

    sonuc = []
    for bolge, h in havuz.items():
        arac = bolge_arac.get(bolge)
        cap_ag = arac["cap_ag"] if arac else 0.0
        cap_hc = arac["cap_hc"] if arac else 0.0
        doluluk = round(max(
            100 * h["agirlik"] / cap_ag if cap_ag else 0.0,
            100 * h["hacim"] / cap_hc if cap_hc else 0.0), 1) if arac else None

        en_eski_gun = (bugun - h["en_eski"].date()).days if h["en_eski"] else 0

        termin_durumu = "yok"
        if h["en_erken_termin"]:
            if h["en_erken_termin"] < bugun:
                termin_durumu = "gecmis"
            elif h["en_erken_termin"] == bugun:
                termin_durumu = "bugun"

        # Tetikleyici degerlendirmesi (sebep onceligi: termin > 3 gun > doluluk)
        sebep = None
        if termin_durumu in ("bugun", "gecmis"):
            sebep = f"termin {termin_durumu}"
        elif en_eski_gun >= BEKLEME_TAVANI_GUN:
            sebep = f"{en_eski_gun} gun bekledi"
        elif doluluk is not None and doluluk >= DOLULUK_ESIK:
            sebep = f"doluluk %{doluluk:.0f}"
        hazir = sebep is not None and arac is not None

        sonuc.append({
            "bolge": bolge,
            "arac_idler": arac["arac_idler"] if arac else [],
            "arac_adlari": arac["arac_adlari"] if arac else [],
            "teslimat_sayisi": h["teslimat_sayisi"],
            "agirlik": round(h["agirlik"], 1),
            "hacim": round(h["hacim"], 2),
            "max_agirlik": round(cap_ag, 1) if arac else None,
            "max_hacim": round(cap_hc, 2) if arac else None,
            "doluluk": doluluk,
            "en_eski_gun": en_eski_gun,
            "termin_durumu": termin_durumu,
            "hazir": hazir,
            "sebep": sebep,
        })

    sonuc.sort(key=lambda s: (not s["hazir"], -s["teslimat_sayisi"]))
    return sonuc, bolgesiz, bugun


@app.route("/api/havuz", methods=["GET"])
def havuz_durum():
    session = Session()
    sonuc, bolgesiz, bugun = bolge_havuzu(session)
    session.close()
    return jsonify({
        "bugun": str(bugun),
        "esik": {"doluluk": DOLULUK_ESIK, "bekleme_gun": BEKLEME_TAVANI_GUN},
        "bolgeler": sonuc,
        "bolgesiz": bolgesiz,
    })


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
    # ilce ve formatted_address'i donuyoruz ki arayuz yeni teslimati listeyi
    # bastan cekmeden havuza yerlestirebilsin
    kayit = session.execute(text(
        "SELECT a.ilce, t.adres FROM teslimatlar t "
        "LEFT JOIN adresler a ON a.id = t.adres_id WHERE t.id = :id"
    ), {"id": yeni_id}).fetchone()
    session.commit()
    session.close()
    return jsonify({"id": yeni_id, "ilce": (kayit.ilce or "") if kayit else "",
                    "adres": (kayit.adres or "") if kayit else ""})


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
SERVIS_DK = 25.0       # teslimat basina sabit sure (montaj + tasima dahil)
VARDIYA_DK = 540.0     # 9 saatlik vardiya
HIZ_KMH = 25.0         # Istanbul ici ortalama hiz
YOL_SAPMA = 1.35       # kus ucusu mesafe -> gercek yol carpani
KOPRU_KM = 12.0        # Bogaz gecisi cezasi
HEDEF_DOLULUK = (70.0, 82.0)   # filo boyutlandirma uyarisi icin bant

# --- Doluluk-esikli sevkiyat tetikleyicileri -------------------------------
# Bir bolgenin araci ancak su kosullardan biri saglaninca yola cikar:
#   1) doluluk >= DOLULUK_ESIK (ekonomik yumusak hedef)
#   2) bekleyen bir yukun termini bugun/gecmis (sert kisit, esigi ezer)
#   3) en eski yukun yasi BEKLEME_TAVANI_GUN'u doldurmus (sonsuz beklemeyi keser)
DOLULUK_ESIK = 80.0
BEKLEME_TAVANI_GUN = 3

ANADOLU_ILCELERI = {
    "adalar", "atasehir", "beykoz", "cekmekoy", "kadikoy", "kartal", "maltepe",
    "pendik", "sancaktepe", "sultanbeyli", "sile", "tuzla", "umraniye", "uskudar",
}

# Bolge -> o bolgeye ait ilceler (sadelestirilmis). Her araca bir bolge atanir;
# teslimatlar ilcesine gore ilgili bolgenin havuzunda birikir. 18 bolge = 18 arac.
BOLGELER = {
    "Silivri-Çatalca": {"silivri", "catalca"},
    "Arnavutköy-Başakşehir": {"arnavutkoy", "basaksehir"},
    "Büyükçekmece-Beylikdüzü": {"buyukcekmece", "beylikduzu"},
    "Esenyurt": {"esenyurt"},
    "Avcılar-Küçükçekmece": {"avcilar", "kucukcekmece"},
    "Bakırköy-Bahçelievler": {"bakirkoy", "bahcelievler"},
    "Bağcılar-Güngören": {"bagcilar", "gungoren"},
    "Zeytinburnu-Fatih": {"zeytinburnu", "fatih"},
    "Esenler-Bayrampaşa-GOP": {"esenler", "bayrampasa", "gaziosmanpasa"},
    "Sultangazi-Eyüpsultan": {"sultangazi", "eyupsultan", "eyup"},
    "Beyoğlu-Şişli-Kağıthane": {"beyoglu", "sisli", "kagithane"},
    "Beşiktaş-Sarıyer": {"besiktas", "sariyer"},
    "Üsküdar-Kadıköy": {"uskudar", "kadikoy"},
    "Ümraniye-Ataşehir": {"umraniye", "atasehir"},
    "Beykoz-Çekmeköy-Şile": {"beykoz", "cekmekoy", "sile"},
    "Maltepe-Kartal": {"maltepe", "kartal"},
    "Sancaktepe-Sultanbeyli": {"sancaktepe", "sultanbeyli"},
    "Pendik-Tuzla": {"pendik", "tuzla"},
}

_TR_TABLO = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")


def sadelestir(s):
    return (s or "").translate(_TR_TABLO).lower().strip()


# ilce -> bolge etiketi ters aramasi (sadelestirilmis anahtar)
_ILCE_BOLGE = {ilce: ad for ad, ilceler in BOLGELER.items() for ilce in ilceler}


def bolge_bul(ilce):
    """Ilce adindan bolge etiketini dondurur; eslesme yoksa None."""
    return _ILCE_BOLGE.get(sadelestir(ilce))


@app.route("/api/dagit", methods=["POST"])
def otomatik_dagit():
    import math

    session = Session()
    araclar = session.execute(text(
        "SELECT id, adi, max_agirlik, max_hacim FROM araclar WHERE aktif = TRUE "
        "ORDER BY max_hacim, max_agirlik"
    )).fetchall()
    teslimatlar = session.execute(text("""
        SELECT t.id, t.agirlik, t.hacim, t.lat, t.lon, a.ilce
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
        "servis": SERVIS_DK,
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

    # rota metrikleri arayuzde gosterilebilsin diye kaliciya yaziliyor;
    # rota almayan araclarin eski degerleri temizlenir
    session.execute(text("UPDATE araclar SET son_rota_km = NULL, son_rota_dk = NULL"))
    for d in detaylar:
        session.execute(text(
            "UPDATE araclar SET son_rota_km = :km, son_rota_dk = :dk WHERE id = :id"
        ), {"km": d["km"], "dk": d["sure_dk"], "id": d["arac_id"]})
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


@app.route("/api/soforler", methods=["GET"])
def sofor_listele():
    session = Session()
    rows = session.execute(text(
        "SELECT * FROM soforler ORDER BY aktif DESC, ad"
    )).fetchall()
    session.close()
    return jsonify([{
        "id": r.id, "ad": r.ad, "telefon": r.telefon or "",
        "ev_adresi": r.ev_adresi or "",
        "ev_lat": float(r.ev_lat) if r.ev_lat is not None else None,
        "ev_lon": float(r.ev_lon) if r.ev_lon is not None else None,
        "aktif": r.aktif, "notlar": r.notlar or "",
    } for r in rows])


@app.route("/api/soforler", methods=["POST"])
def sofor_ekle():
    v = request.json or {}
    ad = (v.get("ad") or "").strip()
    if not ad:
        return jsonify({"hata": "Şoför adı zorunlu"}), 400
    session = Session()
    row = session.execute(text("""
        INSERT INTO soforler (ad, telefon, ev_adresi, ev_lat, ev_lon, aktif, notlar)
        VALUES (:ad, :tel, :adr, :lat, :lon, :aktif, :not)
        RETURNING id
    """), {
        "ad": ad, "tel": (v.get("telefon") or "").strip() or None,
        "adr": (v.get("ev_adresi") or "").strip() or None,
        "lat": v.get("ev_lat"), "lon": v.get("ev_lon"),
        "aktif": v.get("aktif", True), "not": (v.get("notlar") or "").strip() or None,
    })
    yeni_id = row.scalar()
    session.commit()
    session.close()
    return jsonify({"id": yeni_id, "ok": True})


@app.route("/api/soforler/<int:sofor_id>", methods=["PUT"])
def sofor_guncelle(sofor_id):
    v = request.json or {}
    # sadece gonderilen alanlari guncelle
    alanlar, param = [], {"id": sofor_id}
    esleme = {"ad": "ad", "telefon": "telefon", "ev_adresi": "ev_adresi",
              "ev_lat": "ev_lat", "ev_lon": "ev_lon", "aktif": "aktif", "notlar": "notlar"}
    for anahtar, kolon in esleme.items():
        if anahtar in v:
            alanlar.append(f"{kolon} = :{kolon}")
            deger = v[anahtar]
            if isinstance(deger, str):
                deger = deger.strip() or None
            param[kolon] = deger
    if not alanlar:
        return jsonify({"hata": "Güncellenecek alan yok"}), 400
    session = Session()
    session.execute(text(
        f"UPDATE soforler SET {', '.join(alanlar)} WHERE id = :id"), param)
    session.commit()
    session.close()
    return jsonify({"ok": True})


@app.route("/api/soforler/<int:sofor_id>", methods=["DELETE"])
def sofor_sil(sofor_id):
    session = Session()
    session.execute(text("DELETE FROM soforler WHERE id = :id"), {"id": sofor_id})
    session.commit()
    session.close()
    return jsonify({"ok": True})


@app.route("/api/araclar/<int:arac_id>/rota-qr", methods=["GET"])
def arac_rota_qr(arac_id):
    """Aracin teslimatlarini sira duzeninde Google Maps rota linkine cevirir,
    QR kodunu SVG olarak dondurur. Yol/path formati kullanilir (waypoints=...
    parametresine gore daha fazla durak destekler). Google API cagrisi YOK -
    sadece bir URL uretiyoruz, ucret olusmaz."""
    session = Session()
    depo = session.execute(text("SELECT lat, lon FROM depolar ORDER BY id LIMIT 1")).fetchone()
    duraklar = session.execute(text("""
        SELECT lat, lon FROM teslimatlar
        WHERE arac_id = :aid AND lat IS NOT NULL AND lon IS NOT NULL
        ORDER BY sira NULLS LAST, id
    """), {"aid": arac_id}).fetchall()
    session.close()

    if not duraklar:
        return jsonify({"hata": "Araçta konumlu teslimat yok"}), 404

    noktalar = []
    if depo:
        noktalar.append(f"{float(depo.lat):.6f},{float(depo.lon):.6f}")
    for d in duraklar:
        noktalar.append(f"{float(d.lat):.6f},{float(d.lon):.6f}")

    # Path formati: /maps/dir/depo/durak1/durak2/.../son
    url = "https://www.google.com/maps/dir/" + "/".join(noktalar)

    tampon = io.BytesIO()
    segno.make(url, error="m").save(tampon, kind="svg", scale=1, border=2)
    svg = tampon.getvalue().decode("utf-8")
    # inline gomme icin <?xml ...?> on ekini at
    if svg.lstrip().startswith("<?xml"):
        svg = svg[svg.index("<svg"):]

    return jsonify({"url": url, "svg": svg, "durak_sayisi": len(duraklar)})


@app.route("/api/teslimatlar/<int:tes_id>", methods=["DELETE"])
def teslimat_sil_api(tes_id):
    session = Session()
    # Adres kaydi teslimatla birlikte olusturuluyor; sadece teslimati silmek
    # adresler tablosunda yetim kayit birakir. Baska teslimat ayni adresi
    # kullanmiyorsa adres de silinir.
    adres_id = session.execute(text(
        "SELECT adres_id FROM teslimatlar WHERE id = :id"
    ), {"id": tes_id}).scalar()
    session.execute(text("DELETE FROM teslimatlar WHERE id = :id"), {"id": tes_id})
    if adres_id:
        kalan = session.execute(text(
            "SELECT COUNT(*) FROM teslimatlar WHERE adres_id = :aid"
        ), {"aid": adres_id}).scalar()
        if not kalan:
            session.execute(text("DELETE FROM adresler WHERE id = :aid"), {"aid": adres_id})
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
        "toplam_bekleme": sonuc["toplam_bekleme"],
        "toplam_bekleme_sn": sonuc["toplam_bekleme_sn"],
        "toplam_servis_sn": sonuc["toplam_servis_sn"],
        "varis_zamanlari": sonuc["varis_zamanlari"],
        "polyline": sonuc["polyline"],
        "bacak_polylines": sonuc["bacak_polylines"],
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(debug=True, port=port)
