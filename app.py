import os
from flask import Flask, request, jsonify, send_file
from datetime import datetime
from coklu_teslimat import teslimat_optimize

app = Flask(__name__)


@app.route("/")
def anasayfa():
    return send_file("templates/index.html")


@app.route("/optimize", methods=["POST"])
def optimize():
    veri = request.json

    depo = (veri["depo"]["lat"], veri["depo"]["lon"])
    kalkis = datetime.fromisoformat(veri["kalkis_zamani"])

    teslimatlar = []
    isimler = []
    pencereler = {}

    for i, t in enumerate(veri["teslimatlar"]):
        teslimatlar.append((t["lat"], t["lon"]))
        isimler.append(t.get("isim", f"Teslimat {i+1}"))

        if t.get("pencere_bas") and t.get("pencere_son"):
            pencereler[i] = (
                datetime.fromisoformat(t["pencere_bas"]),
                datetime.fromisoformat(t["pencere_son"]),
            )

    sonuc = teslimat_optimize(
        depo=depo,
        teslimatlar=teslimatlar,
        kalkis_zamani=kalkis,
        pencereler=pencereler,
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
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=True, port=port)
