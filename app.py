import os
import io
import math
import requests
import segno
from flask import Flask, request, jsonify, send_file
from datetime import datetime, date
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
DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"

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


@app.route("/plan")
def plan():
    return send_file("templates/plan.html")


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


@app.route("/api/yol", methods=["POST"])
def yol_bacak():
    """Iki nokta arasi yol (road-following) polyline'ini dondurur. TEK Directions
    cagrisi - UCRETLI. Harita sayfasinda esnaf eve donus bacagini kus ucusu yerine
    gercek yoldan cizmek icin kullanilir. Trafik/departure_time yok (sade geometri,
    en ucuz tarife)."""
    v = request.json or {}
    b, h = v.get("from"), v.get("to")
    if not b or not h:
        return jsonify({"hata": "from ve to gerekli"}), 400
    resp = requests.get(DIRECTIONS_URL, params={
        "origin": f"{b[0]},{b[1]}",
        "destination": f"{h[0]},{h[1]}",
        "key": API_KEY,
    })
    veri = resp.json()
    if veri.get("status") != "OK" or not veri.get("routes"):
        return jsonify({"hata": "Yol bulunamadi", "durum": veri.get("status")}), 502
    return jsonify({"polyline": veri["routes"][0]["overview_polyline"]["points"]})


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


@app.route("/api/araclar/<int:arac_id>/tamamla", methods=["POST"])
def arac_gunu_tamamla(arac_id):
    """Aracin o anki rotasini tamamlar: atanmis (durum='atandi') teslimatlari
    'teslim_edildi' yapar ve aracin son rota metrigini temizler. Boylece arac
    artik 'mesgul' sayilmaz, ertesi gunun planina cikabilir."""
    session = Session()
    n = session.execute(text(
        "UPDATE teslimatlar SET durum = 'teslim_edildi' "
        "WHERE arac_id = :id AND durum = 'atandi'"
    ), {"id": arac_id}).rowcount
    session.execute(text(
        "UPDATE araclar SET son_rota_km = NULL, son_rota_dk = NULL WHERE id = :id"
    ), {"id": arac_id})
    session.commit()
    session.close()
    return jsonify({"ok": True, "teslim_edilen": n})


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


GUN_ADLARI = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


def _gun_ciktisi(gunler, gun_bolge, bolge_arac, cakismalar=None):
    """Gun+bolge yuk ozetinden takvim ciktisini kurar (POST plan ve GET plan-durum
    ayni sekli dondursun diye ortak). cakismalar: {(gun,bolge): [cakisma grubu]}."""
    cakismalar = cakismalar or {}
    out = []
    for g in gunler:
        bolgeler = []
        for (gg, bolge), d in gun_bolge.items():
            if gg != g:
                continue
            arac = bolge_arac.get(bolge, {})
            cap_ag = arac.get("cap_ag") or 1
            cap_hc = arac.get("cap_hc") or 1
            doluluk = round(max(100 * d["ag"] / cap_ag, 100 * d["hc"] / cap_hc), 1)
            bolgeler.append({
                "bolge": bolge, "arac": arac.get("adi", ""),
                "teslimat_sayisi": d["adet"],
                "agirlik": round(d["ag"], 1), "hacim": round(d["hc"], 2),
                "doluluk": doluluk, "kesin_adet": d["kesin"],
                "cakisma": cakismalar.get((gg, bolge), [])})
        bolgeler.sort(key=lambda x: -x["teslimat_sayisi"])
        out.append({
            "tarih": str(g), "gun_adi": GUN_ADLARI[g.weekday()], "bolgeler": bolgeler})
    return out


def _kus_ucusu_km(a, b):
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h)) * YOL_SAPMA


def _nn_zincir_dk(noktalar):
    """Noktalar arasi en-yakin-komsu zincirinin yol suresi (dk), haversine ile."""
    if len(noktalar) < 2:
        return 0.0
    kalan, cur, toplam = list(noktalar[1:]), noktalar[0], 0.0
    while kalan:
        nx = min(kalan, key=lambda p: _kus_ucusu_km(cur, p))
        toplam += _kus_ucusu_km(cur, nx)
        cur = nx
        kalan.remove(nx)
    return toplam / HIZ_KMH * 60.0


def _dk_saat(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def pencere_cakismalari(teslimatlar):
    """Bir aracin pencereli teslimatlarini AYNI pencereye gore gruplar; bir grup
    tek araca sigmiyorsa (N*servis + haversine yol > pencere suresi) cakisma sayar.
    UCRETSIZ - Google yok. Haversine iyimser oldugu icin 'cakisiyor' dedigi gercek.
    teslimatlar: [{id, adi, lat, lon, bas(dk), son(dk)}]. Doner: cakisan gruplar."""
    pencereli = [t for t in teslimatlar if t.get("bas") is not None and t.get("lat") is not None]
    gruplar = {}
    for t in pencereli:
        gruplar.setdefault((t["bas"], t["son"]), []).append(t)

    cakismalar = []
    for (bas, son), grup in gruplar.items():
        if len(grup) < 2:
            continue
        mevcut = son - bas
        gereken = len(grup) * SERVIS_DK + _nn_zincir_dk([(t["lat"], t["lon"]) for t in grup])
        if gereken > mevcut:
            cakismalar.append({
                "pencere": f"{_dk_saat(bas)}-{_dk_saat(son)}",
                "teslimat_sayisi": len(grup),
                "gereken_dk": round(gereken),
                "mevcut_dk": round(mevcut),
                "teslimatlar": [{"id": t["id"], "adi": t["adi"]} for t in grup],
            })
    cakismalar.sort(key=lambda c: -c["teslimat_sayisi"])
    return cakismalar


def _teslimat_pencere(r):
    """DB satirindan pencere_cakismalari girdisi (bas/son dakika)."""
    bas = r.randevu_bas.hour * 60 + r.randevu_bas.minute if r.randevu_bas else None
    son = r.randevu_son.hour * 60 + r.randevu_son.minute if r.randevu_son else None
    return {"id": r.id, "adi": r.adi,
            "lat": float(r.lat) if r.lat is not None else None,
            "lon": float(r.lon) if r.lon is not None else None,
            "bas": bas, "son": son}


@app.route("/api/pencere-kontrol", methods=["POST"])
def pencere_kontrol():
    """Verilen teslimat listesindeki pencere cakismalarini dondurur - UCRETSIZ.
    Harita 'Google ile Optimize'den once bunu cagirir; cakisma varsa Google'a
    (ucretli) gonderilmeden once uyarilir."""
    v = request.json or {}
    tesler = []
    for i, t in enumerate(v.get("teslimatlar", [])):
        bas = son = None
        if t.get("pencere_bas") and t.get("pencere_son"):
            try:
                db = datetime.fromisoformat(t["pencere_bas"])
                ds = datetime.fromisoformat(t["pencere_son"])
                bas, son = db.hour * 60 + db.minute, ds.hour * 60 + ds.minute
            except (ValueError, TypeError):
                pass
        tesler.append({"id": i, "adi": t.get("isim", f"Teslimat {i+1}"),
                       "lat": t.get("lat"), "lon": t.get("lon"), "bas": bas, "son": son})
    return jsonify({"cakismalar": pencere_cakismalari(tesler)})


@app.route("/api/arac-cakismalari", methods=["GET"])
def arac_cakismalari():
    """Her aracin ATANMIS teslimatlarindaki pencere cakismalari (Filo bayragi icin)."""
    session = Session()
    rows = session.execute(text("""
        SELECT t.id, t.adi, t.lat, t.lon, t.randevu_bas, t.randevu_son, t.arac_id
        FROM teslimatlar t
        WHERE t.arac_id IS NOT NULL AND t.durum = 'atandi'
    """)).fetchall()
    session.close()
    arac_tesler = {}
    for r in rows:
        arac_tesler.setdefault(r.arac_id, []).append(_teslimat_pencere(r))
    sonuc = {}
    for aid, tesler in arac_tesler.items():
        c = pencere_cakismalari(tesler)
        if c:
            sonuc[str(aid)] = c
    return jsonify(sonuc)


def _bolge_arac_kapasite(session):
    """Bolge -> {adi, cap_ag, cap_hc} (1 bolge = 1 arac; birden fazlaysa toplanir)."""
    rows = session.execute(text(
        "SELECT adi, max_agirlik, max_hacim, bolge FROM araclar "
        "WHERE aktif = TRUE AND bolge IS NOT NULL")).fetchall()
    bolge_arac = {}
    for a in rows:
        b = bolge_arac.setdefault(a.bolge, {"adi": a.adi, "cap_ag": 0.0, "cap_hc": 0.0})
        b["cap_ag"] += float(a.max_agirlik)
        b["cap_hc"] += float(a.max_hacim)
    return bolge_arac


@app.route("/api/plan-durum", methods=["GET"])
def plan_durum():
    """Mevcut haftalik plani (salt okunur) takvim olarak dondurur - yeniden
    hesaplamaz. Arayuz acilista ve kilit degisiminden sonra bunu kullanir."""
    from datetime import timedelta
    bas_str = request.args.get("baslangic")
    try:
        baslangic = datetime.strptime(bas_str, "%Y-%m-%d").date() if bas_str \
            else datetime.now().date()
    except (ValueError, TypeError):
        baslangic = datetime.now().date()
    gun_sayisi = max(1, min(int(request.args.get("gun_sayisi") or 7), 14))
    gunler = [baslangic + timedelta(days=i) for i in range(gun_sayisi)]

    session = Session()
    bolge_arac = _bolge_arac_kapasite(session)
    rows = session.execute(text("""
        SELECT t.id, t.adi, t.agirlik, t.hacim, t.lat, t.lon,
               t.randevu_bas, t.randevu_son, t.planlanan_gun, t.kesinlesmis, a.ilce
        FROM teslimatlar t LEFT JOIN adresler a ON a.id = t.adres_id
        WHERE t.arac_id IS NULL AND t.planlanan_gun = ANY(:gunler)
    """), {"gunler": gunler}).fetchall()
    session.close()

    gun_bolge = {}
    hucre_tesler = {}   # (gun,bolge) -> pencere kontrolu icin teslimat listesi
    for r in rows:
        bolge = bolge_bul(r.ilce)
        if not bolge:
            continue
        anahtar = (r.planlanan_gun, bolge)
        d = gun_bolge.setdefault(anahtar, {"adet": 0, "ag": 0.0, "hc": 0.0, "kesin": 0})
        d["adet"] += 1
        d["ag"] += float(r.agirlik or 0)
        d["hc"] += float(r.hacim or 0)
        if r.kesinlesmis:
            d["kesin"] += 1
        hucre_tesler.setdefault(anahtar, []).append(_teslimat_pencere(r))

    cakismalar = {k: pencere_cakismalari(v) for k, v in hucre_tesler.items()}
    cakismalar = {k: v for k, v in cakismalar.items() if v}

    return jsonify({
        "baslangic": str(baslangic),
        "gun_sayisi": gun_sayisi,
        "gunler": _gun_ciktisi(gunler, gun_bolge, bolge_arac, cakismalar),
    })


@app.route("/api/plan/kesinlestir", methods=["POST"])
def plan_kesinlestir():
    """Bir gun+bolge hucresindeki (planlanan_gun=tarih, o bolgenin) atanmamis
    teslimatlarin plan kilidini acar/kapatir. kesinlesmis=TRUE ise sonraki
    haftalik plan bu teslimatlara dokunmaz. Arayuzdeki kilit ikonu buraya basar."""
    v = request.json or {}
    tarih = v.get("tarih")
    bolge = v.get("bolge")
    kesin = bool(v.get("kesinlesmis"))
    if not tarih or not bolge:
        return jsonify({"hata": "tarih ve bolge gerekli"}), 400

    session = Session()
    # O gune planlanmis atanmamis teslimatlari cek, bolgeye gore filtrele
    rows = session.execute(text("""
        SELECT t.id, a.ilce FROM teslimatlar t
        LEFT JOIN adresler a ON a.id = t.adres_id
        WHERE t.planlanan_gun = :g AND t.arac_id IS NULL
    """), {"g": tarih}).fetchall()
    idler = [r.id for r in rows if bolge_bul(r.ilce) == bolge]
    if idler:
        session.execute(text(
            "UPDATE teslimatlar SET kesinlesmis = :k WHERE id = ANY(:ids)"),
            {"k": kesin, "ids": idler})
        session.commit()
    session.close()
    return jsonify({"ok": True, "kesinlesmis": kesin, "etkilenen": len(idler)})


@app.route("/api/haftalik-plan", methods=["POST"])
def haftalik_plan():
    """Bekleyen teslimatlari ~1 haftalik takvime dagitir (rota degil, GUN atamasi).
    Sadece kesinlesmemis (kesinlesmis=FALSE) teslimatlara dokunur; kesinlesmis
    olanlar yerinde kalir ama gunlerinin kapasitesini dusurur. Her teslimatin
    gunu terminini asamaz; ayni bolge ayni gune toplanir (kumeleme)."""
    from datetime import timedelta

    v = request.json or {}
    bas_str = v.get("baslangic")
    try:
        baslangic = datetime.strptime(bas_str, "%Y-%m-%d").date() if bas_str \
            else datetime.now().date()
    except (ValueError, TypeError):
        baslangic = datetime.now().date()
    gun_sayisi = max(1, min(int(v.get("gun_sayisi") or 7), 14))
    gunler = [baslangic + timedelta(days=i) for i in range(gun_sayisi)]

    session = Session()

    # Bolge -> arac kapasitesi (1 bolge = 1 arac; birden fazlaysa toplanir)
    arac_rows = session.execute(text(
        "SELECT id, adi, max_agirlik, max_hacim, bolge FROM araclar "
        "WHERE aktif = TRUE AND bolge IS NOT NULL")).fetchall()
    bolge_arac = {}
    for a in arac_rows:
        b = bolge_arac.setdefault(a.bolge, {"adi": a.adi, "cap_ag": 0.0, "cap_hc": 0.0})
        b["cap_ag"] += float(a.max_agirlik)
        b["cap_hc"] += float(a.max_hacim)

    # Bekleyen (atanmamis, konumu belli) teslimatlar - kesinlesmis dahil
    tes_rows = session.execute(text("""
        SELECT t.id, t.adi, t.agirlik, t.hacim, t.termin_tarihi, t.olusturma_zamani,
               t.planlanan_gun, t.kesinlesmis, a.ilce
        FROM teslimatlar t LEFT JOIN adresler a ON a.id = t.adres_id
        WHERE t.arac_id IS NULL AND t.lat IS NOT NULL AND t.lon IS NOT NULL
    """)).fetchall()
    session.close()

    ILERI = date.max
    bolge_veri = {}   # bolge -> {plansiz:[...], kilitli_yuk:{gun:[ag,hc]}}
    tes_map = {}      # id -> {bolge, ag, hc, kesin}
    bolgesiz = 0
    for t in tes_rows:
        bolge = bolge_bul(t.ilce)
        ag, hc = float(t.agirlik or 0), float(t.hacim or 0)
        if not bolge:
            if not t.kesinlesmis:
                bolgesiz += 1
            continue
        tes_map[t.id] = {"bolge": bolge, "ag": ag, "hc": hc, "kesin": bool(t.kesinlesmis)}
        bv = bolge_veri.setdefault(bolge, {"plansiz": [], "kilitli_yuk": {}})
        if t.kesinlesmis:
            if t.planlanan_gun:
                gy = bv["kilitli_yuk"].setdefault(t.planlanan_gun, [0.0, 0.0])
                gy[0] += ag
                gy[1] += hc
        else:
            bv["plansiz"].append({
                "id": t.id, "adi": t.adi, "ag": ag, "hc": hc,
                "termin": t.termin_tarihi or ILERI,
                "olusturma": t.olusturma_zamani or datetime.now()})

    atamalar = {}   # tes_id -> gun (date)
    sigmayan = []   # {id, bolge, neden}
    for bolge, bv in bolge_veri.items():
        arac = bolge_arac.get(bolge)
        if not arac:
            for t in bv["plansiz"]:
                sigmayan.append({
                    "id": t["id"], "adi": t["adi"], "bolge": bolge, "termin": None,
                    "kategori": "araç yok",
                    "aciklama": f"{bolge} bölgesine atanmış araç yok — hiçbir güne konamaz"})
            continue
        # Gun bazli kalan kapasite (kilitli yukler onceden dusuldu)
        kalan = {}
        for g in gunler:
            ky = bv["kilitli_yuk"].get(g, [0.0, 0.0])
            kalan[g] = [arac["cap_ag"] - ky[0], arac["cap_hc"] - ky[1]]
        # Termine gore yerlestir; her yuk EN DOLU uygun gune (kumeleme), esitlikte en erken
        for t in sorted(bv["plansiz"], key=lambda x: (x["termin"], x["olusturma"])):
            adaylar = [g for g in gunler
                       if g <= t["termin"] and kalan[g][0] >= t["ag"] and kalan[g][1] >= t["hc"]]
            if not adaylar:
                termin_str = str(t["termin"]) if t["termin"] != ILERI else None
                if t["termin"] == ILERI:
                    kategori = "hafta dolu"
                    aciklama = f"{bolge} aracı tüm hafta dolu (bu teslimatın termini yok)"
                elif t["termin"] < gunler[0]:
                    kategori = "termin geçmiş"
                    aciklama = f"termin {termin_str} — plan başlangıcından önce (geçmiş tarih)"
                else:
                    kategori = "termine kadar dolu"
                    aciklama = (f"termini {termin_str}; {bolge} aracı o güne kadarki "
                                f"günlerde dolu (boş günler bu terminden sonra, kullanılamaz)")
                sigmayan.append({"id": t["id"], "adi": t["adi"], "bolge": bolge,
                                 "termin": termin_str, "kategori": kategori, "aciklama": aciklama})
                continue
            hedef = max(adaylar, key=lambda g: (
                (arac["cap_ag"] - kalan[g][0]) + (arac["cap_hc"] - kalan[g][1]),
                -(g - gunler[0]).days))
            kalan[hedef][0] -= t["ag"]
            kalan[hedef][1] -= t["hc"]
            atamalar[t["id"]] = hedef

    # Yaz: kesinlesmemis teslimatlarin planlanan_gun'unu guncelle
    session = Session()
    for tid, gun in atamalar.items():
        session.execute(text(
            "UPDATE teslimatlar SET planlanan_gun = :g WHERE id = :id AND NOT kesinlesmis"),
            {"g": gun, "id": tid})
    sig_idler = [s["id"] for s in sigmayan]
    if sig_idler:
        session.execute(text(
            "UPDATE teslimatlar SET planlanan_gun = NULL WHERE id = ANY(:ids) AND NOT kesinlesmis"),
            {"ids": sig_idler})
    session.commit()
    session.close()

    # Ozet: gun -> bolge -> yuk. Hem atanan hem kilitli yukler gosterilir.
    gun_bolge = {}   # (gun, bolge) -> {adet, ag, hc, kesin}

    def ekle(gun, bolge, ag, hc, kesin):
        d = gun_bolge.setdefault((gun, bolge), {"adet": 0, "ag": 0.0, "hc": 0.0, "kesin": 0})
        d["adet"] += 1
        d["ag"] += ag
        d["hc"] += hc
        if kesin:
            d["kesin"] += 1

    for tid, gun in atamalar.items():
        m = tes_map[tid]
        ekle(gun, m["bolge"], m["ag"], m["hc"], False)
    for t in tes_rows:
        if t.kesinlesmis and t.planlanan_gun and t.planlanan_gun in gunler:
            b = bolge_bul(t.ilce)
            if b:
                ekle(t.planlanan_gun, b, float(t.agirlik or 0), float(t.hacim or 0), True)

    gun_ciktisi = _gun_ciktisi(gunler, gun_bolge, bolge_arac)

    uyarilar = []
    if atamalar:
        uyarilar.append(f"{len(atamalar)} teslimat {gun_sayisi} güne planlandı")
    if sigmayan:
        uyarilar.append(f"{len(sigmayan)} teslimat plana sığmadı (termin/kapasite)")
    if bolgesiz:
        uyarilar.append(f"{bolgesiz} teslimat bölgesiz — ilçesi bir bölgeye eşlenmiyor")

    return jsonify({
        "baslangic": str(baslangic),
        "gun_sayisi": gun_sayisi,
        "gunler": gun_ciktisi,
        "sigmayanlar": sigmayan,
        "bolgesiz": bolgesiz,
        "ozet": {"planlanan": len(atamalar), "sigmayan": len(sigmayan)},
        "uyarilar": uyarilar,
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
# Dagitim parametreleri (doluluk-esikli bolge dagitimi + bolge-ici 2-opt)
# Kat suresi sonucu en cok degistiren varsayimdir; sahadan gercek deger
# geldiginde once burasi guncellenmeli.
# ---------------------------------------------------------------------------
SERVIS_DK = 25.0       # teslimat basina sabit sure (montaj + tasima dahil)
VARDIYA_DK = 540.0     # 9 saatlik vardiya
HIZ_KMH = 25.0         # Istanbul ici ortalama hiz
YOL_SAPMA = 1.35       # kus ucusu mesafe -> gercek yol carpani
KOPRU_KM = 12.0        # Bogaz gecisi cezasi

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

    # 1) Hangi gunun plani rotalanacak? (varsayilan: bugun). Haftalik plan gunleri
    #    onceden atar; /api/dagit o gunun planini rotaya cevirir (rota o gun cikar).
    v = request.json or {}
    tarih_str = v.get("tarih")
    try:
        tarih = datetime.strptime(tarih_str, "%Y-%m-%d").date() if tarih_str \
            else datetime.now().date()
    except (ValueError, TypeError):
        tarih = datetime.now().date()

    planli_sayi = session.execute(text(
        "SELECT count(*) FROM teslimatlar "
        "WHERE arac_id IS NULL AND planlanan_gun = :g AND lat IS NOT NULL"
    ), {"g": tarih}).scalar()
    if not planli_sayi:
        session.close()
        return jsonify({
            "atamalar": {}, "rotalar": [], "acikta_teslimatlar": [], "bolgesiz": 0,
            "ozet": {"teslimat": 0, "atanan": 0, "acikta": 0, "kullanilan_arac": 0,
                     "toplam_arac": 0, "toplam_km": 0.0, "doluluk_agirlik": 0.0,
                     "doluluk_hacim": 0.0, "vardiya_yuzde": 0, "tarih": str(tarih)},
            "uyarilar": [f"{tarih} gününe planlanmış teslimat yok — önce Haftalık Planla"],
        })

    depo = session.execute(text("SELECT * FROM depolar ORDER BY id LIMIT 1")).fetchone()
    depo_lat = float(depo.lat) if depo else 40.98
    depo_lon = float(depo.lon) if depo else 28.872
    depo_pt = (depo_lat, depo_lon)

    # 2) Bolge -> o bolgeye bakan aktif araclar (soforun ev konumuyla birlikte)
    arac_rows = session.execute(text(
        "SELECT a.id, a.adi, a.max_agirlik, a.max_hacim, a.bolge, "
        "       s.ev_lat, s.ev_lon "
        "FROM araclar a LEFT JOIN soforler s ON s.id = a.sofor_id "
        "WHERE a.aktif = TRUE AND a.bolge IS NOT NULL"
    )).fetchall()
    bolge_araclar = {}
    for a in arac_rows:
        # Acik rota icin soforun ev konumu; yoksa rota depoya doner (kapali)
        ev_pt = (float(a.ev_lat), float(a.ev_lon)) if a.ev_lat is not None \
            and a.ev_lon is not None else None
        bolge_araclar.setdefault(a.bolge, []).append({
            "id": a.id, "adi": a.adi,
            "mag": float(a.max_agirlik), "mhc": float(a.max_hacim), "ev": ev_pt})

    # Yolda (mesgul) araclar: halihazirda atanmis teslimati olanlar tekrar
    # yuklenemez. Bir bolgenin araci mesgulse o bolge bugun cikamaz.
    mesgul_idler = {r.arac_id for r in session.execute(text(
        "SELECT DISTINCT arac_id FROM teslimatlar "
        "WHERE arac_id IS NOT NULL AND durum = 'atandi'"
    )).fetchall() if r.arac_id is not None}

    # 3) O gune planlanmis (henuz rotalanmamis) teslimatlari bolgeye gore grupla
    tes_rows = session.execute(text("""
        SELECT t.id, t.agirlik, t.hacim, t.lat, t.lon,
               t.termin_tarihi, t.olusturma_zamani, a.ilce
        FROM teslimatlar t
        LEFT JOIN adresler a ON a.id = t.adres_id
        WHERE t.arac_id IS NULL AND t.planlanan_gun = :g
              AND t.lat IS NOT NULL AND t.lon IS NOT NULL
    """), {"g": tarih}).fetchall()

    ILERI_TARIH = date.max
    bolge_tesler = {}
    for t in tes_rows:
        bolge = bolge_bul(t.ilce)
        if not bolge:
            continue
        bolge_tesler.setdefault(bolge, []).append({
            "id": t.id,
            "ag": float(t.agirlik or 0),
            "hc": float(t.hacim or 0),
            "pt": (float(t.lat), float(t.lon)),
            "yaka": "A" if sadelestir(t.ilce) in ANADOLU_ILCELERI else "E",
            "servis": SERVIS_DK,
            "termin": t.termin_tarihi or ILERI_TARIH,
            "olusturma": t.olusturma_zamani or datetime.now(),
        })

    # --- Geometri ve rota yardimcilari -------------------------------------
    # Esnaf acik rota: depo -> duraklar -> soforun evi (ev_pt). Ev yoksa rota
    # depoya doner (kapali). KRITIK: eve donus bacagi YOL'a (hedef, 2-opt) girer
    # ama MESAI'ye (vardiya kisiti) girmez - ikisi ayri hesaplanir.
    def kus_ucusu(a, b):
        yer_yaricapi = 6371.0
        p1, p2 = math.radians(a[0]), math.radians(b[0])
        dp, dl = p2 - p1, math.radians(b[1] - a[1])
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * yer_yaricapi * math.asin(math.sqrt(h)) * YOL_SAPMA

    def mesafe(a_yaka, a_pt, b_yaka, b_pt):
        return kus_ucusu(a_pt, b_pt) + (KOPRU_KM if a_yaka != b_yaka else 0.0)

    def kapanis_km(seq, ev_pt):
        # rotanin son duragindan kapanis: eve (ev soforun bolgesinde, ayni yaka
        # varsayilir -> kopru cezasi yok) ya da ev yoksa depoya
        son = seq[-1]
        if ev_pt is not None:
            return kus_ucusu(son["pt"], ev_pt)
        return mesafe(depo_yaka, depo_pt, son["yaka"], son["pt"])

    def yol_km(seq, ev_pt=None):
        # Toplam yol (hedef): depo -> duraklar -> ev/depo. Kapanis DAHIL.
        if not seq:
            return 0.0
        km = mesafe(depo_yaka, depo_pt, seq[0]["yaka"], seq[0]["pt"])
        for a, b in zip(seq, seq[1:]):
            km += mesafe(a["yaka"], a["pt"], b["yaka"], b["pt"])
        return km + kapanis_km(seq, ev_pt)

    def mesai_dk(seq):
        # Vardiya (kisit): depo -> son teslimat + servisler. Kapanis bacagi HARIC.
        if not seq:
            return 0.0
        km = mesafe(depo_yaka, depo_pt, seq[0]["yaka"], seq[0]["pt"])
        for a, b in zip(seq, seq[1:]):
            km += mesafe(a["yaka"], a["pt"], b["yaka"], b["pt"])
        return km / HIZ_KMH * 60.0 + sum(t["servis"] for t in seq)

    def en_yakin_komsu(secili):
        kalan, sirali = list(secili), []
        cur_yaka, cur_pt = depo_yaka, depo_pt
        while kalan:
            nx = min(kalan, key=lambda t: mesafe(cur_yaka, cur_pt, t["yaka"], t["pt"]))
            sirali.append(nx)
            kalan.remove(nx)
            cur_yaka, cur_pt = nx["yaka"], nx["pt"]
        return sirali

    def iki_opt(seq, ev_pt=None):
        if len(seq) < 4:
            return seq
        gelisti = True
        while gelisti:
            gelisti = False
            for a in range(len(seq) - 1):
                for b in range(a + 2, len(seq)):
                    aday = seq[:a + 1] + seq[a + 1:b + 1][::-1] + seq[b + 1:]
                    if yol_km(aday, ev_pt) < yol_km(seq, ev_pt) - 1e-9:
                        seq, gelisti = aday, True
        return seq

    # Depo yakasi en yakin teslimattan cikariliyor (adres kaydinda tutulmuyor)
    tum_tesler = [t for ts in bolge_tesler.values() for t in ts]
    depo_yaka = min(tum_tesler, key=lambda t: (t["pt"][0] - depo_lat) ** 2
                    + (t["pt"][1] - depo_lon) ** 2)["yaka"] if tum_tesler else "E"

    # 4) Her hazir bolgeyi kendi aracina, oncelik sirasiyla (termin, sonra yas)
    #    sigdigi kadar yukle. Sigmayan havuzda bekler (arac_id NULL kalir).
    atamalar, detaylar, acikta = {}, [], []
    uyarilar = []
    for bolge in bolge_tesler:
        araclar_b = [a for a in bolge_araclar.get(bolge, []) if a["id"] not in mesgul_idler]
        if not bolge_araclar.get(bolge):
            uyarilar.append(f"{bolge}: atanmış araç yok — plan rotalanamadı")
            continue
        if not araclar_b:
            uyarilar.append(f"{bolge}: aracı yolda (meşgul) — plan rotalanamadı")
            continue

        kalan_tes = sorted(bolge_tesler.get(bolge, []),
                           key=lambda t: (t["termin"], t["olusturma"]))
        for arac in araclar_b:
            if not kalan_tes:
                break
            secili, kalan_ag, kalan_hc, artik = [], arac["mag"], arac["mhc"], []
            for t in kalan_tes:
                if t["ag"] <= kalan_ag and t["hc"] <= kalan_hc:
                    secili.append(t)
                    kalan_ag -= t["ag"]
                    kalan_hc -= t["hc"]
                else:
                    artik.append(t)
            kalan_tes = artik
            if not secili:
                continue

            ev_pt = arac["ev"]
            sirali = iki_opt(en_yakin_komsu(secili), ev_pt)
            ag = sum(t["ag"] for t in sirali)
            hc = sum(t["hc"] for t in sirali)
            dk = mesai_dk(sirali)
            atamalar[arac["id"]] = [t["id"] for t in sirali]
            vardiya_yuzde = round(100 * dk / VARDIYA_DK)
            detaylar.append({
                "arac_id": arac["id"], "arac_adi": arac["adi"], "bolge": bolge,
                "teslimat_sayisi": len(sirali),
                "km": round(yol_km(sirali, ev_pt), 1),
                "sure_dk": round(dk),
                "acik_rota": ev_pt is not None,
                "ev_km": round(kapanis_km(sirali, ev_pt), 1) if ev_pt is not None else None,
                "agirlik": round(ag, 1), "max_agirlik": arac["mag"],
                "hacim": round(hc, 2), "max_hacim": arac["mhc"],
                "doluluk_agirlik": round(100 * ag / arac["mag"], 1),
                "doluluk_hacim": round(100 * hc / arac["mhc"], 1),
                "vardiya_yuzde": vardiya_yuzde,
                "sebep": f"{tarih} planı",
            })
            if vardiya_yuzde > 100:
                uyarilar.append(
                    f"{arac['adi']} ({bolge}) vardiyayı aşıyor (%{vardiya_yuzde}) "
                    f"— rota 9 saate sığmıyor")

        # bolgenin aracina sigmayan yukler (plan kapasiteyi asmis olabilir)
        if kalan_tes:
            acikta.extend(t["id"] for t in kalan_tes)
            uyarilar.append(
                f"{bolge}: {len(kalan_tes)} yük araca sığmadı — planı gözden geçirin")

    # 5) Yazma: atanan teslimatlar + sira; sadece cikan araclarin rota metrigi
    for arac_id, tes_idler in atamalar.items():
        for sira, tid in enumerate(tes_idler, 1):
            session.execute(text(
                "UPDATE teslimatlar SET arac_id = :arac_id, durum = 'atandi', sira = :sira "
                "WHERE id = :tid"
            ), {"arac_id": arac_id, "sira": sira, "tid": tid})
    for d in detaylar:
        session.execute(text(
            "UPDATE araclar SET son_rota_km = :km, son_rota_dk = :dk WHERE id = :id"
        ), {"km": d["km"], "dk": d["sure_dk"], "id": d["arac_id"]})
    session.commit()
    session.close()

    # 6) Ozet ve uyarilar
    kullanilan = len(detaylar)
    atanan = sum(d["teslimat_sayisi"] for d in detaylar)
    top_km = round(sum(d["km"] for d in detaylar), 1)
    top_ag = sum(d["agirlik"] for d in detaylar)
    top_hc = sum(d["hacim"] for d in detaylar)
    kap_ag = sum(d["max_agirlik"] for d in detaylar) or 1
    kap_hc = sum(d["max_hacim"] for d in detaylar) or 1
    dol_ag = round(100 * top_ag / kap_ag, 1)
    dol_hc = round(100 * top_hc / kap_hc, 1)
    vardiya = round(100 * sum(d["sure_dk"] for d in detaylar)
                    / (kullanilan * VARDIYA_DK)) if kullanilan else 0

    if kullanilan:
        uyarilar.insert(0, f"{tarih}: {kullanilan} araç rotalandı, {atanan} teslimat")

    return jsonify({
        "atamalar": {str(k): v for k, v in atamalar.items()},
        "ozet": {
            "teslimat": atanan + len(acikta),
            "atanan": atanan,
            "acikta": len(acikta),
            "kullanilan_arac": kullanilan,
            "toplam_arac": len(arac_rows),
            "toplam_km": top_km,
            "doluluk_agirlik": dol_ag,
            "doluluk_hacim": dol_hc,
            "vardiya_yuzde": vardiya,
            "tarih": str(tarih),
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
